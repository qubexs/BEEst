"""kp205_clean.py — clean a raw KP205 txt dump + rebalance the ledger.

Takes a semi-structured DOSM KP205 text report, applies authoritative
variables (identity + totals), then re-balances (pecahan/untung/IO)
to resolve validation warnings.

  python kp205_clean.py --in dump.txt --out bersih.txt ^
    --company "SZK KENANGA VENTURES" --ssm 202201012345 ^
    --address "Kuala Lumpur" --msic 62012 --aktiviti "Perkhidmatan IT" ^
    --susut 39204 --hasil 880610 --belanja 731249 ^
    --sektor pembuatan --seimbang 0.65

Variable map:
  COMPANY_NAME    -> META::Company / Syarikat (+ headers)
  REGISTRATION_NO -> META::SSM No. Pendaftaran
  BUSINESS_ADDRESS-> META::Alamat berdaftar (created if absent)
  MSIC_CODE       -> META::Kod MSIC (Newss)
  MAIN_ACTIVITY   -> META::Aktiviti utama
  DEPRECIATION_VAL-> PERBELANJAAN::9.29
  TOTAL_REVENUE   -> PENDAPATAN::8.13 + 8.15
  TOTAL_EXPENSES  -> PERBELANJAAN::9.39 + 9.44
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PERANAN = ("Juruakaun cukai korporat Malaysia dan pakar pembersih data "
           "pematuhan survei DOSM: betulkan jurang identiti, seimbangkan "
           "lejar perakaunan (Jualan/Belanja/Untung/IO) supaya konsisten, "
           "label semua anggaran, jangan reka fakta identiti.")

VAR_MAP = [  # (cli-arg, field-id, section, label)
    ("company", "META::Company / Syarikat", "META", "Company / Syarikat"),
    ("ssm", "META::SSM No. Pendaftaran", "META", "SSM No. Pendaftaran"),
    ("address", "META::Alamat berdaftar", "META", "Alamat berdaftar"),
    ("msic", "META::Kod MSIC (Newss)", "META", "Kod MSIC (Newss)"),
    ("aktiviti", "META::Aktiviti utama", "META", "Aktiviti utama"),
    ("susut", "PERBELANJAAN::9.29", "PERBELANJAAN", "9.29 Susut nilai"),
    ("hasil", "PENDAPATAN::8.13", "PENDAPATAN", "8.13 Jumlah pendapatan"),
    ("hasil", "PENDAPATAN::8.15", "PENDAPATAN", "8.15 JUMLAH BESAR"),
    ("belanja", "PERBELANJAAN::9.39", "PERBELANJAAN", "9.39 Jumlah perbelanjaan"),
    ("belanja", "PERBELANJAAN::9.44", "PERBELANJAAN", "9.44 JUMLAH BESAR"),
]


def _num(raw):
    if raw is None:
        return None
    s = str(raw).strip().replace("RM", "").replace(",", "").strip()
    if not s:
        return None
    try:
        v = float(s)
        return int(v) if v.is_integer() else v
    except ValueError:
        return raw if isinstance(raw, str) and raw else None


def ensure_field(fields: list[dict], fid: str, section: str, label: str):
    for f in fields:
        if f["id"] == fid:
            return f
    f = {"id": fid, "section": section, "label": label, "value": "",
         "raw": "", "missing": True, "source": "—", "confidence": "RENDAH",
         "note": ""}
    fields.append(f)
    return f


def apply_variables(fields: list[dict], meta: dict, a) -> int:
    n = 0
    by_id = {f["id"]: f for f in fields}
    for arg, fid, sec, lab in VAR_MAP:
        raw = getattr(a, arg, "")
        if raw in (None, ""):
            continue
        if arg in ("susut", "hasil", "belanja"):
            v = _num(raw)
            if v is None or isinstance(v, str):
                print(f"  amaran: --{arg} '{raw}' bukan nombor — dilangkau.")
                continue
        else:
            v = str(raw).strip()
        f = by_id.get(fid)
        if f is None:
            f = ensure_field(fields, fid, sec, lab)
            by_id[fid] = f
        lama = f.get("value")
        f.update(value=v, raw=str(v), missing=False,
                 source="Input pengguna (clean)", confidence="TINGGI",
                 note="Pemboleh ubah sah clean"
                      + (f" (asal {lama})" if lama not in (None, "") else ""))
        n += 1
    if a.company.strip():
        meta["company"] = a.company.strip()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Bersih + seimbang dump KP205.")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--company", default="")
    ap.add_argument("--ssm", default="")
    ap.add_argument("--address", default="")
    ap.add_argument("--msic", default="")
    ap.add_argument("--aktiviti", default="")
    ap.add_argument("--susut", default="")
    ap.add_argument("--hasil", default="")
    ap.add_argument("--belanja", default="")
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--sektor", choices=("auto", "perkhidmatan", "pembuatan",
                                         "pembinaan"),
                    default="auto")
    ap.add_argument("--seimbang", type=float, default=0.0)
    ap.add_argument("--provider", choices=("auto", "openrouter", "gemini"),
                    default="auto")
    ap.add_argument("--model", default="")
    ap.add_argument("--batch", type=int, default=60)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from kp205.parser_txt import parse_kp205_file
    from kp205.pecahan import pecah_auto
    from kp205.gaji import agih_gaji, skala_teks
    from kp205.anchors import selaras_untung
    from kp205.estimator import (build_context, estimate_missing,
                                 apply_estimates, offline_fallback_estimates)
    from kp205.report_txt import tulis_laporan
    from kp205.semakan import semak
    from settings_store import load as load_settings
    from search.ai_openrouter import DEFAULT_MODEL, dapatkan_kunci
    from search.ai_gemini import dapatkan_kunci_gemini

    cfg = load_settings()
    or_k = dapatkan_kunci(cfg.get("openrouter_key", ""))
    gem_k = dapatkan_kunci_gemini(cfg.get("gemini_key", ""))
    prov = a.provider if a.provider != "auto" else (cfg.get("provider") or "auto")
    if a.model:
        model = a.model
    elif prov == "gemini" or (prov == "auto" and not or_k and gem_k):
        m0 = (cfg.get("model") or "").strip()
        model, prov = (m0 if m0 and "/" not in m0 else "gemini-3.8-flash"), \
            ("gemini" if (m0 and "/" not in m0) or not or_k else prov)
        if prov == "auto":
            prov = "gemini" if gem_k else "openrouter"
    else:
        model = cfg.get("model") or DEFAULT_MODEL

    print(f"[1/5] Parse {a.inp} ...")
    try:
        fields, meta = parse_kp205_file(a.inp)
    except FileNotFoundError as e:
        print(f"RALAT: {e}")
        return 2
    nama = (a.company.strip() or meta.get("company")
            or "(tidak dinyatakan)")
    meta["company"] = nama
    print(f"      {len(fields)} medan, syarikat={nama!r}")

    print("[2/5] Terap pemboleh ubah ...")
    n_v = apply_variables(fields, meta, a)
    print(f"      {n_v} medan ditetap (Input pengguna).")

    print("[3/5] Pecahan + gaji + selaras ...")
    sek = "" if a.sektor == "auto" else a.sektor
    n_p, prof = pecah_auto(fields, nama, meta.get("aktiviti", ""), sektor=sek)
    meta["profil"] = prof
    print(f"      pecahan: {n_p} (profil {prof}).")
    n_g = agih_gaji(fields)["monthly"]
    print(f"      gaji: {n_g} kadar jawatan.")
    ch, uv = selaras_untung(fields)
    if ch:
        print(f"      untung diselaraskan: RM{uv:,}.")

    print("[4/5] Anggaran baki ...")
    missing = [f for f in fields if f.get("missing")]
    nota_ai = ""
    if not missing:
        nota_ai = "Tiada medan kosong."
    elif a.offline or (not or_k and not gem_k):
        from kp205.estimator import offline_fallback_estimates as off
        n = off(fields)
        nota_ai = f"Offline: {n} heuristik."
    else:
        konteks = build_context(nama, a.year, meta,
                                {"status": "clean", "sebab": "dump + vars",
                                 "no_ssm": [], "hasil": []})
        konteks["peranan"] = PERANAN
        konteks["skala_gaji"] = skala_teks()
        peta, nota_ai, used = estimate_missing(
            nama, a.year,
            [{"label": f"[{m['section']}] {m['label']}", "cell": m["id"],
              "sheet": m["section"], "semasa": m.get("value", "")}
             for m in missing],
            konteks, or_k, gem_k, prov, model, batch=max(a.batch, 1))
        n = apply_estimates(fields, peta, used)
        print(f"      AI {used}: {n}. {nota_ai}")
    g2 = agih_gaji(fields)
    selaras_untung(fields)

    if a.seimbang:
        from kp205.seimbang import terap
        plan = terap(fields, a.seimbang, paksa_aset=True)
        if plan.get("ok") and plan.get("dilaksana"):
            print(f"      seimbang: {plan['mesej']}")
        else:
            print(f"      seimbang gagal: {plan.get('mesej', '?')}")

    print("[5/5] Semakan + tulis ...")
    warns = semak(fields, meta.get("profil", "perkhidmatan"))
    n_warn = sum(1 for w in warns if w.startswith("AMARAN"))
    print(f"      semakan: {len(warns)} checks, {n_warn} AMARAN.")
    for w in warns:
        if w.startswith("AMARAN"):
            print(f"        ! {w}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    tulis_laporan(fields, meta,
                  {"status": "clean", "sebab": "dump + pemboleh ubah",
                   "no_ssm": [], "hasil": []},
                  nota_ai, a.out)
    berisi = sum(1 for f in fields if not f.get("missing"))
    print(f"      siap: {a.out} ({berisi}/{len(fields)}) "
          f"dalam {time.time() - t0:.0f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
