"""Manual anchor figures: user types known KP205 totals, AI estimates the rest.

Sections: Pendapatan, Perbelanjaan, Pekerja (L/P + Warga/BWN),
Aset, Stok, Sewa Premis. Blank = AI estimates everything.
"""
from __future__ import annotations
import re

from kp205.parser_txt import SECTION_PENDAPATAN, SECTION_BELANJA, SECTION_PEKERJA
from kp205.parser_txt import SECTION_ASET, SECTION_STOK

ANCHOR_IDS = {
    "pendapatan": (f"{SECTION_PENDAPATAN}::8.13", f"{SECTION_PENDAPATAN}::8.15"),
    "belanja": (f"{SECTION_BELANJA}::9.39", f"{SECTION_BELANJA}::9.44"),
    "aset": (f"{SECTION_ASET}::Jumlah",),
    "stok_awal": (f"{SECTION_STOK}::Jumlah::Awal",),
    "stok_akhir": (f"{SECTION_STOK}::Jumlah::Akhir",),
    "sewa": (f"{SECTION_BELANJA}::9.28(b)",),
    "L": (f"{SECTION_PEKERJA}::Pekerja Lelaki (L)",),
    "P": (f"{SECTION_PEKERJA}::Pekerja Perempuan (P)",),
    "warga": (f"{SECTION_PEKERJA}::Pekerja — Warganegara (Warga)",),
    "bwn": (f"{SECTION_PEKERJA}::Pekerja — Bukan Warganegara (BWN)",),
    "total": (f"{SECTION_PEKERJA}::Pekerja — Jumlah besar (Total)",),
}

PROMPTS = [
    ("pendapatan", "Pendapatan tahunan RM"),
    ("belanja", "Perbelanjaan tahunan RM"),
    ("aset", "Aset bersih jumlah RM"),
    ("stok_awal", "Stok awal tahun RM"),
    ("stok_akhir", "Stok akhir tahun RM"),
    ("sewa", "Sewa premis tahunan RM"),
    ("L", "Pekerja Lelaki (L)"),
    ("P", "Pekerja Perempuan (P)"),
    ("warga", "Pekerja Warganegara"),
    ("bwn", "Pekerja BWN (asing)"),
]


def parse_num(s: str):
    """'880,610' / 'RM 15,320' -> 880610. Blank/invalid -> None."""
    if s is None:
        return None
    s = str(s).strip().replace("RM", "").replace(",", "").strip()
    if not s:
        return None
    try:
        v = float(s)
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


def tanya_jangkar(defaults: dict | None = None) -> dict:
    """Interactive prompt. Returns {key: number} for filled ones only."""
    defaults = defaults or {}
    print("-- Data sedia ada (Enter = kosongkan, AI anggar) --")
    out: dict = {}
    for key, lab in PROMPTS:
        dv = defaults.get(key)
        hint = f" [{dv}]" if dv is not None else ""
        try:
            raw = input(f"{lab}{hint}: ").strip()
        except EOFError:
            raw = ""
        if not raw and dv is not None:
            out[key] = dv
            continue
        v = parse_num(raw)
        if v is not None:
            out[key] = v
    # auto total L+P
    if "total" not in out and ("L" in out or "P" in out):
        out["total"] = (out.get("L") or 0) + (out.get("P") or 0)
    return out


def apply_anchors(fields: list[dict], anchors: dict,
                  skip: set | None = None) -> int:
    """Fill anchor values as HIGH-confidence user input. Returns count.

    `skip`: field ids to leave alone (GUI unticked rows).
    """
    by_id = {f["id"]: f for f in fields}
    n = 0
    for key, v in anchors.items():
        for fid in ANCHOR_IDS.get(key, ()):
            if skip is not None and fid in skip:
                continue
            f = by_id.get(fid)
            if f is None:
                continue
            f["value"] = v
            f["raw"] = str(v)
            f["missing"] = False
            f["source"] = "Input pengguna"
            f["confidence"] = "TINGGI"
            f["note"] = "Angka diberi pengguna — AI anggar baki ikut nisbah ini"
            n += 1
    # derive Untung Semasa when both totals known
    if "pendapatan" in anchors and "belanja" in anchors:
        f = by_id.get(f"{SECTION_PENDAPATAN}::Untung::Semasa")
        if f is not None and f.get("missing") and \
                (skip is None or
                 f"{SECTION_PENDAPATAN}::Untung::Semasa" not in skip):
            u = anchors["pendapatan"] - anchors["belanja"]
            f.update(value=u, raw=str(u), missing=False,
                     source="Terbitan (Pendapatan-Belanja)",
                     confidence="SEDARHANA",
                     note="Diterbit: pendapatan tolak belanja (angka pengguna)")
            n += 1
    return n


def _fnum(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


# Sources that may be overwritten by exact derivation (guesses, not facts)
BOLEH_SELARAS = {"ANGGARAN AI", "Pecahan berkadar", "ANGGARAN (13% gaji)",
                 "ANGGARAN (1.75% gaji)", "ANGGARAN AI (offline)",
                 "ANGGARAN (offline)", "ANGGARAN (Hari×Jam)",
                 "Terbitan (Pendapatan-Belanja)", "Terbitan (ikut jawatan)"}


def selaras_untung(fields: list[dict]) -> tuple[bool, int]:
    """Untung/Rugi Semasa = Jumlah Pendapatan − Jumlah Perbelanjaan.

    Sets the exact value when both totals are known, unless the current
    value is real data (fail/txt, input/suntingan pengguna) — those are
    kept and any mismatch is left to validation warnings.
    Returns (changed, value).
    """
    by_id = {f["id"]: f for f in fields}
    h = _fnum((by_id.get(f"{SECTION_PENDAPATAN}::8.15") or {}).get("value"))
    if h is None:
        h = _fnum((by_id.get(f"{SECTION_PENDAPATAN}::8.13") or {})
                  .get("value"))
    b = _fnum((by_id.get(f"{SECTION_BELANJA}::9.44") or {}).get("value"))
    if b is None:
        b = _fnum((by_id.get(f"{SECTION_BELANJA}::9.39") or {}).get("value"))
    if h is None or b is None:
        return False, 0
    u = round(h - b)
    f = by_id.get(f"{SECTION_PENDAPATAN}::Untung::Semasa")
    if f is None:
        return False, u
    cur = _fnum(f.get("value"))
    if cur == u:
        return False, u
    if f.get("missing") or f.get("source") in BOLEH_SELARAS:
        f.update(value=u, raw=str(u), missing=False,
                 source="Terbitan (Pendapatan-Belanja)",
                 confidence="SEDARHANA",
                 note=f"Selaras tepat: {h:g} − {b:g}")
        return True, u
    return False, u


def anchor_context(anchors: dict) -> str:
    """One-line summary injected into AI context as hard reference."""
    if not anchors:
        return "Tiada angka pengguna — anggar semua ikut nisbah lazim PKS."
    parts = []
    name = {"pendapatan": "Hasil", "belanja": "Belanja", "aset": "Aset",
            "stok_awal": "StokAwal", "stok_akhir": "StokAkhir",
            "sewa": "Sewa", "L": "Lelaki", "P": "Perempuan",
            "warga": "Warga", "bwn": "BWN", "total": "PekerjaTotal"}
    for k, v in anchors.items():
        parts.append(f"{name.get(k, k)}={v:g}" if isinstance(v, float)
                     else f"{name.get(k, k)}={v}")
    return ("ANGKA SAH PENGGUNA (WAJIB patuhi, jangan ubah; anggar medan lain "
            "supaya jumlah komponen menghampiri angka ini): " + ", ".join(parts))
