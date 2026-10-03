"""Selaras konsistensi: deterministic post-pass after AI/offline estimates.

Fixes three structural failure modes that AI section-by-section estimation
cannot guarantee on its own:

1. Jumlah terkunci: 8.13 == 8.15 (hasil), 9.39 == 9.44 (belanja).
   The "JUMLAH BESAR" twin is the truth; the weaker-sourced twin is
   overwritten so the report never carries two different revenues.
2. Jumlah kategori pekerja == jumlah L/P: category breakdowns are
   largest-remainder rescaled to the declared L/P totals instead of
   leaving AI-invented sums (e.g. 3 kategori lelaki vs Jumlah L=1).
3. Gaji sifar: a GAJI entry of RM0 (or any out-of-scale value) on a
   zero-headcount position is cleared to missing — unstaffed posts must
   not carry wage values, otherwise "Gaji luar julat skala" fires.
   KWSP (13%) / PERKESO (1.75%) are recomputed from gaji when the
   current value is only a weak guess.

Only weak sources are ever overwritten (AI/pecahan/offline/terbitan);
real data (Input pengguna, FAIL_TXT, Suntingan pengguna, Web:) wins.
Returns a stats dict for logging.
"""
from __future__ import annotations

from kp205.anchors import BOLEH_SELARAS

PB, PP = "PERBELANJAAN", "PENDAPATAN"

# Sources treated as ground truth — never overwritten by reconciliation.
KUAT = {"Input pengguna", "Suntingan pengguna", "FAIL_TXT", "FAIL TXT"}


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _kuat(f: dict) -> bool:
    if f.get("missing"):
        return False
    src = str(f.get("source") or "")
    if src in KUAT or src.startswith("Web:") or src.startswith("FAIL"):
        return True
    if f.get("confidence") == "TINGGI" and src not in BOLEH_SELARAS:
        return True
    return False


def _agih_baki(total: int, weights: dict[str, float]) -> dict[str, int]:
    """Largest-remainder split of `total` by weights (deterministic)."""
    keys = list(weights.keys())
    wsum = sum(weights.values()) or 1
    exact = [total * weights[k] / wsum for k in keys]
    base = [int(x) for x in exact]
    baki = total - sum(base)
    urut = sorted(range(len(keys)), key=lambda i: exact[i] - base[i],
                  reverse=True)
    for i in urut[:max(0, baki)]:
        base[i] += 1
    return dict(zip(keys, base))


def _kunci_jumlah(by_id: dict, fid_benar: str, fid_kembar: str,
                  nama: str, stats: dict) -> None:
    """Force twin totals equal; weaker-sourced twin follows the stronger."""
    a, b = by_id.get(fid_benar), by_id.get(fid_kembar)
    if a is None or b is None:
        return
    va, vb = _num(a.get("value")), _num(b.get("value"))
    if va is None or vb is None or va == vb:
        return
    # Strong-side wins; if tied, the JUMLAH BESAR twin (fid_benar) wins.
    if _kuat(a) and not _kuat(b):
        benar, kembar, v = a, b, va
    elif _kuat(b) and not _kuat(a):
        benar, kembar, v = b, a, vb
    else:
        benar, kembar, v = a, b, va
    iv = int(round(v))
    kembar.update(value=iv, raw=str(iv), missing=False,
                  source="Selaras jumlah", confidence="SEDARHANA",
                  note=f"Diselaraskan = {nama} RM{iv:g} "
                       f"(sebelum RM{vb:g})"[:220])
    stats["jumlah"] += 1


