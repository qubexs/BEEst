"""KP205 dossier (free web search) + AI estimator wrapper.

Dossier: reuses search.syarikat (DDG -> Bing free cascade, no key).
Estimator: reuses search.ai_openrouter / ai_gemini with KP205-specific prompt
context (accounting consistency rules). Fail-soft without keys.
"""
from __future__ import annotations
import re

from search.syarikat import cari_syarikat
from search.ai_openrouter import (
    DEFAULT_MODEL, dapatkan_kunci, perkaya_syarikat,
)
from search.ai_gemini import (
    DEFAULT_GEMINI_MODEL, dapatkan_kunci_gemini, perkaya_gemini,
)


def _it_hint(nama: str, aktiviti: str) -> str:
    t = f"{nama} {aktiviti}".lower()
    if any(k in t for k in ("teknologi maklumat", "information tech", "software",
                            "syst", "digital", "it ", "kenanga", "ventures")):
        return ("Sektor: Perkhidmatan teknologi maklumat (MSIC 6201/6202/6311 lazim). "
                "Anggaran ikut nisbah DOSM perkhidmatan IT PKS: margin 10-20%, "
                "gaji 25-35% hasil, sewa 5-12% hasil.")
    if any(k in t for k in ("pembinaan", "bina", "construction", "kontraktor",
                            "pemaju", "konkrit", "cidb", "infrastruktur")):
        return ("Sektor: Pembinaan (MSIC 4100/4210/4220/4290/4311/4321 lazim). "
                "Anggaran ikut nisbah DOSM pembinaan PKS: bahan binaan 20-60% "
                "hasil, subkontrak 9.10 dan sewa jentera 9.28(b) ketara, "
                "gaji 10-40% hasil, susut jentera berat 9.29 tinggi.")
    return ""


def build_context(nama: str, tahun: int, meta: dict, dossier: dict) -> dict:
    ctx = {
        "kp205": True,
        "nama": nama,
        "tahun": tahun,
        "meta": {k: v for k, v in meta.items() if k != "fail"},
        "dossier_status": dossier.get("status", "?"),
        "dossier_sebab": dossier.get("sebab", ""),
        "dossier_ssm": dossier.get("no_ssm", []),
        "sektor_hint": _it_hint(nama, meta.get("aktiviti", "")),
        "peraturan_perakaunan": (
            "9.39 Jumlah perbelanjaan ~= sum komponen 9.x; "
            "Untung Semasa ~= 8.15 Jumlah Besar - 9.44 Jumlah Besar; "
            "8.13 Jumlah pendapatan MESTI SAMA dengan 8.15 JUMLAH BESAR "
            "(satu angka hasil sahaja — JANGAN cipta dua angka berbeza); "
            "9.39 MESTI SAMA dengan 9.44; "
            "Kategori pekerja L (siri PEKERJA::L::...) MESTI tambah tepat "
            "kepada Pekerja Lelaki (L); sama untuk P — JANGAN lebih/kurang; "
            "L+P MESTI = Jumlah; Warga+BWN MESTI = Jumlah; "
            "Shif1+2+3 MESTI = Jumlah; tahap PENDIDIKAN MESTI = Jumlah; "
            "Jawatan dengan 0 pekerja MESTI dikosongkan (gaji kosong, "
            "BUKAN RM0); "
            "Shif1+Shif2+Shif3 MESTI SAMA dengan Jumlah pekerja; "
            "9.36(a) MESTI SAMA dengan bil gaji (orang x kadar bulanan x 12); "
            "JAM OT dan Upah OT sifar serentak; "
            "Jumlah Jam = Hari beroperasi x Jam/Shift; "
            "BWN>0 MESTI ada 9.36(i) Levi; BWN=0 MESTI Levi 0/kosong; "
            "KWSP ~= 13% daripada 9.36(a) Gaji; PERKESO ~= 1.5-2% gaji; "
            "Stok Akhir munasabah vs Awal (+-30% kecuali bahan); "
            "Kapasiti 0-100%."
        ),
    }
    return ctx


