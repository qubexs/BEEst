"""Gaji ikut jawatan: position-based monthly RANGES drive wage bills.

Each position has a market monthly range [dari, hingga] (PKS micro/small).
Monthly field value = midpoint; annual bill per category =
headcount x midpoint x 12. If 9.36(a) total is still missing, it is
DERIVED from the bills (relevant to posts, not a blind guess).
KWSP (13%) / PERKESO (1.75%) are recomputed whenever they are still
offline-heuristics and the gaji total is known.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

SKALA_FILE = Path(__file__).resolve().parent.parent / "config" / "gaji_skala.json"

SKALA = {  # monthly RM [dari, hingga] by position — defaults
    "Pemilik": [4000, 6000],
    "Pengurus": [3500, 5500],
    "Profesional (Pro)": [3000, 4600],
    "Penyelidik": [2800, 4200],
    "Juruteknik": [2200, 3400],
    "Mahir berkaitan": [2000, 3200],
    "Jualan": [1900, 2900],
    "Kerani": [1700, 2700],
    "Operator": [1700, 2300],
    "Asas": [1500, 2100],
    "Keluarga": [1200, 1800],
}


def parse_julat(raw) -> tuple[float, float] | None:
    """'1800-2200' / 'RM 1,800 - RM 2,200' / 2000 / [1800,2200] -> (lo, hi)."""
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            lo, hi = float(raw[0]), float(raw[1])
            return (min(lo, hi), max(lo, hi))
        except (ValueError, TypeError):
            return None
    if raw is None:
        return None
    s = str(raw).replace("RM", "").replace(",", "").strip()
    if not s:
        return None
    if "-" in s:
        parts = [p.strip() for p in s.split("-", 1)]
        try:
            lo, hi = float(parts[0]), float(parts[1])
            return (min(lo, hi), max(lo, hi))
        except ValueError:
            return None
    try:
        v = float(s)
        return (v, v)
    except ValueError:
        return None


def _bulat(v: float):
    return int(v) if float(v).is_integer() else round(v, 2)


def mid(julat: tuple[float, float]) -> float:
    return (julat[0] + julat[1]) / 2


def get_skala() -> dict:
    """Monthly ranges {kat: (dari, hingga)}: file overrides defaults."""
    out = {k: (float(v[0]), float(v[1])) for k, v in SKALA.items()}
    try:
        if SKALA_FILE.exists():
            custom = json.loads(SKALA_FILE.read_text(encoding="utf-8"))
            for k, v in custom.items():
                if k in out:
                    j = parse_julat(v)
                    if j is not None:
                        out[k] = j
    except Exception:
        pass
    return out


def save_skala(d: dict) -> None:
    """Persist custom monthly ranges (validated only)."""
    clean = {}
    for k, v in SKALA.items():
        j = parse_julat(d.get(k, v))
        if j is None:
            j = (float(v[0]), float(v[1]))
        clean[k] = [_bulat(j[0]), _bulat(j[1])]
    SKALA_FILE.parent.mkdir(parents=True, exist_ok=True)
    SKALA_FILE.write_text(json.dumps(clean, indent=2, ensure_ascii=False),
                          encoding="utf-8")

OFFLINE_SRCS = {"ANGGARAN (13% gaji)", "ANGGARAN (1.75% gaji)"}


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def skala_teks() -> str:
    skala = get_skala()
    return ("Kadar gaji bulanan pasaran PKS (WAJIB guna untuk anggaran "
            "berkaitan gaji): "
            + ", ".join(f"{k} RM{lo:g}–RM{hi:g}"
                         for k, (lo, hi) in skala.items()))


def agih_gaji(fields: list[dict], only: set | None = None) -> dict:
    """Post-pass after headcounts exist. Returns counts dict.

    If `only` is given, unticked ids are skipped (GUI refill control).
    """
    def ok(fid: str) -> bool:
        return only is None or fid in only

    by_id = {f["id"]: f for f in fields}
    skala = get_skala()
    n_m = 0
    bills: list[tuple[str, int]] = []
    for gender, tag in (("L", "Lelaki"), ("P", "Perempuan")):
        for kat, (lo, hi) in skala.items():
            monthly = mid((lo, hi))
            fid = f"GAJI::{gender}::{kat}"
            f = by_id.get(fid)
            hc = _num((by_id.get(f"PEKERJA::{gender}::{kat}") or {})
                      .get("value"))
            if f is not None and f.get("missing") and ok(fid):
                nota = (f"Kadar pasaran {kat} ({tag}), bulanan "
                        f"RM{lo:g}–RM{hi:g}")
                if hc:
                    nota += f"; {hc:g} orang x RM{monthly:g} x 12"
                f.update(value=_bulat(monthly), raw=str(_bulat(monthly)),
                         missing=False, source="Skala jawatan PKS",
                         confidence="SEDARHANA", note=nota)
                n_m += 1
            if hc:
                bills.append((f"{tag} {kat}", int(hc * monthly * 12)))
    n_tot = 0
    tot_bills = sum(v for _, v in bills)
    g = by_id.get("PERBELANJAAN::9.36(a)")
    if g is not None and g.get("missing") and tot_bills > 0 \
            and ok("PERBELANJAAN::9.36(a)"):
        top = sorted(bills, key=lambda x: -x[1])[:3]
        nota = "Terbitan ikut jawatan: " + " + ".join(
            f"{k} RM{v:g}" for k, v in top)
        if len(bills) > 3:
            nota += f" (+{len(bills) - 3} lagi)"
        g.update(value=tot_bills, raw=str(tot_bills), missing=False,
                 source="Terbitan (ikut jawatan)", confidence="SEDARHANA",
                 note=nota[:220])
        n_tot = 1
    n_kw = 0
    gval = _num(g.get("value")) if g is not None else None
    if gval:
        for code, rate, lab in (("9.36(d)(i)", 0.13, "KWSP"),
                                ("9.36(d)(iii)", 0.0175, "PERKESO")):
            fid = f"PERBELANJAAN::{code}"
            f = by_id.get(fid)
            if f is not None and (f.get("missing")
                                  or f.get("source") in OFFLINE_SRCS) \
                    and ok(fid):
                v = round(gval * rate)
                f.update(value=v, raw=str(v), missing=False,
                         source=f"ANGGARAN ({rate * 100:g}% gaji)",
                         confidence="RENDAH",
                         note=f"{lab} {rate * 100:g}% x gaji RM{gval:g} (jawatan)")
                n_kw += 1
    return {"monthly": n_m, "total": n_tot, "kwsp": n_kw,
            "bills": tot_bills}
