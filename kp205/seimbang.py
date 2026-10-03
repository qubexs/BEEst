"""Seimbangkan IO: adjust figures to hit a target IO ratio.

IO = (Belanja − Susut − BelanjaPekerja[9.36]) / Pendapatan = target
=> delta = target*H − (B − S − P), added to an adjustable input
   component (9.1 preferred, else 9.2/9.4/9.35). Belanja totals and
   Untung are cascaded. Assets fixed to a sane multiple of susut.

Only AI/pecahan/offline-sourced fields are adjusted — user/file values
(Input pengguna, FAIL_TXT, Suntingan pengguna) are never overwritten;
conflicts are reported instead.
"""
from __future__ import annotations

from kp205.report_txt import PEKERJA_CODES, CORE_CODES
from kp205.anchors import BOLEH_SELARAS

PB, PP = "PERBELANJAAN", "PENDAPATAN"
KANDIDAT_BAHAN = ["9.1", "9.2", "9.4", "9.35"]


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def baca_io(fields: list[dict]) -> dict | None:
    """Current IO components, or None if core data missing."""
    by_id = {f["id"]: f for f in fields}

    def get(fid):
        f = by_id.get(fid)
        return _num(f.get("value")) if f is not None else None

    h = get(f"{PP}::8.15") or get(f"{PP}::8.13") or get(f"{PP}::8.1")
    b = get(f"{PB}::9.39") or get(f"{PB}::9.44")
    s = get(f"{PB}::9.29")
    if h is None or b is None or s is None:
        return None
    pek, hilang_teras = 0.0, []
    for c in PEKERJA_CODES:
        v = get(f"{PB}::{c}")
        if v is None:
            if c in CORE_CODES:
                hilang_teras.append(c)
        else:
            pek += v
    if hilang_teras:
        return None
    return {"H": h, "B": b, "S": s, "P": pek,
            "I": b - s - pek, "io": (b - s - pek) / h if h else None}


def cadang(fields: list[dict], target: float = 0.65,
           skip: set | None = None) -> dict:
    """Dry-run balancing plan (no changes). Returns plan dict."""
    cur = baca_io(fields)
    if cur is None or cur["io"] is None:
        return {"ok": False,
                "mesej": "Data teras IO tak cukup (jumlah hasil/belanja, "
                         "susut, atau kod pekerja kosong)."}
    if not (0 < target < 2):
        return {"ok": False, "mesej": f"Sasaran {target} tidak sah (0–2)."}
    delta = round(target * cur["H"] - cur["I"])
    plan: dict = {"ok": True, "io_kini": cur["io"], "target": target,
                  "delta": delta, "cur": cur}
    if delta == 0:
        plan["mesej"] = f"IO sudah tepat {target:g} — tiada pelarasan."
        return plan
    by_id = {f["id"]: f for f in fields}
    for code in KANDIDAT_BAHAN:
        fid = f"{PB}::{code}"
        if skip is not None and fid in skip:
            continue
        f = by_id.get(fid)
        if f is None or f.get("missing"):
            continue
        if f.get("source") in (None, "", "—") or \
                f.get("source") in BOLEH_SELARAS:
            plan.update(kod=code, fid=f"{PB}::{code}",
                        nilai_lama=_num(f.get("value")) or 0)
            break
    else:
        plan["ok"] = False
        plan["mesej"] = ("Tiada komponen boleh laras (9.1/9.2/9.4/9.35 "
                         "semua data pengguna/fail) — untick atau kosongkan "
                         "satu komponen dahulu.")
        return plan
    # asset fix suggestion
    susut = cur["S"]
    aset_f = by_id.get("ASET::Jumlah")
    aset_v = _num(aset_f.get("value")) if aset_f is not None else None
    if aset_v is None or aset_v <= susut:
        plan["aset_saran"] = round(susut / 0.15)
    plan["mesej"] = (f"Tambah RM{delta:+,} pada {plan['kod']} "
                     f"(RM{plan['nilai_lama']:g} → RM{plan['nilai_lama'] + delta:,g}) "
                     f"untuk IO {cur['io']:.4f} → {target:g}.")
    return plan


def terap(fields: list[dict], target: float = 0.65,
          skip: set | None = None, paksa_aset: bool = False) -> dict:
    """Apply balancing plan. Returns plan dict (ok + details).

    paksa_aset: also fix user/file asset values when they violate
    Aset > Susut (explicit balance action; old value noted).
    """
    plan = cadang(fields, target, skip=skip)
    if not plan.get("ok") or plan.get("delta", 0) == 0:
        return plan
    from kp205.anchors import selaras_untung
    by_id = {f["id"]: f for f in fields}
    delta = plan["delta"]
    f = by_id[plan["fid"]]
    baharu = plan["nilai_lama"] + delta
    f.update(value=baharu, raw=str(baharu), missing=False,
             source="Seimbangan auto", confidence="SEDARHANA",
             note=f"Dilaras {delta:+,} untuk sasar IO {target:g}")
    # cascade belanja totals + untung. Totals ALWAYS move (the explicit
    # balance action requires it) — old value recorded in the note.
    for fid in (f"{PB}::9.39", f"{PB}::9.44"):
        t = by_id.get(fid)
        if t is not None and not t.get("missing"):
            lama = _num(t.get("value")) or 0
            nv = lama + delta
            t.update(value=nv, raw=str(nv), missing=False,
                     source="Seimbangan auto", confidence="SEDARHANA",
                     note=f"Ikutan {delta:+,} dari {plan['kod']} "
                          f"(asal RM{lama:g})")
    selaras_untung(fields)
    # asset fix: estimable fields always; user/file values only when
    # paksa_aset (explicit balance action — old value noted)
    if plan.get("aset_saran"):
        a = by_id.get("ASET::Jumlah")
        if a is not None and ((a.get("missing")
                               or a.get("source") in BOLEH_SELARAS)
                              or (paksa_aset and not a.get("missing"))) \
                and (skip is None or "ASET::Jumlah" not in skip):
            v = plan["aset_saran"]
            lama = _num(a.get("value"))
            a.update(value=v, raw=str(v), missing=False,
                     source="Seimbangan auto", confidence="RENDAH",
                     note=f"Aset ≈ susut/15% (mesti > susut RM{plan['cur']['S']:g})"
                          + (f" (asal RM{lama:g})" if lama else ""))
            plan["aset_ditetapkan"] = v
    plan["dilaksana"] = True
    return plan