def get_dossier(nama: str) -> dict:
    # Moved import from top level to here to avoid circular dependency issues if needed elsewhere
    from search.syarikat import cari_syarikat
    return cari_syarikat(nama or "(tidak dinyatakan)")


def estimate_missing(nama: str, tahun: int, missing: list[dict], konteks: dict,
                     or_key: str, gem_key: str, provider: str, model: str,
                     batch: int = 60, stop=None,
                     anggaran: bool = True, local_url="", local_model="",
                     local_key="", hf_key="", hf_model="") -> tuple[dict, str, str]:
    """Estimate ALL missing fields, batched. Returns (peta, nota, used_model).

    anggaran=True: force a grounded estimate for every field.
    anggaran=False (factual): AI fills only what it knows, blanks the rest.
    """
    from activity import emit
    medan = [{"label": f"[{m['section']}] {m['label']}", "cell": m["id"],
              "sheet": m["section"], "semasa": m.get("value", "")}
             for m in missing]
    peta_all: dict = {}
    nota_all: list[str] = []
    used = model
    total = (len(medan) + batch - 1) // max(batch, 1)
    for i in range(0, len(medan), batch):
        if stop is not None and getattr(stop, "is_set", lambda: False)():
            from activity import Stopped
            raise Stopped()
        chunk = medan[i:i + batch]
        emit("AI", f"KP205 kelompok {i // batch + 1}/{total}: {len(chunk)} medan ...")
        peta, nota, used = _call_once(nama, tahun, chunk, konteks,
                                       or_key, gem_key, provider, model,
                                       anggaran=anggaran, local_url=local_url,
                                       local_model=local_model,
                                       local_key=local_key, hf_key=hf_key,
                                       hf_model=hf_model)
        nota_all.append(nota)
        peta_all.update(peta)
        if not peta and ("dilangkau" in nota or "ralat" in nota.lower()
                         or "error" in nota.lower()):
            break
    return peta_all, " | ".join(nota_all), used

def estimate_sections(nama: str, tahun: int, fields: list[dict],
                      konteks: dict, or_key: str, gem_key: str,
                      provider: str, model: str,
                      unticked: set | None = None,
                      order: list | None = None,
                      progress=None, stop=None, local_url="",
                      local_model="", local_key="",
                      hf_key="", hf_model="") -> tuple[int, str, str]:
    """AI fill section-by-section, META first (factual), then estimates.

    META runs in factual mode (AI fills only what it knows — no invented
    SSM/identity numbers). All other sections run in estimate mode.
    progress(sec, idx, total, count, done: bool) callback after each
    section; stop = threading.Event (raises Stopped).
    Returns (total_filled, nota, used_model).
    """
    from activity import emit, Stopped
    order = order or ["META", "PENDAPATAN", "PERBELANJAAN", "PEKERJA", "GAJI",
                      "ASET", "STOK", "BAHAN", "NEGERI", "SHIFT",
                      "PENDIDIKAN"]
    unticked = unticked or set()
    from kp205.template_fields import MANUAL_ONLY
    n_total, nota_parts, used = 0, [], model
    for si, sec in enumerate(order, 1):
        if stop is not None and getattr(stop, "is_set", lambda: False)():
            raise Stopped()
        factual = (sec == "META")
        if factual:
            sec_missing = [
                f for f in fields
                if f.get("missing") and f.get("section") == sec
                and f["id"] not in unticked]
        else:
            sec_missing = [
                f for f in fields
                if f.get("missing") and f.get("section") == sec
                and f["id"] not in MANUAL_ONLY and f["id"] not in unticked]
        if not sec_missing:
            continue
        if progress:
            progress(sec, si, len(order), len(sec_missing), False)
        konteks["seksyen_aktif"] = (
            f"Fokus SEKSYEN {sec} sahaja; medan lain sudah "
            f"lengkap/jangkar — JANGAN ubah.")
        peta, nota_sec, used = estimate_missing(
            nama, tahun, sec_missing, konteks, or_key, gem_key,
            provider, model, batch=60, stop=stop, anggaran=not factual,
            local_url=local_url, local_model=local_model, local_key=local_key,
            hf_key=hf_key, hf_model=hf_model)
        n_sec = apply_estimates(fields, peta, used, anggaran=not factual)
        n_total += n_sec
        nota_parts.append(f"{sec}:{n_sec}")
        emit("OK", f"Seksyen {sec} siap: {n_sec} diisi.")
        if progress:
            progress(sec, si, len(order), n_sec, True)
        if not peta and ("dilangkau" in nota_sec
                         or "ralat" in nota_sec.lower()
                         or "error" in nota_sec.lower()):
            break  # no key / fatal — stop burning further calls
    nota = f"{n_total} (" + ", ".join(nota_parts) + ")" if nota_parts \
        else "0 (tiada medan)"
    return n_total, nota, used


