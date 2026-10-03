"""Kp205.py — interactive KP205 estimator.

Run:
  python Kp205.py

Flow:
  Enter Company name : <nama>
  Search Data.....      -> web search (free), dossier collected to temp
  Estimate with AI..... -> dossier used as reference to estimate KP205 values
  Result: C:\\Users\\tokki\\Downloads\\x205.txt

Flags (optional, for testing): --company, --year, --out, --no-web, --offline.
Keys read from config/settings.json or env OPENROUTER_API_KEY / GEMINI_API_KEY.
Without keys: labelled offline heuristics (never empty, never crashes).
"""
from __future__ import annotations
import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from kp205.template_fields import blank_kp205_fields, MANUAL_ONLY
from kp205.anchors import tanya_jangkar, apply_anchors, anchor_context, parse_num
from kp205.estimator import (get_dossier, build_context, estimate_missing,
                             apply_estimates, offline_fallback_estimates)
from kp205.report_txt import tulis_laporan
from search.ai_openrouter import DEFAULT_MODEL, dapatkan_kunci
from search.ai_gemini import DEFAULT_GEMINI_MODEL, dapatkan_kunci_gemini
from search.syarikat import tulis_dosier, slug
from settings_store import load as load_settings
from activity import subscribe

DEFAULT_OUT = Path("C:/Users/tokki/Downloads/x205.txt")


def _log_line(stamp: str, tag: str, msg: str) -> None:
    print(f"  [{stamp}] {tag} {msg}", flush=True)


def _ping_openrouter(key: str, model: str, timeout: int = 25) -> bool:
    """Quick pre-flight check so we fail over to offline in seconds, not minutes."""
    import requests
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                      "Content-Type": "application/json",
                      "HTTP-Referer": "kp205", "X-Title": "KP205"},
            json={"model": model,
                   "messages": [{"role": "user", "content": "ping"}],
                   "max_tokens": 2},
            timeout=timeout)
        if r.status_code == 200:
            return True
        print(f"  ping {model}: HTTP {r.status_code} — {r.text[:160]}",
              flush=True)
        return False
    except Exception as e:
        print(f"  ping gagal: {e}", flush=True)
        return False


def _gemini_model(cfg: dict) -> str:
    """Honor the selected Gemini model; retired ids auto-remap to working default."""
    from search.ai_gemini import resolve_gemini_model
    m = (cfg.get("model") or "").strip()
    if m and "/" not in m:
        return resolve_gemini_model(m)
    if m and "/" in m:
        return resolve_gemini_model("")  # OpenRouter id -> Gemini default
    return resolve_gemini_model("")


def pick_model(cfg: dict, cli_provider: str = "auto") -> tuple[str, str]:
    or_k = dapatkan_kunci(cfg.get("openrouter_key", ""))
    gem_k = dapatkan_kunci_gemini(cfg.get("gemini_key", ""))
    # "auto" follows the SAVED provider first (Settings tab selection),
    # then falls back to key-based detection as before
    prov = cli_provider if cli_provider != "auto" \
        else (cfg.get("provider") or "auto")
    if prov == "local":
        from search.ai_local import local_model as _lm
        return "local", _lm(cfg.get("local_model", ""))
    if prov in ("hf", "huggingface"):
        from search.ai_hf import hf_model as _hm
        return "huggingface", _hm(cfg.get("hf_model", ""))
    if prov == "gemini" and gem_k:
        return "gemini", _gemini_model(cfg)
    if prov == "openrouter" and or_k:
        return "openrouter", cfg.get("model") or DEFAULT_MODEL
    if gem_k:
        return "gemini", _gemini_model(cfg)
    return "openrouter", cfg.get("model") or DEFAULT_MODEL


