"""META web-catch: extract company facts from websites into META fields.

Two layers:
1. Regex (offline, free): SSM numbers, MSIC codes, incorporation year,
   paid-up capital — from dossier snippets + fetched page text.
2. AI extraction (factual mode, never invents): legal name, aktiviti,
   address, MSIC, SSM — from the collected web text.

Filled META fields carry Web sources (domain + confidence), so the rest
of the pipeline (anchors/AI/offline) treats them as known facts.
SSM/MSIC stay out of AI *estimation* (MANUAL_ONLY) but CAN be caught
from the web here.
"""
from __future__ import annotations
import re

BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36"}
TIMEOUT = 15

META_FIDS = {
    "nama": "META::Company / Syarikat",
    "ssm": "META::SSM No. Pendaftaran",
    "msic": "META::Kod MSIC (Newss)",
    "aktiviti": "META::Aktiviti utama",
    "alamat": "META::Alamat berdaftar",
    "tahun": "META::Tahun mula operasi",
    "modal": "META::Modal berbayar (Capital)",
}

SSM_RES = [
    re.compile(r"(?:Registration No|No\.?\s*Pendaftaran|Company No|SSM)"
               r"[\s:]*([A-Z0-9][A-Z0-9\-/]{4,20})", re.I),
    re.compile(r"\b(\d{12})\b"),            # 201901023456 new format
    re.compile(r"\b(\d{6,7}-[A-Z])\b"),     # 1234567-X old format
]
MSIC_RE = re.compile(r"MSIC[^0-9]{0,20}(\d{5})", re.I)
TAHUN_RES = [
    re.compile(r"incorporat\w*\s+(?:in\s+|on\s+)?(\d{4})", re.I),
    re.compile(r"ditubuhkan(?:\s+pada)?\s+(\d{4})", re.I),
    re.compile(r"(?:established|founded|since)\s+(?:in\s+)?(\d{4})", re.I),
    re.compile(r"ditubuhkan\s+pada\s+\d{1,2}/\d{1,2}/(\d{4})", re.I),
]
MODAL_RE = re.compile(
    r"(?:paid[\s-]*up|modal\s+berbayar|modal\s+dibenarkan|issued\s+capital)"
    r"[^\dRM]{0,25}RM?\s*([\d,]+)", re.I)


def kumpul_teks(dossier: dict, max_pages: int = 4) -> list[tuple[str, str]]:
    """Fetch readable text of top evidence pages. Returns [(url, text)]."""
    import requests
    out: list[tuple[str, str]] = []
    for h in (dossier.get("hasil", []) or [])[:max_pages]:
        url = h.get("url", "")
        if not url or "bing.com/ck/" in url:
            continue
        try:
            r = requests.get(url, headers=BROWSER, timeout=TIMEOUT)
            if r.status_code != 200 or not r.text:
                continue
            teks = re.sub(r"<script.*?</script>", " ", r.text,
                          flags=re.S | re.I)
            teks = re.sub(r"<style.*?</style>", " ", teks, flags=re.S | re.I)
            teks = re.sub(r"<.*?>", " ", teks)
            teks = re.sub(r"\s+", " ", teks).strip()[:6000]
            if len(teks) > 200:
                out.append((url, teks))
        except Exception:
            continue
    # always include snippets as a pseudo-page (free, no fetch)
    snip = " ".join(f"{h.get('tajuk','')} {h.get('petikan','')}"
                    for h in (dossier.get("hasil", []) or []))[:4000]
    if snip.strip():
        out.append(("carian:ringkasan", snip))
    return out


def ekstrak_regex(teks_list: list[tuple[str, str]]) -> dict:
    """{key: (value, source-domain, confidence)}."""
    got: dict = {}

    def put(key, val, url, conf):
        if val and key not in got:
            dom = re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
            got[key] = (str(val).strip(), f"Web: {dom}", conf)

    for url, teks in teks_list:
        for i, rx in enumerate(SSM_RES):
            m = rx.search(teks)
            if m:
                # contextual patterns (idx 0) = TINGGI; bare formats = SEDARHANA
                put("ssm", m.group(1), url,
                    "TINGGI" if i == 0 else "SEDARHANA")
                break
        m = MSIC_RE.search(teks)
        if m:
            put("msic", m.group(1), url, "SEDARHANA")
        for rx in TAHUN_RES:
            m = rx.search(teks)
            if m and 1900 <= int(m.group(1)) <= 2026:
                put("tahun", m.group(1), url, "SEDARHANA")
                break
        m = MODAL_RE.search(teks)
        if m:
            put("modal", m.group(1), url, "SEDARHANA")
    return got