def _cuba_lokal(nama, tahun, chunk, konteks, anggaran,
                local_url="", local_model="", local_key=""):
    """Last-resort local gateway attempt. Returns (peta, nota, model|\"\")."""
    from search.ai_local import perkaya_local, local_model as _lm
    peta, nota = perkaya_local(nama, tahun, chunk, konteks,
                               base_url=local_url, model=local_model,
                               api_key=local_key, anggaran=anggaran)
    if peta:
        m = _lm(local_model)
        if nota.startswith("OK:Lokal "):
            try:
                m = nota.split("OK:Lokal ", 1)[1].split(" ", 1)[0].rstrip("()")
            except Exception:
                pass
        return peta, nota, m
    return {}, nota, ""


def _cuba_hf(nama, tahun, chunk, konteks, anggaran,
             hf_key="", hf_model=""):
    """HF router attempt (needs valid key). Returns (peta, nota, model|\"\")."""
    from search.ai_hf import perkaya_hf, hf_model as _hm
    if not (hf_key or "").strip():
        return {}, "HF dilangkau: tiada kunci.", ""
    peta, nota = perkaya_hf(nama, tahun, chunk, konteks, hf_key, hf_model,
                            anggaran=anggaran)
    if peta:
        m = _hm(hf_model)
        if nota.startswith("OK:HF "):
            try:
                m = nota.split("OK:HF ", 1)[1].split(" ", 1)[0].rstrip("()")
            except Exception:
                pass
        return peta, nota, m
    return {}, nota, ""


