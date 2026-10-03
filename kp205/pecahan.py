"""Pecahan berkadar: split anchor totals into relevant sub-questions by ratio.

Pendapatan total -> 8.1, 8.3, 8.4, ... (NOT % codes like 8.1.1, NOT totals 8.13/8.15)
Perbelanjaan total -> 9.1, 9.2, ... (NOT % codes, NOT totals 9.39/9.44,
NOT 9.40-9.43 company-specific items left for AI)

Weights are normalized in code (need not sum to 100).
KWSP (13%) & PERKESO (1.75%) are derived precisely from the gaji share.
Result: components add up to the anchor by construction (rounding fixed
on the largest component).
"""
from __future__ import annotations
import hashlib

from kp205.parser_txt import SECTION_PENDAPATAN, SECTION_BELANJA

PENDAPATAN_PERKHIDMATAN = {
    "8.1": 86, "8.3": 2, "8.4": 2, "8.5": 1, "8.6": 4, "8.7": 0.5,
    "8.8(e)": 0.5, "8.8(g)": 0.5, "8.9": 0.2,
    "8.10(c)": 0.2, "8.10(e)": 0.5, "8.10(h)": 0.3, "8.10(j)": 0.1,
    "8.12": 2.2,
}
PENDAPATAN_PEMBUATAN = {
    "8.1": 94, "8.2.1": 1, "8.2.3": 0.5, "8.3": 1, "8.4": 0.5, "8.5": 0.5,
    "8.6": 0.2, "8.7": 0.2, "8.8(e)": 0.2, "8.8(g)": 0.1, "8.9": 0.1,
    "8.10(c)": 0.1, "8.10(e)": 0.2, "8.10(h)": 0.2, "8.10(j)": 0.2,
    "8.12": 1.0,
}
BELANJA_PERKHIDMATAN = {
    "9.1": 8, "9.2": 1, "9.3": 1, "9.4": 1, "9.5": 1, "9.6": 0.3,
    "9.7": 1.5, "9.8": 1, "9.10": 2, "9.11": 2, "9.12": 2, "9.13": 1.5,
    "9.14": 2, "9.15": 1.5, "9.16": 0.5, "9.17": 2, "9.18": 1,
    "9.19": 0.3, "9.20": 0.5, "9.21": 1.5, "9.22": 1, "9.23": 2.5,
    "9.24": 2, "9.25": 2, "9.26": 1.2, "9.27": 2, "9.28(b)": 8,
    "9.29": 4, "9.30": 0.5, "9.32(b)(i)": 0.2, "9.32(b)(ii)": 0.2,
    "9.32(b)(iii)": 0.2, "9.32(c)": 0.5, "9.33(a)": 0.2, "9.33(c)": 0.2,
    "9.33(d)": 0.3, "9.33(e)": 0.2, "9.35": 2,
    "9.36(a)": 30, "9.36(b)": 0.5, "9.36(c)(i)": 0.5, "9.36(c)(ii)": 1,
    "9.36(d)(ii)": 0.2, "9.36(d)(iv)": 0.1, "9.36(d)(v)": 0.2,
    "9.36(e)": 2, "9.36(f)": 0.3, "9.36(g)": 1, "9.36(h)": 0.8,
    "9.36(i)": 0.3, "9.36(j)": 0.1, "9.36(k)": 0.5, "9.37": 2, "9.38": 1,
    "9.41": 0.5, "9.43": 1.5,
}
BELANJA_PEMBUATAN = {
    "9.1": 38, "9.2": 3, "9.3": 2, "9.4": 1.5, "9.5": 0.5, "9.6": 0.3,
    "9.7": 2, "9.8": 1.5, "9.10": 1, "9.11": 2, "9.12": 1, "9.13": 2,
    "9.14": 1, "9.15": 1, "9.16": 0.3, "9.17": 1, "9.18": 0.5,
    "9.19": 0.2, "9.20": 0.3, "9.21": 1, "9.22": 0.5, "9.23": 1,
    "9.24": 1, "9.25": 0.5, "9.26": 0.5, "9.27": 1, "9.28(b)": 5,
    "9.29": 5, "9.30": 1, "9.31(a)": 0.2, "9.32(b)(i)": 0.3,
    "9.32(b)(ii)": 0.2, "9.32(b)(iii)": 0.2, "9.32(c)": 1,
    "9.33(a)": 0.2, "9.33(c)": 0.2, "9.33(d)": 0.2, "9.35": 1.5,
    "9.36(a)": 22, "9.36(b)": 0.3, "9.36(c)(i)": 0.3, "9.36(c)(ii)": 0.8,
    "9.36(d)(ii)": 0.1, "9.36(d)(iv)": 0.1, "9.36(d)(v)": 0.1,
    "9.36(e)": 1.5, "9.36(f)": 0.2, "9.36(g)": 0.5, "9.36(h)": 0.5,
    "9.36(i)": 0.3, "9.36(j)": 0.1, "9.36(k)": 0.3, "9.37": 1.5, "9.38": 0.8,
    "9.41": 0.3, "9.43": 1,
}

