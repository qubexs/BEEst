"""KP205 AI-CLI: txt dump -> carian web percuma + anggaran AI -> laporan TXT.

Contoh:
  python kp205_cli.py --in sample_kp205.txt --out laporan.txt --company "SZK KENANGA VENTURES" --year 2022
  python kp205_cli.py --in sample.txt --out lap.txt --no-web --offline  (tiada internet / tiada kunci)

Kunci dibaca dari config/settings.json atau env OPENROUTER_API_KEY / GEMINI_API_KEY.
Tanpa kunci: heuristik offline + data fail (dilabel) — tidak kosong.
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from kp205.parser_txt import parse_kp205_file
from kp205.estimator import (get_dossier, build_context, estimate_missing,
                             apply_estimates, offline_fallback_estimates)
from kp205.report_txt import tulis_laporan
from search.ai_openrouter import DEFAULT_MODEL, dapatkan_kunci
from search.ai_gemini import DEFAULT_GEMINI_MODEL, dapatkan_kunci_gemini
from settings_store import load as load_settings


def pick_model(cfg: dict, cli_model: str, provider: str) -> tuple[str, str]:
    or_k = dapatkan_kunci(cfg.get("openrouter_key", ""))
    gem_k = dapatkan_kunci_gemini(cfg.get("gemini_key", ""))
    if cli_model:
        if provider == "gemini" or (cli_model.startswith("gemini") and "/" not in cli_model):
            return "gemini", cli_model
        return "openrouter", cli_model
    if provider == "auto":
        provider = cfg.get("provider") or "auto"  # honor Settings selection
    if provider == "gemini" and gem_k:
        return "gemini", cfg.get("model") or DEFAULT_GEMINI_MODEL
    if provider == "openrouter" and or_k:
        return "openrouter", cfg.get("model") or DEFAULT_MODEL
    # auto
    if or_k:
        return "openrouter", cfg.get("model") or DEFAULT_MODEL
    if gem_k:
        return "gemini", cfg.get("model") or DEFAULT_GEMINI_MODEL
    return "openrouter", cfg.get("model") or DEFAULT_MODEL


def main() -> int:
    ap = argparse.ArgumentParser(description="KP205 AI-CLI (txt -> anggaran -> txt).")
    ap.add_argument("--in", dest="inp", required=True, help="Fail txt dump KP205")
    ap.add_argument("--out", dest="out", required=True, help="Laporan TXT output")
    ap.add_argument("--company", default="", help="Nama syarikat (override meta fail)")
    ap.add_argument("--year", type=int, default=2022)
    ap.add_argument("--provider", choices=("auto", "openrouter", "gemini"),
                    default="auto")
    ap.add_argument("--model", default="")
    ap.add_argument("--batch", type=int, default=60)
    ap.add_argument("--sektor", choices=("auto", "perkhidmatan", "pembuatan"),
                    default="auto")
    ap.add_argument("--no-web", action="store_true", help="Langkau carian web")
    ap.add_argument("--offline", action="store_true",
                    help="Jangan panggil AI (heuristik offline sahaja)")
    a = ap.parse_args()
    t0 = time.time()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = load_settings()
    or_k = dapatkan_kunci(cfg.get("openrouter_key", ""))
    gem_k = dapatkan_kunci_gemini(cfg.get("gemini_key", ""))
    provider, model = pick_model(cfg, a.model, a.provider)

    print(f"[1/4] Parse {a.inp} ...")
    try:
        fields, meta = parse_kp205_file(a.inp)
    except FileNotFoundError as e:
        print(f"RALAT: {e}")
        return 2
    if a.company.strip():
        meta["company"] = a.company.strip()
    nama = meta.get("company") or a.company.strip() or "(tidak dinyatakan)"
    print(f"      {len(fields)} medan, syarikat={nama!r}")
    n_have = sum(1 for f in fields if not f["missing"])
    print(f"      sedia ada: {n_have}/{len(fields)} berisi")

    if a.no_web:
        dossier = {"status": "DILANGKAU (--no-web)", "sebab": "carian web dimatikan",
                   "no_ssm": [], "hasil": []}
        print("[2/4] Carian web dilangkau.")
    else:
        print("[2/4] Carian web percuma (DDG->Bing) ...")
        try:
            dossier = get_dossier(nama)
        except Exception as e:
            dossier = {"status": "Ralat", "sebab": str(e), "no_ssm": [], "hasil": []}
        print(f"      {dossier.get('status')}: {dossier.get('sebab')} "
              f"({len(dossier.get('hasil', []))} bukti)")

    missing = [f for f in fields if f["missing"]]
    print(f"[3/4] Anggaran AI: {len(missing)} medan kosong ...")
    # pecahan: split known file totals into missing sub-questions first
    from kp205.pecahan import pecah_auto
    sek = "" if a.sektor == "auto" else a.sektor
    n_p, prof = pecah_auto(fields, nama, meta.get("aktiviti", ""),
                           sektor=sek)
    meta["profil"] = prof
    if n_p:
        print(f"      {n_p} pecahan berkadar (profil {prof}).")
        missing = [f for f in fields if f["missing"]]
    nota_ai = ""
    if not missing:
        nota_ai = "Tiada medan kosong."
        print("      " + nota_ai)
    elif a.offline or (not or_k and not gem_k):
        n = offline_fallback_estimates(fields)
        nota_ai = (f"Offline: {n} heuristik dilabel (KWSP/PERKESO/pekerja). "
                   "Tambah kunci OpenRouter/Gemini untuk anggaran penuh AI.")
        print(f"      {nota_ai}")
    else:
        konteks = build_context(nama, a.year, meta, dossier)
        konteks["pecahan"] = (
            f"{n_p} komponen dipenuhi pecahan berkadar (profil {prof}); "
            f"anggar BAKI medan sahaja.") if n_p else "Tiada pecahan."
        from kp205.gaji import skala_teks
        konteks["skala_gaji"] = skala_teks()
        peta, nota_ai, used = estimate_missing(
            nama, a.year, missing, konteks, or_k, gem_k, provider, model,
            batch=max(a.batch, 1))
        n = apply_estimates(fields, peta, used)
        print(f"      AI {used}: {n} anggaran diguna. {nota_ai}")
        if n == 0:
            n2 = offline_fallback_estimates(fields)
            nota_ai += f" | fallback offline: {n2} heuristik."
            print(f"      {nota_ai}")

    from kp205.gaji import agih_gaji
    gstat = agih_gaji(fields)
    if gstat["monthly"]:
        print(f"      gaji: {gstat['monthly']} kadar jawatan"
              + (f", jumlah terbitan RM{gstat['bills']:,}" if gstat["total"] else "")
              + (f", KWSP/PERKESO dikira semula x{gstat['kwsp']}" if gstat["kwsp"] else "")
              + ".")

    from kp205.anchors import selaras_untung
    changed, uval = selaras_untung(fields)
    if changed:
        print(f"      untung diselaraskan: RM{uval:,} (= pendapatan − belanja).")

    berisi = sum(1 for f in fields if not f["missing"])
    print(f"[4/4] Tulis {a.out} ({berisi}/{len(fields)} berisi) ...")
    out = tulis_laporan(fields, meta, dossier, nota_ai, a.out)
    print(f"      siap: {out} dalam {time.time() - t0:.0f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