def ekstrak_ai(nama: str, tahun: int, teks_list: list[str | tuple],
               or_key: str, gem_key: str, provider: str,
               model: str, local_url: str = "", local_model: str = "",
               local_key: str = "", hf_key: str = "",
               hf_model: str = "") -> tuple[dict, str]:
    """AI factual extraction over web text. Returns (peta, nota)."""
    from search.ai_openrouter import dapatkan_kunci
    from search.ai_gemini import (dapatkan_kunci_gemini, perkaya_gemini,
                                  DEFAULT_GEMINI_MODEL)
    from search.ai_openrouter import perkaya_syarikat
    from search.ai_local import perkaya_local, ping_local
    or_k = dapatkan_kunci(or_key)
    gem_k = dapatkan_kunci_gemini(gem_key)

    def _cuba_lokal_meta():
        p, n = perkaya_local(nama, tahun, medan, konteks,
                             base_url=local_url, model=local_model,
                             api_key=local_key, anggaran=False)
        return (p, n + " [lokal]") if p else ({}, n)

    def _cuba_hf_meta():
        if not (hf_key or "").strip():
            return {}, "HF dilangkau: tiada kunci."
        from search.ai_hf import perkaya_hf
        p, n = perkaya_hf(nama, tahun, medan, konteks, hf_key, hf_model,
                          anggaran=False)
        return (p, n + " [hf]") if p else ({}, n)

    if provider in ("hf", "huggingface"):
        peta, nota = _cuba_hf_meta()
        if peta:
            return peta, nota
        if or_k:
            peta2, nota2 = perkaya_syarikat(
                nama, tahun, medan, konteks, or_k, "openai/gpt-4o-mini",
                anggaran=False)
            if peta2:
                return peta2, nota2 + " [fallback-OR]"
        return peta, nota

    if not or_k and not gem_k and provider != "local":
        # no cloud keys: local gateway (if up) or regex only
        ok, _ = ping_local(local_url)
        if ok:
            pass  # fall through to local attempt below
        else:
            return {}, "AI dilangkau: tiada kunci (regex sahaja)."
    if isinstance(teks_list, list) and teks_list and isinstance(teks_list[0], tuple):
        teks = "\n\n".join(f"SUMBER {u}:\n{t[:2500]}" for u, t in teks_list[:5])
    else:
        teks = "\n\n".join(str(t)[:2500] for t in (teks_list or [])[:5])
    if not teks.strip():
        return {}, "AI dilangkau: tiada teks web."
    konteks = {"tugas": "ekstrak-fakta-meta",
               "arahan": ("Ekstrak fakta syarikat dari teks laman web di bawah. "
                          "HANYA isi nilai yang JELAS disebut dalam teks. "
                          "Kosongkan (\"\") jika tidak ditemui — JANGAN reka "
                          "nombor SSM/MSIC/modal/tahun.") ,
               "teks_web": teks[:6000]}
    medan = [
        {"label": "[META] Nama sah syarikat (SSM)", "cell": META_FIDS["nama"],
         "sheet": "META", "semasa": nama},
        {"label": "[META] No. pendaftaran SSM", "cell": META_FIDS["ssm"],
         "sheet": "META", "semasa": ""},
        {"label": "[META] Kod MSIC 5-digit", "cell": META_FIDS["msic"],
         "sheet": "META", "semasa": ""},
        {"label": "[META] Aktiviti utama", "cell": META_FIDS["aktiviti"],
         "sheet": "META", "semasa": ""},
        {"label": "[META] Alamat berdaftar", "cell": META_FIDS["alamat"],
         "sheet": "META", "semasa": ""},
        {"label": "[META] Tahun mula/ditubuhkan", "cell": META_FIDS["tahun"],
         "sheet": "META", "semasa": ""},
        {"label": "[META] Modal berbayar RM", "cell": META_FIDS["modal"],
         "sheet": "META", "semasa": ""},
    ]
    if provider == "local":
        peta, nota = perkaya_local(nama, tahun, medan, konteks,
                                   base_url=local_url, model=local_model,
                                   api_key=local_key, anggaran=False)
        if peta:
            return peta, nota + " [lokal]"
        if or_k:
            peta2, nota2 = perkaya_syarikat(
                nama, tahun, medan, konteks, or_k, "openai/gpt-4o-mini",
                anggaran=False)
            if peta2:
                return peta2, nota2 + " [fallback-OR]"
        return peta, nota + " (gateway lokal gagal)"
    if provider == "gemini" or (provider == "auto" and not or_k and gem_k):
        from search.ai_gemini import resolve_gemini_model
        m = resolve_gemini_model(model)
        peta, nota = perkaya_gemini(nama, tahun, medan, konteks, gem_k, m,
                                    anggaran=False)
        if not peta and or_k:  # cross-provider fallback (quota/retired)
            peta2, nota2 = perkaya_syarikat(nama, tahun, medan, konteks, or_k,
                                            model if "/" in (model or "")
                                            else "openai/gpt-4o-mini",
                                            anggaran=False)
            if peta2:
                return peta2, nota2 + f" [fallback-OR]"
        if not peta:  # local gateway last resort
            peta3, nota3 = _cuba_lokal_meta()
            if peta3:
                return peta3, nota3
        if not peta:  # HF key (if configured)
            peta4, nota4 = _cuba_hf_meta()
            if peta4:
                return peta4, nota4
        return peta, nota + f" [{m}]"
    peta, nota = perkaya_syarikat(nama, tahun, medan, konteks, or_k, model,
                                  anggaran=False)
    if not peta:
        peta2, nota2 = _cuba_lokal_meta()
        if peta2:
            return peta2, nota2
    if not peta:
        peta3, nota3 = _cuba_hf_meta()
        if peta3:
            return peta3, nota3
    return peta, nota + f" [{model}]"


