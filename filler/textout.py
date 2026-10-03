"""Tulis hasil borang ke fail teks berstruktur (bukan XLSX).

Susun: helaian -> seksyen -> item (kod + label + lajur) = nilai [sumber].
Tiada pergantungan selain stdlib.
"""
from __future__ import annotations
from pathlib import Path


def tulis_teks(baris: list[dict], meta: dict, path: str | Path) -> str:
    """baris: [{sheet, cell, label, nilai, sumber, keyakinan, nota}].

    meta: {tajuk, syarikat, tahun, tarikh}.
    Pulangan: path str.
    """
    L = [f"=== {meta.get('tajuk', 'BORANG')} (BE {meta.get('tahun', '')}) ===",
         f"Syarikat: {meta.get('syarikat', '(tidak dinyatakan)')}",
         f"Tarikh: {meta.get('tarikh', '')}",
         ""]
    berisi = sum(1 for b in baris if b.get("nilai") not in (None, ""))
    L.append(f"Lengkap: {berisi}/{len(baris)} berisi")
    L.append("")
    helaian_akhir, seksyen_akhir = None, None
    for b in baris:
        sh = b.get("sheet", "?")
        if sh != helaian_akhir:
            L.append(f"##### Helaian: {sh} #####")
            helaian_akhir, seksyen_akhir = sh, None
        bahagian = (b.get("label") or "").split(" › ")
        seksyen = bahagian[0] if len(bahagian) >= 3 else ""
        tajuk = " › ".join(bahagian[1:] if len(bahagian) >= 3 else bahagian)
        if seksyen != seksyen_akhir:
            if seksyen:
                L.append("")
                L.append(f"## {seksyen}")
            seksyen_akhir = seksyen
        nilai = b.get("nilai")
        v = str(nilai) if nilai not in (None, "") else "(kosong)"
        L.append(f"[{b.get('cell')}] {tajuk} = {v}")
        L.append(f"    sumber: {b.get('sumber', '?')} | keyakinan: {b.get('keyakinan', '?')}"
                 + (f" | nota: {b.get('nota')}" if b.get("nota") else ""))
    L.append("")
    L.append("=== TAMAT ===")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return str(p)