def _call_once(nama, tahun, chunk, konteks, or_key, gem_key, provider, model,
               anggaran: bool = True, local_url="", local_model="",
               local_key="", hf_key="", hf_model=""):
    or_k = dapatkan_kunci(or_key)
    gem_k = dapatkan_kunci_gemini(gem_key)
    from search.ai_gemini import resolve_gemini_model
    if provider in ("hf", "huggingface"):
        peta, nota, m = _cuba_hf(nama, tahun, chunk, konteks, anggaran,
                                 hf_key, hf_model)
        if peta:
            return peta, nota, m
        # HF failed (often auth) -> fall through to cloud/local if available
        if or_k:
            peta2, nota2 = perkaya_syarikat(
                nama, tahun, chunk, konteks, or_k,
                model if "/" in (model or "") else DEFAULT_MODEL,
                anggaran=anggaran)
            if peta2:
                return peta2, nota2, model
        pl, nl, ml = _cuba_lokal(nama, tahun, chunk, konteks, anggaran,
                                 local_url, local_model, local_key)
        if pl:
            return pl, nl, ml
        return peta, nota, m
    if provider == "local":
        peta, nota, m = _cuba_lokal(nama, tahun, chunk, konteks, anggaran,
                                    local_url, local_model, local_key)
        if peta:
            return peta, nota, m
        # local gateway down -> fall through to cloud keys if available
        if or_k:
            peta2, nota2 = perkaya_syarikat(
                nama, tahun, chunk, konteks, or_k,
                model if "/" in (model or "") else DEFAULT_MODEL,
                anggaran=anggaran)
            if peta2:
                return peta2, nota2, model
        if gem_k:
            from activity import emit
            emit("WARN", "Lokal gagal — cuba Gemini ...")
            m2 = resolve_gemini_model("")
            peta2, nota2 = perkaya_gemini(nama, tahun, chunk, konteks,
                                          gem_k, m2, anggaran=anggaran)
            if peta2:
                return peta2, nota2, m2
        return peta, nota + " (tiada kunci cloud untuk fallback)", m
    if provider == "gemini" or (provider == "auto" and not or_k and gem_k):
        m = resolve_gemini_model(model) if "/" not in (model or "") \
            else resolve_gemini_model("")
        peta, nota = perkaya_gemini(nama, tahun, chunk, konteks, gem_k, m,
                                    anggaran=anggaran)
        # perkaya_gemini may have fallen back to another candidate model;
        # report the ACTUAL model from the nota so tags/sources are accurate.
        if peta and nota.startswith("OK:Gemini "):
            try:
                m = nota.split("OK:Gemini ", 1)[1].split(" ", 1)[0].rstrip("()")
            except Exception:
                pass
        # Gemini failed but OpenRouter key exists -> cross-provider fallback
        # so AI still "fulfills" instead of dropping to offline heuristics.
        if not peta and or_k and ("ralat" in nota.lower()
                                  or "error" in nota.lower()
                                  or "quota" in nota.lower()
                                  or "not_found" in nota.lower()
                                  or "404" in nota or "429" in nota
                                  or "503" in nota):
            from activity import emit
            emit("WARN", f"Gemini gagal ({nota[:120]}) — cuba OpenRouter ...")
            peta2, nota2 = perkaya_syarikat(
                nama, tahun, chunk, konteks, or_k,
                model if "/" in (model or "") else DEFAULT_MODEL,
                anggaran=anggaran)
            if peta2:
                return peta2, nota2, model
        # cloud failed -> local gateway, then HF (fail-soft if down/nokey)
        pl, nl, ml = _cuba_lokal(nama, tahun, chunk, konteks, anggaran,
                                 local_url, local_model, local_key)
        if pl:
            return pl, nl, ml
        ph, nh, mh = _cuba_hf(nama, tahun, chunk, konteks, anggaran,
                              hf_key, hf_model)
        if ph:
            return ph, nh, mh
        return peta, nota, m
    peta, nota = perkaya_syarikat(nama, tahun, chunk, konteks, or_k, model,
                                  anggaran=anggaran)
    if not peta and gem_k and ("ralat" in nota.lower()
                               or "error" in nota.lower()):
        from activity import emit
        emit("WARN", f"OpenRouter gagal ({nota[:120]}) — cuba Gemini ...")
        m = resolve_gemini_model("")
        peta2, nota2 = perkaya_gemini(nama, tahun, chunk, konteks, gem_k, m,
                                      anggaran=anggaran)
        if peta2:
            if nota2.startswith("OK:Gemini "):
                try:
                    m = nota2.split("OK:Gemini ", 1)[1].split(" ", 1)[0].rstrip("()")
                except Exception:
                    pass
            return peta2, nota2, m
    if not peta:
        pl, nl, ml = _cuba_lokal(nama, tahun, chunk, konteks, anggaran,
                                 local_url, local_model, local_key)
        if pl:
            return pl, nl, ml
        ph, nh, mh = _cuba_hf(nama, tahun, chunk, konteks, anggaran,
                              hf_key, hf_model)
        if ph:
            return ph, nh, mh
    return peta, nota, model