def _selaras_pekerja(by_id: dict, fields: list[dict],
                     stats: dict) -> None:
    """Rescale L/P category breakdowns to declared L/P totals."""
    for gender in ("L", "P"):
        tot_f = by_id.get(f"PEKERJA::{'Pekerja Lelaki (L)' if gender == 'L'
                                     else 'Pekerja Perempuan (P)'}")
        if tot_f is None:
            continue
        tot = _num(tot_f.get("value"))
        if tot is None:
            continue
        tot = int(round(tot))
        kats = [f for f in fields
                if f["id"].startswith(f"PEKERJA::{gender}::")]
        if not kats:
            continue
        vals = {f["id"]: _num(f.get("value")) for f in kats}
        if any(v is None for v in vals.values()):
            continue  # incomplete — leave for validation SKIP, not guess
        s = sum(vals.values())
        if int(round(s)) == tot:
            continue
        if all(not _kuat(by_id[fid]) for fid in vals):
            # All weak: rescale proportionally (largest remainder = exact).
            weights = {fid: (v if v > 0 else 0.01) for fid, v in vals.items()}
            # keep zero categories at zero when total is small
            if tot == 0:
                for f in kats:
                    f.update(value=0, raw="0", missing=False,
                             source="Selaras pekerja", confidence="SEDARHANA",
                             note="Jumlah sifar — kategori disifarkan")
                    stats["pekerja"] += 1
                continue
            agih = _agih_baki(tot, weights)
            # never resurrect a zero category the AI deliberately left at 0
            # unless the total forces it (tot > number of nonzero cats)
            for f in kats:
                v = agih[f["id"]]
                f.update(value=v, raw=str(v), missing=False,
                         source="Selaras pekerja", confidence="SEDARHANA",
                         note=f"Skala semula supaya jumlah kategori = {tot:g}")
                stats["pekerja"] += 1
        # else: real category data — leave mismatch to validation warning.


def _selaras_pendidikan(by_id: dict, fields: list[dict],
                       stats: dict) -> None:
    """Rescale education breakdown to Jumlah pekerja (weak sources only)."""
    tot_f = by_id.get("PEKERJA::Pekerja — Jumlah besar (Total)")
    if tot_f is None:
        return
    tot = _num(tot_f.get("value"))
    if tot is None:
        return
    tot = int(round(tot))
    kats = [f for f in fields if f["id"].startswith("PENDIDIKAN::")]
    if not kats:
        return
    vals = {f["id"]: _num(f.get("value")) for f in kats}
    if any(v is None for v in vals.values()):
        return  # incomplete — SKIP, not guess
    if int(round(sum(vals.values()))) == tot:
        return
    if not all(not _kuat(by_id[fid]) for fid in vals):
        return  # real data — leave to KRITIKAL warning
    if tot == 0:
        for f in kats:
            f.update(value=0, raw="0", missing=False,
                     source="Selaras pekerja", confidence="SEDARHANA",
                     note="Jumlah sifar — tahap disifarkan")
            stats["pekerja"] += 1
        return
    weights = {fid: (v if v > 0 else 0.01) for fid, v in vals.items()}
    agih = _agih_baki(tot, weights)
    for f in kats:
        v = agih[f["id"]]
        f.update(value=v, raw=str(v), missing=False,
                 source="Selaras pekerja", confidence="SEDARHANA",
                 note=f"Skala semula supaya jumlah tahap = {tot:g}")
        stats["pekerja"] += 1


