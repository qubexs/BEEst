"""Dosier syarikat: wujud atau tutup? Kumpul sebarang sumber internet, tulis fail TXT.

Aliran: cari nama merata sumber awam (enjin carian + direktori SSM terbitan) ->
tentukan status (WUJUD / TUTUP / TIDAK PASTI / TIADA REKOD) -> kumpul data ->
tambah anggaran berasas (dilabel) -> tulis TXT. Semua fail-soft.
"""
from __future__ import annotations
import re
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

import requests

from activity import emit

TIMEOUT = 20
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"\b(sdn|bhd|enterprise|ent|trading|services|marketing|sdn\.|bhd\.)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _cari_ddg_html(nama: str, n: int = 12) -> list[dict]:
    """DuckDuckGo HTML (tiada kunci)."""
    try:
        r = requests.get("https://html.duckduckgo.com/html/",
                         params={"q": f'"{nama}" Malaysia syarikat SSM'},
                         headers=BROWSER, timeout=TIMEOUT)
        r.raise_for_status()
        html = r.text
        hasil = []
        for m in re.finditer(
                r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?(?:class="result__snippet"[^>]*>(.*?)</a>|class="result__snippet"[^>]*>(.*?)</div>)',
                html, re.S):
            url, tajuk = m.group(1), re.sub(r"<.*?>", "", m.group(2)).strip()
            petikan = re.sub(r"<.*?>", "", (m.group(3) or m.group(4) or "")).strip()
            if url.startswith("//"):
                url = "https:" + url
            if tajuk and url.startswith("http"):
                hasil.append({"tajuk": tajuk, "url": url, "petikan": petikan,
                              "sumber": "DuckDuckGo"})
            if len(hasil) >= n:
                break
        return hasil
    except Exception as e:
        emit("WARN", f"DDG-html gagal: {e}")
        return []


def _cari_bing(nama: str, n: int = 12) -> list[dict]:
    """Bing HTML (tiada kunci). URL pengalih ck/ dibiarkan — diselesai bila perlu."""
    try:
        r = requests.get("https://www.bing.com/search",
                         params={"q": f'"{nama}" Malaysia syarikat', "count": 15},
                         headers={**BROWSER, "Accept-Language": "en-MY,en;q=0.9"},
                         timeout=TIMEOUT)
        r.raise_for_status()
        hasil = []
        for b in re.findall(r'<li class="b_algo".*?</li>', r.text, re.S):
            m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
            p = re.search(r'<p[^>]*>(.*?)</p>', b, re.S)
            if not m:
                continue
            tajuk = re.sub(r"<.*?>", "", m.group(2)).strip()
            url = m.group(1)
            petikan = re.sub(r"<.*?>", "", p.group(1)).strip()[:300] if p else ""
            if tajuk and url.startswith("http"):
                hasil.append({"tajuk": tajuk, "url": url, "petikan": petikan,
                              "sumber": "Bing"})
            if len(hasil) >= n:
                break
        return hasil
    except Exception as e:
        emit("WARN", f"Bing gagal: {e}")
        return []


def _selesai_url(url: str) -> str:
    """Selesaikan URL pengalih (bing ck/) kepada destinasi sebenar."""
    if "bing.com/ck/" not in url:
        return url
    try:
        r = requests.head(url, headers=BROWSER, timeout=TIMEOUT, allow_redirects=True)
        if r.url and "bing.com" not in r.url:
            return r.url
        r = requests.get(url, headers=BROWSER, timeout=TIMEOUT, allow_redirects=True)
        if r.url and "bing.com" not in r.url:
            return r.url
    except Exception:
        pass
    return url


def _cari_web(nama: str, n: int = 12) -> list[dict]:
    """Lata enjin: DDG -> Bing. Tapis relevan (>0.25) supaya sampah bot tidak dikira."""
    emit("NET", f"Cari web: {nama!r} ...")
    gabung: list[dict] = []
    lihat = set()
    for fn in (_cari_ddg_html, _cari_bing):
        for h in fn(nama, n):
            if h["url"] not in lihat:
                lihat.add(h["url"])
                gabung.append(h)
        if len(gabung) >= n:
            break
    relevan = [h for h in gabung
               if max(_skor_padanan(nama, h["tajuk"]),
                       _skor_padanan(nama, h["petikan"])) >= 0.25]
    emit("OK" if relevan else "WARN",
         f"Carian web: {len(gabung)} mentah, {len(relevan)} relevan untuk {nama!r}.")
    return relevan