def apply_estimates(fields: list[dict], peta: dict, used_model: str,
                    anggaran: bool = True) -> int:
    """Merge AI map {(label,sel): {...}} into fields by id (=sel). Returns count.

    anggaran=False (factual META pass): source/confidence come from the AI
    instead of the forced ANGGARAN AI/RENDAH labels.
    """
    import unicodedata
    import re

    def norm_sel(s):
        return re.sub(r"\s+", "", (s or "").upper())

    lookup = {}
    for k, v in (peta or {}).items():
        if isinstance(k, tuple):
            lab, sel = k
            if sel:
                lookup.setdefault(norm_sel(sel), v)
        elif isinstance(k, str):
            lookup.setdefault(norm_sel(k), v)
    n = 0
    tag = f"ANGGARAN AI:{used_model.split('/')[-1]}"
    for f in fields:
        if not f.get("missing"):
            continue
        ai = lookup.get(norm_sel(f["id"]))
        if ai is None:
            # fallback: match by label substring
            continue
        nilai = ai.get("nilai", ai.get("value", ""))
        if nilai in (None, ""):
            continue

        f["raw"] = str(nilai)
        f["missing"] = False
        if anggaran:
            f["source"] = "ANGGARAN AI"
        else:
            f["source"] = str(ai.get("sumber", ai.get("source", "AI"))) or "AI"
        conf = str(ai.get("keyakinan", ai.get("confidence", "RENDAH"))).upper()
        if conf not in ("TINGGI", "SEDARHANA", "RENDAH"):
            conf = "SEDARHANA" if "SEDER" in conf else "RENDAH"
        f["confidence"] = conf
        f["estimated_range"] = ""

        if isinstance(nilai, str) and re.match(r"^\d[\d,]*\s*-\s*\d[\d,]*$", nilai):
            # Range like "15000-16000": keep range, use midpoint as value
            f["estimated_range"] = nilai
            try:
                low, high = [float(x.replace(",", "")) for x in nilai.split("-")]
                f["value"] = int(round((low + high) / 2))
            except ValueError:
                f["value"] = nilai
        else:
            f["value"] = nilai

        nota = str(ai.get("nota", ai.get("note", "")) or
               (f"Anggaran {tag}" if anggaran else f"Fakta {tag}"))[:220]
        f["note"] = nota
        n += 1

    return n

def _agih(pekerja: int, pemberat: dict[str, float]) -> dict[str, int]:
    """Largest-remainder split of headcount by weights (deterministic)."""
    keys = list(pemberat.keys())
    wsum = sum(pemberat.values()) or 1
    exact = [pekerja * pemberat[k] / wsum for k in keys]
    base = [int(x) for x in exact]
    baki = pekerja - sum(base)
    urut = sorted(range(len(keys)), key=lambda i: exact[i] - base[i],
                  reverse=True)
    for i in urut[:max(0, baki)]:
        base[i] += 1
    return dict(zip(keys, base))


KAT_W = {"Pemilik": 2, "Keluarga": 1, "Pengurus": 2, "Profesional (Pro)": 1.5,
         "Penyelidik": 0.5, "Juruteknik": 1.5, "Kerani": 1.5, "Jualan": 2.5,
         "Mahir berkaitan": 1, "Operator": 3, "Asas": 1}
DIDIK_W = {"Pasca (L/P)": 0.5, "Deg A (L/P)": 1.5, "Deg T (L/P)": 1,
           "Dip A (L/P)": 1.5, "Dip TVet (L/P)": 1, "STPM (L/P)": 1.5,
           "Cert A (L/P)": 0.5, "TVET (L/P)": 1, "SPM (L/P)": 3,
           "Under SPM (L/P)": 1}


