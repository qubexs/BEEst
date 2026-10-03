"""Fill a copy of the real 205.xlsx with pipeline values (formulas preserved).

Safe cells only (never overwrite a value or formula):
- 8.x / 9.x detail rows  -> H{row}  (H = Value input column)
- Worker L categories     -> G{row}  (Lelaki Warga count)
- Worker P categories     -> V{row}  (Perempuan Warga count)
- Untung Semasa/Sebelum   -> H238/H239
BWN breakdowns (K/Z) left for manual entry.
Totals, assets matrix, wages, stok, negeri: untouched (they compute).
"""
from __future__ import annotations
import re
from pathlib import Path

from kp205.parser_txt import (SECTION_PENDAPATAN, SECTION_BELANJA,
                               SECTION_PEKERJA)

CELL_RE = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")


def valid_sel(sel: str) -> bool:
    """'H42' -> True; garbage -> False."""
    return bool(CELL_RE.match((sel or "").strip().upper()))


def sheets_of(template: str | Path) -> list[str]:
    """Sheet names (read-only probe, original untouched)."""
    import openpyxl
    wb = openpyxl.load_workbook(template, read_only=True, data_only=False)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def pick_sheet(template: str | Path) -> str | None:
    """'KP205' if present, else the only sheet, else None (ambiguous)."""
    names = sheets_of(template)
    if "KP205" in names:
        return "KP205"
    if len(names) == 1:
        return names[0]
    return None


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"\(.*?\)", "", s)  # drop "(Pro)", "(Bersih)" ...
    return re.sub(r"[^a-z0-9]+", "", s)


def build_map(template: str | Path, sheet: str = "KP205") -> dict:
    """Scan template once. Returns {field_id: (sheet, cell)}.

    Keys use normalized worker categories, e.g. PEKERJA::L::operator.
    Use _canon_worker_fid() on our field ids before lookup.
    """
    import openpyxl
    wb = openpyxl.load_workbook(template, read_only=True, data_only=False)
    try:
        ws = wb[sheet]
        m: dict = {}
        for r in range(1, ws.max_row + 1):
            b = ws.cell(row=r, column=2).value
            c = ws.cell(row=r, column=3).value
            if b is None:
                continue
            bs = str(b).strip()
            # 8.x / 9.x detail rows (writer skips formula/non-empty
            # cells anyway, so totals/% rows are safe to include)
            if re.match(r"^[89]\.", bs):
                sec = SECTION_PENDAPATAN if bs.startswith("8.") \
                    else SECTION_BELANJA
                m[f"{sec}::{bs}"] = ("KP205", f"H{r}")
            # worker categories: L -> G col, P -> V col (counts);
            # monthly wages: L -> P col, P -> AE col
            if 41 <= r <= 52:
                cn = _norm(str(c) if c else "")
                if cn:
                    if cn == "pro":
                        # must match _norm("Profesional (Pro)") on field side
                        cn = "profesional"
                    m[f"{SECTION_PEKERJA}::L::{cn}"] = ("KP205", f"G{r}")
                    m[f"{SECTION_PEKERJA}::P::{cn}"] = ("KP205", f"V{r}")
                    m[f"GAJI::L::{cn}"] = ("KP205", f"P{r}")
                    m[f"GAJI::P::{cn}"] = ("KP205", f"AE{r}")
            # profit rows
            if r in (238, 239) and c and "emas" in str(c).lower():
                tag = "Semasa" if r == 238 else "Sebelum"
                m[f"{SECTION_PENDAPATAN}::Untung::{tag}"] = ("KP205", f"H{r}")
        return m
    finally:
        wb.close()


def _canon_worker_fid(fid: str) -> str:
    """PEKERJA::L::Operator -> normalized lookup key."""
    parts = fid.split("::")
    if len(parts) == 3 and parts[1] in ("L", "P"):
        return f"{parts[0]}::{parts[1]}::{_norm(parts[2])}"
    return fid


def isi_xlsx(template: str | Path, out: str | Path,
             fields: list[dict], sheet: str = "KP205",
             overrides: dict | None = None,
             force: bool = False) -> tuple[str, int, int, int, list]:
    """Write field values into a copy (original file never modified).

    overrides: {field_id: "H42"} manual cell mapping (validated, wins).
    force: overwrite plain values (formulas are STILL never touched).
    Only rows with include != False are written (unticked stay out).
    Returns (out, written, overwritten, skipped, unmapped_ids).
    """
    import openpyxl
    ov = {(k or ""): (v or "").strip().upper()
          for k, v in (overrides or {}).items() if valid_sel(v)}
    cellmap = build_map(template, sheet)

    wb = openpyxl.load_workbook(template)
    try:
        ws = wb[sheet]
        written = overwritten = skipped = 0
        unmapped = []
        for f in fields:
            if f.get("include") is False:
                skipped += 1  # unticked rows stay out of the workbook
                continue
            v = f.get("value")
            if v in (None, "") or f.get("missing"):
                skipped += 1
                continue
            if f.get("source") == "Tidak ditanda":
                skipped += 1  # legacy unticked marker
                continue
            key = _canon_worker_fid(f["id"])
            dest = cellmap.get(f["id"]) or cellmap.get(key)
            coord = ov.get(f["id"]) or ov.get(key)
            if coord:
                dest = (sheet, coord)
            if not dest:
                skipped += 1
                unmapped.append(f["id"])
                continue
            _, coord = dest
            c = ws[coord]
            if c.data_type == "f":
                skipped += 1  # formulas sacred, even in force mode
                continue
            if c.value not in (None, "") and not force:
                skipped += 1  # never overwrite real data (incl. 0)
                continue
            if c.value not in (None, "") and force:
                overwritten += 1
            else:
                written += 1
            c.value = v
        wb.save(out)
    finally:
        wb.close()
    return str(out), written, overwritten, skipped, unmapped


def _ov_path() -> Path:
    from pathlib import Path as _P
    return _P(__file__).resolve().parent.parent / "config" \
        / "cell_overrides.json"


def load_overrides(template_name: str = "") -> dict:
    """{field_id: cell} for one template file (fail-soft: {})."""
    import json
    try:
        p = _ov_path()
        if p.exists():
            all_ov = json.loads(p.read_text(encoding="utf-8"))
            return dict(all_ov.get(template_name or "", {}))
    except Exception:
        pass
    return {}


def save_overrides(template_name: str, ov: dict) -> None:
    """Persist manual cell mapping per template file."""
    import json
    p = _ov_path()
    try:
        all_ov = json.loads(p.read_text(encoding="utf-8")) \
            if p.exists() else {}
    except Exception:
        all_ov = {}
    all_ov[template_name or ""] = {k: v for k, v in ov.items()
                                   if valid_sel(v)}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(all_ov, indent=2, ensure_ascii=False),
                 encoding="utf-8")
