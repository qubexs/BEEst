"""Larian terus tanpa GUI: soal dari INPUT -> online + anggaran AI -> tulis OUTPUT.

Contoh:
  python auto_fill.py --in "C:/Users/tokki/Downloads/205.xlsx" --out "C:/Users/tokki/Downloads/x205.xlsx"

Pilihan: --cui, --company, --year, --model (default: model PERCUMA terbaik live),
         --batch (medan per panggilan AI), --with-suggest (selain anggaran, cuba fakta AI dulu)
Kunci/model dibaca dari config/settings.json (atau env OPENROUTER_API_KEY / GEMINI_API_KEY).
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from filler.template import inspect_template
from filler.writer import fill_template
from search.aggregator import aggregate
from search.ai_openrouter import DEFAULT_MODEL, dapatkan_kunci, perkaya_syarikat, gabung_ai_ke_baris
from search.ai_gemini import dapatkan_kunci_gemini, perkaya_gemini
from search.models import cari_model_terbaik
from settings_store import load as load_settings


def pilih_model(cfg: dict, cli_model: str) -> tuple[str, str]:
    """Pulang (provider, model). provider: openrouter | gemini."""
    or_k = dapatkan_kunci(cfg.get("openrouter_key", ""))
    gem_k = dapatkan_kunci_gemini(cfg.get("gemini_key", ""))
    if cli_model:
        if cli_model.startswith("gemini") and "/" not in cli_model:
            return "gemini", cli_model
        return "openrouter", cli_model
    if or_k:
        try:
            ranked, _ = cari_model_terbaik(limit=12)
            free = [m["id"] for m in ranked if m["price"] == 0]
            for cand in free[:6]:
                if _ping_openrouter(or_k, cand):
                    print(f"[model] guna percuma terbaik live: {cand}")
                    return "openrouter", cand
            print("[model] semua model percuma gagal ping — cuba model simpanan.")
        except Exception as e:
            print(f"[model] ranking gagal ({e}), guna lalai.")
        return "openrouter", cfg.get("model") or DEFAULT_MODEL
    if gem_k:
        return "gemini", "gemini-3.8-flash"
    return "openrouter", cfg.get("model") or DEFAULT_MODEL


def _ping_openrouter(key: str, model: str) -> bool:
    """Panggilan mini untuk sahkan model boleh guna (murah, ~saat)."""
    import requests
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "HTTP-Referer": "be2026-filler", "X-Title": "BE2026 filler"},
            json={"model": model, "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 2},
            timeout=45)
        ok = r.status_code == 200
        print(f"[model] ping {model}: {r.status_code}")
        return ok
    except Exception as e:
        print(f"[model] ping {model} gagal: {e}")
        return False


def semak_tulis(out: str) -> None:
    """Gagal awal jika fail output dikunci (cth. terbuka dalam Excel)."""
    try:
        with open(out, "ab"):
            pass
    except OSError:
        raise SystemExit(f"Tutup dahulu {out} (terbuka dalam Excel?) — tidak boleh tulis.")


def panggil_ai(provider, model, nama, tahun, medan, konteks, or_k, gem_k, anggaran):
    if provider == "gemini":
        peta, nota = perkaya_gemini(nama, tahun, medan, konteks, gem_k, model,
                                    anggaran=anggaran)
        return peta, nota, model
    peta, nota = perkaya_syarikat(nama, tahun, medan, konteks, or_k, model,
                                  anggaran=anggaran)
    return peta, nota, model


def main() -> int:
    ap = argparse.ArgumentParser(description="Auto-isi borang XLSX tanpa GUI.")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--cui", default="")
    ap.add_argument("--company", default="")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--model", default="")
    ap.add_argument("--batch", type=int, default=60)
    ap.add_argument("--with-suggest", action="store_true")
    ap.add_argument("--format", dest="fmt", choices=("xlsx", "txt"), default="xlsx",
                    help="xlsx: tulis buku kerja; txt: tulis fail teks sahaja (tanpa xlsx)")
    a = ap.parse_args()
    t0 = time.time()

    cfg = load_settings()
    or_k = dapatkan_kunci(cfg.get("openrouter_key", ""))
    gem_k = dapatkan_kunci_gemini(cfg.get("gemini_key", ""))
    semak_tulis(a.out)
    provider, model = pilih_model(cfg, a.model)
    if provider == "openrouter" and not or_k:
        print("AMARAN: tiada kunci OpenRouter — hanya data online + manual.")
    nama = a.company.strip() or a.cui.strip() or "(tidak dinyatakan)"

    print(f"[1/4] Imbas {a.inp} ...")
    fields, sheets = inspect_template(a.inp)
    print(f"      {len(fields)} medan, helaian={sheets}")

    print("[2/4] Carian dalam talian (ANAF/BNR/BNM) ...")
    rows, log = aggregate(a.cui, fields, a.year)
    print("      " + " | ".join(log["steps"]))
    konteks = {"anaf": log.get("anaf", {}), "fx": log.get("fx", {}),
               "fx_myr": log.get("fx_myr", {})}

    def kelompok(daftar, anggaran):
        peta_all, nota_all, used = {}, [], model
        gagal_berturut = 0
        total = (len(daftar) + a.batch - 1) // max(a.batch, 1)
        for i in range(0, len(daftar), a.batch):
            chunk = daftar[i:i + a.batch]
            print(f"      AI kelompok {i // a.batch + 1}/{total} "
                  f"({'anggar' if anggaran else 'fakta'}): {len(chunk)} medan ...")
            peta, nota, used = panggil_ai(provider, model, nama, a.year, chunk,
                                          konteks, or_k, gem_k, anggaran)
            nota_all.append(nota)
            peta_all.update(peta)
            print(f"        -> {nota}")
            if not peta and ("dilangkau" in nota):
                break  # tiada kunci — jangan bazir panggilan lanjut
            if not peta:
                gagal_berturut += 1
                if gagal_berturut >= 3:
                    print("      3 kelompok gagal berturut — berhenti.")
                    break
            else:
                gagal_berturut = 0
        return peta_all, " | ".join(nota_all), used

    if a.with_suggest:
        print("[3a/4] AI fakta ...")
        medan = [{"label": r.label, "cell": f"{r.sheet}!{r.cell}", "sheet": r.sheet,
                  "semasa": r.proposed} for r in rows]
        peta, nota, used = kelompok(medan, False)
        n = gabung_ai_ke_baris(rows, peta, used)
        print(f"      fakta disentuh: {n}")

    kosong = [r for r in rows if r.proposed in (None, "")]
    print(f"[3b/4] AI anggaran baki: {len(kosong)} medan kosong ...")
    if kosong and (or_k or gem_k):
        medan = [{"label": r.label, "cell": f"{r.sheet}!{r.cell}", "sheet": r.sheet,
                  "semasa": r.proposed} for r in kosong]
        peta, nota, used = kelompok(medan, True)
        n = gabung_ai_ke_baris(rows, peta, used)
        print(f"      anggaran disentuh: {n}")
    elif not kosong:
        print("      tiada medan kosong.")
    else:
        print("      dilangkau (tiada kunci AI).")

    values = {(r.sheet, r.cell): (r.proposed if r.proposed != "" else r.alternate)
              for r in rows if r.include}
    berisi = sum(1 for v in values.values() if v not in (None, ""))
    if a.fmt == "txt":
        from datetime import date
        from filler.textout import tulis_teks
        baris = [{"sheet": r.sheet, "cell": r.cell, "label": r.label,
                  "nilai": (r.proposed if r.proposed != "" else r.alternate),
                  "sumber": (r.proposed_source if r.proposed not in (None, "")
                             else (r.alternate_source if r.alternate not in (None, "")
                                   else r.proposed_source)),
                  "keyakinan": r.confidence, "nota": r.note} for r in rows]
        print(f"[4/4] Tulis teks {a.out} ({berisi}/{len(baris)} berisi) ...")
        out = tulis_teks(baris, {"tajuk": Path(a.inp).stem, "syarikat": nama,
                                 "tahun": a.year, "tarikh": str(date.today())}, a.out)
        print(f"      siap: {out} dalam {time.time() - t0:.0f}s.")
        return 0
    print(f"[4/4] Tulis {a.out} ({berisi}/{len(values)} berisi) ...")
    out, skipped = fill_template(a.inp, a.out, values)
    print(f"      siap: {out} (formula dilindungi: {skipped}) "
          f"dalam {time.time() - t0:.0f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