def offline_fallback_estimates(fields: list[dict],
                               only: set | None = None) -> int:
    """No-key heuristic estimates so TXT is never empty. Returns count filled.

    If `only` is given, unticked ids are skipped (GUI refill control).
    """
    import random
    n = 0
    # gaji anchor if known
    gaji = next((f for f in fields if "9.36" in f["id"] or "Gaji" in f["label"]
                 and f.get("value") not in (None, "")), None)
    try:
        g = float(str(gaji["value"]).replace(",", "")) if gaji else 247000.0
    except Exception:
        g = 247000.0
    by_id = {f["id"]: f for f in fields}

    def _isi(f, v, note):
        f.update(value=v, raw=str(v), missing=False,
                 source="ANGGARAN AI (offline)", confidence="RENDAH", note=note)
        return 1

    # --- headcount anchors (L/P/Warga/BWN/Total) if known ---
    def head(fid):
        f = by_id.get(fid)
        try:
            return int(float(str(f["value"]).replace(",", ""))) \
                if f is not None and f.get("value") not in (None, "") else 0
        except (ValueError, TypeError):
            return 0

    s = "PEKERJA::"
    tot_l = head(s + "Pekerja Lelaki (L)")
    tot_p = head(s + "Pekerja Perempuan (P)")
    tot = head(s + "Pekerja — Jumlah besar (Total)") or (tot_l + tot_p) or 2
    if not tot_l and not tot_p:
        tot_l, tot_p = (tot + 1) // 2, tot // 2  # split when unknown
    tot_bwn = head(s + "Pekerja — Bukan Warganegara (BWN)")
    # distribute L and P separately over job categories (varied, sums exact)
    agih_l = _agih(tot_l, KAT_W)
    agih_p = _agih(tot_p, KAT_W)
    agih_d = _agih(tot, DIDIK_W)
    for f in fields:
        if not f.get("missing"):
            continue
        if only is not None and f["id"] not in only:
            continue  # unticked in GUI: skip refill
        lab = f["label"].lower()
        if "kwsp" in lab or "9.36(d)(i" in f["id"]:
            f.update(value=round(g * 0.13), raw=str(round(g * 0.13)),
                     missing=False, source="ANGGARAN (13% gaji)",
                     confidence="RENDAH", note="Heuristik: KWSP 13% daripada gaji")
            n += 1
        elif "perkeso" in lab or "9.36(d)(iii" in f["id"]:
            f.update(value=round(g * 0.0175), raw=str(round(g * 0.0175)),
                     missing=False, source="ANGGARAN (1.75% gaji)",
                     confidence="RENDAH", note="Heuristik: PERKESO ~1.75% gaji")
            n += 1
        elif f["id"].startswith(s + "L::"):
            kat = f["label"].split("—")[-1].strip()
            v = agih_l.get(kat, 0)
            n += _isi(f, v, f"Agihan {tot_l} lelaki ikut profil PKS")
        elif f["id"].startswith(s + "P::"):
            kat = f["label"].split("—")[-1].strip()
            v = agih_p.get(kat, 0)
            n += _isi(f, v, f"Agihan {tot_p} perempuan ikut profil PKS")
        elif f["section"] == "PENDIDIKAN":
            kat = f["label"].replace("Pendidikan ", "").strip()
            v = agih_d.get(kat, 0)
            n += _isi(f, v, f"Agihan {tot} pekerja ikut tahap lazim")
        elif f["id"] == s + "Pekerja — Jumlah besar (Total)":
            n += _isi(f, tot, "Jumlah pekerja (jangkar/agihan)")
        elif f["id"] == s + "Pekerja Lelaki (L)":
            n += _isi(f, tot_l, "Agihan jantina")
        elif f["id"] == s + "Pekerja Perempuan (P)":
            n += _isi(f, tot_p, "Agihan jantina")
        elif f["id"] == s + "Pekerja — Warganegara (Warga)":
            n += _isi(f, max(0, tot - tot_bwn), "Warga = jumlah tolak BWN")
        elif f["id"] == s + "Pekerja — Bukan Warganegara (BWN)":
            n += _isi(f, 0, "Andaian tiada pekerja asing")
        elif f["id"] == s + "Pekerja — Sambilan":
            n += _isi(f, 0, "Andaian tiada pekerja sambilan")
    # shift hours derivation: Jumlah Jam = Hari x Jam/Shift (per pekerja)
    vals = {f["id"]: f.get("value") for f in fields}
    try:
        hari = float(str(vals.get("SHIFT::Hari beroperasi", "") or 0))
        jam = float(str(vals.get("SHIFT::Jam/Shift", "") or 0))
    except Exception:
        hari, jam = 0, 0
    for f in fields:
        if not f.get("missing"):
            continue
        if only is not None and f["id"] not in only:
            continue  # unticked in GUI: skip refill
        if f["id"] == "SHIFT::Jumlah Jam" and hari and jam:
            v = int(hari * jam)
            f.update(value=v, raw=str(v), missing=False,
                     source="ANGGARAN (Hari×Jam)",
                     confidence="RENDAH", note=f"Terbitan: {hari:g}x{jam:g} jam/tahun")
            n += 1
        elif f["id"] in ("SHIFT::JAM OT", "SHIFT::Upah OT"):
            f.update(value=0, raw="0", missing=False,
                     source="ANGGARAN (offline)",
                     confidence="RENDAH", note="Andaian tiada OT direkodkan")
            n += 1
    return n