def isi_meta(fields: list[dict], regex_vals: dict, peta_ai: dict) -> int:
    """Fill META fields: regex first (precise), AI fills the rest."""
    import unicodedata

    def norm_sel(s):
        return re.sub(r"\s+", "", (s or "").upper())

    lookup = {}
    for k, v in (peta_ai or {}).items():
        if isinstance(k, tuple):
            lab, sel = k
            if sel:
                lookup.setdefault(norm_sel(sel), v)
    by_id = {f["id"]: f for f in fields}
    n = 0
    # 1. regex (exact patterns)
    key2fid = {"ssm": META_FIDS["ssm"], "msic": META_FIDS["msic"],
               "tahun": META_FIDS["tahun"], "modal": META_FIDS["modal"]}
    for key, (val, src, conf) in regex_vals.items():
        f = by_id.get(key2fid.get(key, ""))
        if f is not None and f.get("missing"):
            f.update(value=val, raw=str(val), missing=False,
                     source=src, confidence=conf,
                     note="Diekstrak corak regex dari web")
            n += 1
    # 2. AI factual (only still-missing)
    for fid in META_FIDS.values():
        f = by_id.get(fid)
        if f is None or not f.get("missing"):
            continue
        ai = lookup.get(norm_sel(fid))
        if not ai:
            continue
        val = ai.get("nilai", ai.get("value", ""))
        if val in (None, ""):
            continue
        conf = str(ai.get("keyakinan", ai.get("confidence", "SEDARHANA"))).upper()
        if conf not in ("TINGGI", "SEDARHANA", "RENDAH"):
            conf = "SEDARHANA"
        f.update(value=val, raw=str(val), missing=False,
                 source=str(ai.get("sumber", ai.get("source", "Web/AI"))),
                 confidence=conf,
                 note=str(ai.get("nota", ai.get("note", "")) or
                          "Diekstrak AI dari web")[:220])
        n += 1
    return n


def tangkap(nama: str, tahun: int, dossier: dict, fields: list[dict],
            or_key: str = "", gem_key: str = "", provider: str = "auto",
            model: str = "", local_url: str = "", local_model: str = "",
            local_key: str = "", hf_key: str = "",
            hf_model: str = "") -> tuple[int, str]:
    """Full META web-catch. Returns (filled_count, note)."""
    teks = kumpul_teks(dossier)
    rx = ekstrak_regex(teks)
    peta, nota_ai = ekstrak_ai(nama, tahun, teks, or_key, gem_key,
                               provider, model, local_url, local_model,
                               local_key, hf_key, hf_model)
    n = isi_meta(fields, rx, peta)
    nota = (f"Web-catch: {len(teks)} sumber dibaca, {len(rx)} regex, "
            f"{nota_ai}".rstrip() + ".")
    return n, nota