def main() -> int:
    ap = argparse.ArgumentParser(description="Kp205 interactive estimator.")
    ap.add_argument("--company", default="")
    ap.add_argument("--year", type=int, default=0)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--xls-in", default="C:/Users/tokki/Downloads/205.xlsx")
    ap.add_argument("--xls-out", default="C:/Users/tokki/Downloads/x205.xlsx")
    ap.add_argument("--no-xls", action="store_true")
    ap.add_argument("--provider", choices=("auto", "openrouter", "gemini",
                                            "local", "hf", "huggingface"),
                    default="auto")
    ap.add_argument("--sektor", choices=("auto", "perkhidmatan", "pembuatan",
                                            "pembinaan"),
                    default="auto")
    ap.add_argument("--seimbang", type=float, default=0.0,
                    help="Sasar IO dan seimbangkan automatik (cth 0.65; 0=mati)")
    ap.add_argument("--no-web", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--no-ask", action="store_true",
                    help="Langkau soalan angka manual (AI anggar semua)")
    for k in ("pendapatan", "belanja", "aset", "stok_awal", "stok_akhir",
              "sewa", "L", "P", "warga", "bwn"):
        ap.add_argument(f"--{k.replace('_', '-')}", default="",
                        help=f"Angka manual: {k} (cth --pendapatan 880610)")
    a = ap.parse_args()
    t0 = time.time()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("=== KP205 AI Estimator ===")
    nama = (a.company or input("Enter Company name : ")).strip()
    if not nama:
        print("Nama kosong — tamat.")
        return 1
    if a.year:
        tahun = a.year
    else:
        raw = input("Enter Year [2025] : ").strip()
        tahun = int(raw) if raw.isdigit() else 2025

    # ---- step 0: manual anchors (optional known figures) ----
    flag_anchors = {}
    for k in ("pendapatan", "belanja", "aset", "stok_awal", "stok_akhir",
              "sewa", "L", "P", "warga", "bwn"):
        v = parse_num(getattr(a, k, "") or "")
        if v is not None:
            flag_anchors[k] = v
    if a.no_ask:
        anchors = flag_anchors
    elif flag_anchors and a.company:
        anchors = flag_anchors  # non-interactive: flags only
    else:
        anchors = tanya_jangkar(flag_anchors)
    if anchors:
        print(f"  angka pengguna: {len(anchors)} medan.")


    cfg = load_settings()
    or_k = dapatkan_kunci(cfg.get("openrouter_key", ""))
    gem_k = dapatkan_kunci_gemini(cfg.get("gemini_key", ""))
    loc_u = cfg.get("local_url", "")
    loc_m = cfg.get("local_model", "")
    loc_k = cfg.get("local_key", "")
    hf_k = cfg.get("hf_key", "")
    hf_m = cfg.get("hf_model", "")
    provider, model = pick_model(cfg, a.provider)
    subscribe(_log_line)  # live progress for search + AI (no more silent hangs)

    # ---- step 1: search web, collect to temp ----
    print("Search Data.....")
    tmpdir = Path(tempfile.gettempdir()) / "kp205"
    tmpdir.mkdir(parents=True, exist_ok=True)
    if a.no_web:
        dossier = {"nama": nama, "status": "DILANGKAU (--no-web)",
                   "sebab": "carian web dimatikan", "skor": 0.0,
                   "hasil": [], "direktori": [], "no_ssm": [],
                   "anggaran": {}, "tarikh": ""}
    else:
        try:
            dossier = get_dossier(nama)
        except Exception as e:
            dossier = {"nama": nama, "status": "Ralat", "sebab": str(e),
                       "skor": 0.0, "hasil": [], "direktori": [],
                       "no_ssm": [], "anggaran": {}, "tarikh": ""}
    dosier_tmp = tmpdir / f"{slug(nama)}_dossier.txt"
    # resolve Bing redirect links to real destinations (best-effort, quick)
    if not a.no_web and dossier.get("hasil"):
        from search.syarikat import _selesai_url
        for h in dossier["hasil"]:
            try:
                h["url"] = _selesai_url(h.get("url", ""))
            except Exception:
                pass
        print(f"  URLs resolved.")
    try:
        tulis_dosier(dossier, dosier_tmp)
        print(f"  collected -> {dosier_tmp}")
    except Exception as e:
        print(f"  (nota: dossier temp gagal ditulis: {e})")
    print(f"  status: {dossier.get('status')} — {dossier.get('sebab')} "
          f"({len(dossier.get('hasil', []))} bukti)")

    # ---- step 2: estimate with AI using dossier as reference ----
    print("Estimate with AI.....")
    fields, meta = blank_kp205_fields(nama, tahun)
    meta["fail"] = "(blank template)"
    # ---- step 1b: META web-catch (facts from websites, not guesses) ----
    from kp205.meta_web import tangkap
    n_meta, nota_meta = tangkap(nama, tahun, dossier, fields,
                                or_k, gem_k, provider, model,
                                local_url=loc_u, local_model=loc_m,
                                local_key=loc_k, hf_key=hf_k, hf_model=hf_m)
    print(f"  META web-catch: {n_meta} diisi. {nota_meta}", flush=True)
    n_j = apply_anchors(fields, anchors)
    if n_j:
        print(f"  {n_j} angka pengguna dimasuk (keyakinan TINGGI).")
    # ---- step 1b: pecahan berkadar totals -> relevant sub-questions ----
    from kp205.pecahan import pecah_auto
    sek = "" if a.sektor == "auto" else a.sektor
    n_p, prof = pecah_auto(fields, nama, str(dossier.get("anggaran", "")),
                           sektor=sek)
    meta["profil"] = prof
    if n_p:
        print(f"  {n_p} pecahan berkadar (profil {prof}) — komponen genap jumlah.")
    konteks = build_context(nama, tahun, meta, dossier)
    konteks["data_pengguna"] = anchor_context(anchors)
    konteks["pecahan"] = (f"{n_p} komponen dipenuhi pecahan berkadar "
                          f"(profil {prof}); JANGAN ubah — anggar BAKI medan "
                          f"sahaja.") if n_p else "Tiada pecahan."
    from kp205.gaji import skala_teks
    konteks["skala_gaji"] = skala_teks()
    # attach web evidence as reference for the AI
    ref = []
    for h in (dossier.get("hasil", []) or [])[:10]:
        ref.append(f"{h.get('tajuk','')} | {h.get('petikan','')[:200]} | {h.get('url','')}")
    konteks["rujukan_web"] = ref
    konteks["anggaran_dossier"] = dossier.get("anggaran", {})

    for_ai = [f for f in fields
              if f.get("missing") and f["id"] not in MANUAL_ONLY]
    nota_ai = ""
    from search.ai_local import ping_local as _ping_local
    loc_ok = False
    if not a.offline:
        loc_ok, _loc_nota = _ping_local(loc_u)
    use_ai = bool(or_k or gem_k or loc_ok or hf_k.strip()) and not a.offline
    if use_ai and provider == "local" and not loc_ok:
        print(f"  Lokal tidak respons ({_loc_nota}) — cuba kunci cloud ...",
              flush=True)
    if use_ai and provider == "openrouter":
        # pre-flight: free models often queue/stall — check in ~25s
        # instead of hanging 3+ min per batch
        print(f"  Pre-flight ping {model} ...", flush=True)
        if not _ping_openrouter(or_k, model):
            print("  Model tidak respons — guna heuristik offline "
                  "(tukar 'model' dalam settings.json untuk model laju).",
                  flush=True)
            use_ai = False
    if not use_ai:
        n = offline_fallback_estimates(fields)
        nota_ai = (f"Offline: {n} heuristik dilabel. "
                   "Tambah kunci OpenRouter/Gemini atau hidupkan gateway lokal "
                   "(localhost:4000) untuk anggaran penuh AI.")
        print(f"  {nota_ai}")
    else:
        from kp205.estimator import estimate_sections

        def _prog(sec, i, t, n, done):
            if not done:
                print(f"  Seksyen {i}/{t}: {sec} ({n} medan)...", flush=True)
            else:
                print(f"    -> {sec} siap: {n} diisi.", flush=True)

        n, nota_sec, used = estimate_sections(
            nama, tahun, fields, konteks, or_k, gem_k,
            provider, model, progress=_prog,
            local_url=loc_u, local_model=loc_m, local_key=loc_k,
            hf_key=hf_k, hf_model=hf_m)
        nota_ai = f"AI {used}: {n} ({nota_sec})."
        print(f"  {nota_ai}")
        if n == 0:
            n2 = offline_fallback_estimates(fields)
            nota_ai += f" | fallback offline: {n2} heuristik."
            print(f"  {nota_ai}")

    # ---- step 2b: gaji ikut jawatan (post-pass) ----
    from kp205.gaji import agih_gaji
    gstat = agih_gaji(fields)
    if gstat["monthly"]:
        print(f"  gaji: {gstat['monthly']} kadar jawatan"
              + (f", jumlah terbitan RM{gstat['bills']:,}" if gstat["total"] else "")
              + (f", KWSP/PERKESO dikira semula x{gstat['kwsp']}" if gstat["kwsp"] else "")
              + ".")

    # ---- step 2b2: selaras konsistensi (deterministik, bukan AI) ----
    from kp205.selaras import selaras_konsistensi
    kstat = selaras_konsistensi(fields)
    if any(kstat.values()):
        print(f"  selaras: jumlah {kstat['jumlah']}, pekerja {kstat['pekerja']}, "
              f"gaji {kstat['gaji']}, KWSP/PERKESO {kstat['kwsp']}, "
              f"shif {kstat.get('shift', 0)}.")

    # ---- step 2c: selaras Untung = Pendapatan - Belanja (tepat) ----
    from kp205.anchors import selaras_untung
    changed, uval = selaras_untung(fields)
    if changed:
        print(f"  untung diselaraskan: RM{uval:,} (= pendapatan − belanja).")

    # ---- step 2d: seimbangkan IO ke sasaran (jika diminta) ----
    if a.seimbang:
        from kp205.seimbang import terap
        plan = terap(fields, a.seimbang, paksa_aset=True)
        if plan.get("ok") and plan.get("dilaksana"):
            print(f"  seimbang: {plan['mesej']}"
                  + (f" Aset RM{plan['aset_ditetapkan']:,}"
                     if plan.get("aset_ditetapkan") else ""))
        else:
            print(f"  seimbang gagal: {plan.get('mesej', '?')}")

    # ---- step 3: result ----
    berisi = sum(1 for f in fields if not f.get("missing"))
    out = Path(a.out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tulis_laporan(fields, meta, dossier, nota_ai, out)
    except OSError as e:
        out = tmpdir / "x205.txt"
        tulis_laporan(fields, meta, dossier, nota_ai, out)
        print(f"  (nota: {a.out} tidak boleh ditulis [{e}] — guna {out})")
    print(f"Done in {time.time() - t0:.0f}s. "
          f"Lengkap: {berisi}/{len(fields)}.")
    print(f"Result: {out}")
    # ---- step 4: fill a copy of the real 205.xlsx (formulas kept) ----
    if not a.no_xls and Path(a.xls_in).exists():
        from kp205.xlsx_fill import isi_xlsx
        try:
            print(f"Isi workbook {a.xls_in} ...")
            xo, n_w, n_o, n_s, _unmap = isi_xlsx(a.xls_in, a.xls_out, fields)
            print(f"  xlsx: {n_w} sel diisi -> {xo} ({n_s} dilangkau: "
                  f"formula/berisi/tiada padanan). Buka dalam Excel untuk kira semula.")
        except Exception as e:
            print(f"  (nota: isi xlsx gagal: {e})")
    elif not a.no_xls:
        print(f"  (nota: {a.xls_in} tiada — langkau isi xlsx.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