BUAT_KATA = ("buat", "proses", "pasang", "kilang", "manufactur", "pengilang",
             "pembuatan", "bina", "kontrak", "makan", "food", "resto",
             "minuman", "roti", "plastik", "kayu", "tekstil", "jahit",
             "cetak", "perabot", "furniture", "furnitur", "factory",
             "pembekal perabot", "wood", "timber")


def pilih_profil(nama: str = "", aktiviti: str = "",
                 sektor: str = "") -> tuple[str, dict, dict]:
    """Returns (profile_name, pendapatan_table, belanja_table).

    sektor: "" (auto by keywords), "pembuatan", or "perkhidmatan".
    """
    s = (sektor or "").strip().lower()
    if s.startswith("pembuat") or s.startswith("manufact"):
        return "pembuatan", PENDAPATAN_PEMBUATAN, BELANJA_PEMBUATAN
    if s.startswith("perkhid") or s.startswith("serv"):
        return "perkhidmatan", PENDAPATAN_PERKHIDMATAN, BELANJA_PERKHIDMATAN
    t = f"{nama} {aktiviti}".lower()
    if any(k in t for k in BUAT_KATA):
        return "pembuatan", PENDAPATAN_PEMBUATAN, BELANJA_PEMBUATAN
    return "perkhidmatan", PENDAPATAN_PERKHIDMATAN, BELANJA_PERKHIDMATAN


def _num(v) -> float | None:
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _jitter(seed: str, code: str, amp: float = 4.0) -> float:
    """Deterministic ±amp% variation per company+code (0.1% steps).

    Same company+code always gives the same factor (stable reports),
    but equal weights no longer produce identical RM values.
    """
    h = hashlib.md5(f"{seed}|{code}".encode("utf-8")).hexdigest()
    steps = int(h[:8], 16) % int(2 * amp * 10 + 1)
    return 1.0 + (steps / 10.0 - amp) / 100.0


def _unikkan(vals: list[int], target: int) -> list[int]:
    """Force all values distinct (growing deterministic nudges).

    Sum is re-fixed on the largest component each pass, so the
    total stays exact while no two components share a value.
    """
    vals = list(vals)
    if not vals:
        return vals
    for rnd in range(1, 6):
        big = max(range(len(vals)), key=lambda i: vals[i])
        vals[big] += target - sum(vals)
        seen: set[int] = set()
        dups = False
        for i in sorted(range(len(vals)), key=lambda j: vals[j],
                        reverse=True):
            if vals[i] in seen:
                vals[i] = max(0, vals[i] + rnd)
                dups = True
            seen.add(vals[i])
        if not dups:
            break
    big = max(range(len(vals)), key=lambda i: vals[i])
    vals[big] += target - sum(vals)
    return vals