def _selaras_gaji(by_id: dict, stats: dict) -> None:
    """Clear wage values on zero-headcount posts; fix statutory ratios."""
    try:
        from kp205.gaji import get_skala
        skala = get_skala()
    except Exception:
        skala = {}
    for gender in ("L", "P"):
        for kat in (skala or {}):
            h_f = by_id.get(f"PEKERJA::{gender}::{kat}")
            g_f = by_id.get(f"GAJI::{gender}::{kat}")
            if g_f is None or g_f.get("missing"):
                continue
            hc = _num(h_f.get("value")) if h_f is not None else None
            gv = _num(g_f.get("value"))
            if hc == 0 and gv is not None:
                # Unstaffed post must not carry a wage (not even 0).
                g_f.update(value="", raw="", missing=True,
                           source="—", confidence="RENDAH",
                           note="Dikosongkan: tiada pekerja jawatan ini")
                stats["gaji"] += 1
            elif gv == 0 and not _kuat(g_f):
                g_f.update(value="", raw="", missing=True,
                           source="—", confidence="RENDAH",
                           note="Dikosongkan: gaji RM0 bukan kadar sah")
                stats["gaji"] += 1
    # KWSP 13% / PERKESO 1.75% are REFERENCE rates (+- tolerance).
    # Weak values inside the band are left alone; only outliers snap
    # to the reference (same bands as semakan checks 7/8).
    gval = _num((by_id.get(f"{PB}::9.36(a)") or {}).get("value"))
    if gval:
        for code, rate, lo, hi, lab in (
                ("9.36(d)(i)", 0.13, 0.11, 0.15, "KWSP"),
                ("9.36(d)(iii)", 0.0175, 0.010, 0.025, "PERKESO")):
            f = by_id.get(f"{PB}::{code}")
            if f is None or f.get("missing") or _kuat(f):
                continue
            cur = _num(f.get("value"))
            ratio = (cur / gval) if cur is not None else None
            if ratio is not None and lo <= ratio <= hi:
                continue  # within +- tolerance — real-world variance, keep
            want = round(gval * rate)
            if cur != want:
                f.update(value=want, raw=str(want), missing=False,
                         source=f"ANGGARAN ({rate * 100:g}% gaji ±)",
                         confidence="RENDAH",
                         note=f"Selaras {lab} rujukan {rate * 100:g}% x gaji "
                              f"RM{gval:g} (sebelum RM{(cur or 0):g})"[:220])
                stats["kwsp"] += 1
    # Levi 9.36(i) follows BWN: no foreigners -> levy 0 (never a guess).
    bwn = _num((by_id.get("PEKERJA::Pekerja — Bukan Warganegara (BWN)")
                or {}).get("value"))
    if bwn == 0:
        f = by_id.get(f"{PB}::9.36(i)")
        if f is not None and (f.get("missing") or not _kuat(f)):
            cur = _num(f.get("value"))
            if cur:
                f.update(value=0, raw="0", missing=False,
                         source="Terbitan (tiada BWN)", confidence="SEDARHANA",
                         note=f"Tiada BWN — levi disifarkan (sebelum RM{cur:g})"
                         [:220])
                stats["kwsp"] += 1
            elif f.get("missing"):
                f.update(value=0, raw="0", missing=False,
                         source="Terbitan (tiada BWN)", confidence="SEDARHANA",
                         note="Tiada BWN — levi RM0"[:220])
                stats["kwsp"] += 1


def _selaras_shift(by_id: dict, stats: dict) -> None:
    """Derive exact shift relations (missing fields only, never overwrite)."""
    def _isi(fid: str, v, note: str):
        f = by_id.get(fid)
        if f is not None and f.get("missing"):
            iv = int(v) if float(v).is_integer() else round(v, 2)
            f.update(value=iv, raw=str(iv), missing=False,
                     source="Terbitan (shif)", confidence="SEDARHANA",
                     note=note[:220])
            stats["shift"] += 1

    hari = _num((by_id.get("SHIFT::Hari beroperasi") or {}).get("value"))
    jam = _num((by_id.get("SHIFT::Jam/Shift") or {}).get("value"))
    if hari is not None and jam is not None:
        _isi("SHIFT::Jumlah Jam", hari * jam,
             f"Terbitan: {hari:g} hari x {jam:g} jam/shif")
    jam_ot = _num((by_id.get("SHIFT::JAM OT") or {}).get("value"))
    upah_ot = _num((by_id.get("SHIFT::Upah OT") or {}).get("value"))
    if jam_ot == 0 and upah_ot is None:
        _isi("SHIFT::Upah OT", 0, "Tiada jam OT — upah OT RM0")
    elif upah_ot == 0 and jam_ot is None:
        _isi("SHIFT::JAM OT", 0, "Tiada upah OT — jam OT 0")


def selaras_konsistensi(fields: list[dict]) -> dict:
    """Run all reconciliation passes. Returns stats dict."""
    stats = {"jumlah": 0, "pekerja": 0, "gaji": 0, "kwsp": 0, "shift": 0}
    by_id = {f["id"]: f for f in fields}
    _kunci_jumlah(by_id, f"{PP}::8.15", f"{PP}::8.13",
                  "JUMLAH BESAR hasil", stats)
    _kunci_jumlah(by_id, f"{PB}::9.44", f"{PB}::9.39",
                  "JUMLAH BESAR belanja", stats)
    _selaras_pekerja(by_id, fields, stats)
    _selaras_pendidikan(by_id, fields, stats)
    _selaras_gaji(by_id, stats)
    _selaras_shift(by_id, stats)
    return stats