def _skor_padanan(nama: str, teks: str) -> float:
    """0..1: berapa banyak token nama penuh muncul dalam teks."""
    target = [t for t in _norm(nama).split() if len(t) > 2]
    if not target:
        return 0.0
    ada = _norm(teks)
    kena = sum(1 for t in target if t in ada)
    return kena / len(target)


def _semak_direktori(hasil: list[dict]) -> list[dict]:
    """Cuba buka hasil direktori SSM-terbitan (creditscan/ctos/mydata) untuk no. daftar."""
    bukti = []
    for h in hasil:
        url = _selesai_url(h["url"])
        if not any(d in url for d in ("creditscan.com.my", "ctoscredit.com", "mydata-ssm.com")):
            continue
        try:
            emit("NET", f"Direktori GET {url[:80]} ...")
            r = requests.get(url, headers=BROWSER, timeout=TIMEOUT)
            if r.status_code != 200:
                continue
            teks = re.sub(r"<.*?>", " ", r.text)
            teks = re.sub(r"\s+", " ", teks)
            no_daftar = re.findall(
                r"(?:Registration No|No\. Pendaftaran|Company No)[\s:]*([A-Z0-9][A-Z0-9\-/]{4,20})",
                teks, re.I)
            status = re.findall(r"Status[\s:]*([A-Z ]{3,20})", teks)
            bukti.append({"url": url, "no_daftar": sorted(set(no_daftar))[:3],
                          "status_teks": sorted(set(s.strip() for s in status))[:3],
                          "petikan": teks[:600]})
            emit("OK", f"Direktori dibaca: {url.split('/')[2]}.")
        except Exception as e:
            emit("WARN", f"Direktori gagal: {e}")
    return bukti


def _anggaran_sektor(nama: str) -> dict:
    """Anggaran berasas dari kata kunci nama (dilabel, bukan fakta)."""
    mentah = re.sub(r"[^a-z0-9]+", " ", (nama or "").lower()).strip()
    n = mentah  # JANGAN buang kata kunci sektor di sini
    sektor = "Perkhidmatan am / tidak dikenal pasti"
    asas = "nama tanpa kata kunci sektor jelas"
    if any(k in n for k in ("market", "advertis", "brand", "digital", "media", "promo")):
        sektor, asas = "Pemasaran / pengiklanan (agensi atau MLM barangan pengguna)", \
            "kata kunci 'marketing' pada nama"
    elif any(k in n for k in ("tech", "system", "software", "it ", "digital")):
        sektor, asas = "Teknologi maklumat / perkhidmatan digital", "kata kunci teknologi pada nama"
    elif any(k in n for k in ("food", "makan", "resto", "cafe", "katering")):
        sektor, asas = "Makanan & minuman", "kata kunci makanan pada nama"
    elif any(k in n for k in ("construct", "bina", "contractor", "kontrak")):
        sektor, asas = "Pembinaan / kontraktor", "kata kunci binaan pada nama"
    return {
        "sektor": (sektor, asas),
        "bentuk": ("Enterprise (ROB) milik tunggal/perkongsian — andaian lazim PKS mikro "
                   "tanpa 'SDN. BHD.' pada nama",
                   "tiada 'SDN. BHD.' pada nama diberi"),
        "pekerja": ("1–10 orang (PKS mikro)", "profil lazim perusahaan pemasaran kecil"),
        "hasil_tahunan": ("RM200 ribu – RM2 juta (PKS mikro/kecil)", "julat lazim sektor perkhidmatan kecil"),
    }