def pecah_auto(fields: list[dict], nama: str = "",
               aktiviti: str = "", only: set | None = None,
               sektor: str = "") -> tuple[int, str]:
    """Split known totals (anchor or file values) into missing components.

    Reads totals from fields themselves: 8.13/8.15 and 9.39/9.44.
    Only fills currently-missing components (and, if `only` is given,
    only fields whose id is in that set — e.g. ticked rows in the GUI).
    sektor: "" auto, "pembuatan", "perkhidmatan".
    Returns (count, profile_name).
    """
    by_id = {f["id"]: f for f in fields}
    pname, tab_p, tab_b = pilih_profil(nama, aktiviti, sektor)

    def total(*fids):
        for fid in fids:
            f = by_id.get(fid)
            v = _num(f.get("value")) if f is not None else None
            if v:
                return v
        return None

    n = 0
    jobs = [
        (f"{SECTION_PENDAPATAN}::8.13", f"{SECTION_PENDAPATAN}::8.15",
         SECTION_PENDAPATAN, dict(tab_p), "hasil"),
        (f"{SECTION_BELANJA}::9.39", f"{SECTION_BELANJA}::9.44",
         SECTION_BELANJA, dict(tab_b), "belanja"),
    ]
    for fid_t1, fid_t2, sec, table, kind in jobs:
        tot = total(fid_t1, fid_t2)
        if not tot:
            continue
        seed = f"{nama}|{tot:g}"
        # shares computed over ALL missing components (proportional),
        # but only ticked ones are filled when `only` is given
        targets = [(c, w) for c, w in table.items()
                   if (f := by_id.get(f"{sec}::{c}")) is not None
                   and f.get("missing")]
        if not targets:
            continue
        wsum = sum(w for _, w in targets)

        def fill(code: str, v: int, base_note: str):
            if only is not None and f"{sec}::{code}" not in only:
                return 0  # unticked in GUI: leave empty for manual/AI later
            f = by_id[f"{sec}::{code}"]
            f.update(value=v, raw=str(v), missing=False,
                     source="Pecahan berkadar", confidence="SEDARHANA",
                     note=base_note)
            return 1

        if kind == "belanja" and any(c == "9.36(a)" for c, _ in targets):
            # gaji first (with jitter), then KWSP/PERKESO exact from it,
            # remainder spread over the rest — total stays exact
            wg = next(w for c, w in targets if c == "9.36(a)")
            gaji = max(0, round(tot * wg / wsum * _jitter(seed, "9.36(a)")))
            kwsp = round(gaji * 0.13)
            perkeso = round(gaji * 0.0175)
            rest = [t for t in targets if t[0] not in
                    ("9.36(a)", "9.36(d)(i)", "9.36(d)(iii)")]
            rsum = sum(w for _, w in rest)
            rest_tot = round(tot) - gaji - kwsp - perkeso
            vals = [max(0, round(rest_tot * w / rsum * _jitter(seed, c)))
                    for c, w in rest]
            vals = _unikkan(vals, rest_tot)
            n += fill("9.36(a)", gaji,
                      f"Gaji pecahan ±4% (profil {pname})")
            if (f := by_id.get(f"{sec}::9.36(d)(i)")) is not None \
                    and f.get("missing") \
                    and (only is None or f"{sec}::9.36(d)(i)" in only):
                n += fill("9.36(d)(i)", kwsp,
                          f"13% × gaji RM{gaji:g} tepat — profil {pname}")
            if (f := by_id.get(f"{sec}::9.36(d)(iii)")) is not None \
                    and f.get("missing") \
                    and (only is None or f"{sec}::9.36(d)(iii)" in only):
                n += fill("9.36(d)(iii)", perkeso,
                          f"1.75% × gaji RM{gaji:g} tepat — profil {pname}")
            for (code, w), v in zip(rest, vals):
                pct = 100 * v / tot if tot else 0
                n += fill(code, v,
                          f"{pct:.2f}% × jumlah RM{tot:g} ±4% (profil {pname})")
        else:
            vals = [max(0, round(tot * w / wsum * _jitter(seed, c)))
                    for c, w in targets]
            vals = _unikkan(vals, round(tot))
            for (code, w), v in zip(targets, vals):
                pct = 100 * v / tot if tot else 0
                n += fill(code, v,
                          f"{pct:.2f}% × jumlah RM{tot:g} ±4% (profil {pname})")
    return n, pname