def cari_syarikat(nama: str) -> dict:
    """Cari syarikat merata sumber. Pulangan dosier dict (sedia ditulis TXT)."""
    nama = (nama or "").strip()
    emit("INFO", f"Dosier: semak kewujudan {nama!r} ...")
    hasil = _cari_web(nama) if nama else []
    skor_terbaik, terbaik = 0.0, None
    for h in hasil:
        s = max(_skor_padanan(nama, h["tajuk"]), _skor_padanan(nama, h["petikan"]))
        if s > skor_terbaik:
            skor_terbaik, terbaik = s, h
    direktori = _semak_direktori([h for h in hasil if _skor_padanan(nama, h["tajuk"]) >= 0.5])
    teks_semua = " ".join((h["tajuk"] + " " + h["petikan"]) for h in hasil).lower()
    isyarat_tutup = any(k in teks_semua for k in
                        ("struck off", "dissolved", "dibubarkan", "wound up", "digulung",
                         "ceased", "telah ditutup", "bankrupt", "muflis"))
    no_ssm = []
    for d in direktori:
        no_ssm.extend(d["no_daftar"])
    url_terbaik = _selesai_url(terbaik["url"]) if terbaik else ""
    if no_ssm or (terbaik and skor_terbaik >= 0.8 and
                  any(d in url_terbaik for d in ("creditscan", "ctoscredit", "mydata-ssm", "ssm"))):
        status = "BERKEMUNGKINAN WUJUD"
        sebab = (f"rekod SSM-terbitan ditemui ({', '.join(no_ssm) if no_ssm else 'rujukan direktori'})"
                 if no_ssm or terbaik else "padanan nama kukuh dalam direktori")
    elif isyarat_tutup and skor_terbaik >= 0.5:
        status = "BERKEMUNGKINAN TUTUP"
        sebab = "teks sumber menyebut dibubarkan/digulung/ditutup"
    elif skor_terbaik >= 0.5:
        status = "TIDAK PASTI"
        sebab = f"hanya rujukan separa (skor {skor_terbaik:.0%}), tiada rekod SSM-terbitan"
    elif hasil:
        status = "TIADA REKOD TEPAT"
        sebab = f"{len(hasil)} hasil umum, tiada padanan nama kukuh (terbaik {skor_terbaik:.0%})"
    else:
        status = "TIADA REKOD AWAM"
        sebab = "enjin carian tidak mengembalikan apa-apa (mungkin luar talian/disekat)"
    emit("OK" if "WUJUD" in status else "WARN", f"Dosier {nama!r}: {status} — {sebab}.")
    return {"nama": nama, "tarikh": str(date.today()), "status": status, "sebab": sebab,
            "skor": round(skor_terbaik, 2), "hasil": hasil, "direktori": direktori,
            "no_ssm": sorted(set(no_ssm)), "anggaran": _anggaran_sektor(nama)}


def tulis_dosier(d: dict, path: str | Path) -> str:
    """Tulis dosier ke TXT (UTF-8). Pulangan path str."""
    L = [f"=== DOSIER SYARIKAT: {d['nama']} ===",
         f"Tarikh semakan: {d['tarikh']}",
         "",
         f"STATUS: {d['status']}",
         f"Sebab: {d['sebab']}",
         f"No. SSM ditemui: {', '.join(d['no_ssm']) if d['no_ssm'] else '(tiada)'}",
         "",
         f"--- Bukti internet ({len(d['hasil'])}) ---"]
    if not d["hasil"]:
        L.append("(tiada hasil — semak sambungan atau nama ejaan)")
    for i, h in enumerate(d["hasil"], 1):
        L.append(f"[{i}] {h['tajuk']}")
        L.append(f"    {h['url']}")
        if h["petikan"]:
            L.append(f"    » {h['petikan'][:300]}")
    L.append("")
    L.append(f"--- Rekod direktori SSM-terbitan ({len(d['direktori'])}) ---")
    if not d["direktori"]:
        L.append("(tiada — pengesahan rasmi perlu SSM e-Info berbayar: "
                 "ssm-einfo.my / mydata-ssm.com.my / ssmsearch.com)")
    for x in d["direktori"]:
        L.append(f"- {x['url']}")
        L.append(f"  no: {', '.join(x['no_daftar']) or '(tiada)'} | status: "
                 f"{', '.join(x['status_teks']) or '(tiada)'}")
    L.append("")
    L.append("--- ANGGARAN berasas (BUKAN fakta — sahkan sebelum guna) ---")
    for k, (nilai, asas) in d["anggaran"].items():
        L.append(f"- {k}: {nilai}")
        L.append(f"  asas: {asas}")
    L.append("")
    L.append("Langkah seterusnya: 1) semak ejaan/nama penuh SSM, 2) beli profil SSM e-Info "
             "(sahkan status EXISTING/DISSOLVED), 3) guna data sah ini untuk isi borang.")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    emit("OK", f"Dosier ditulis: {p} ({len(d['hasil'])} bukti, status {d['status']}).")
    return str(p)


def slug(nama: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", (nama or "syarikat")).strip("_").upper()
    return s[:60] or "SYARIKAT"
