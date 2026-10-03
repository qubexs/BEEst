"""Fill an xlsx template preserving all styles/formulas.

Only overwrites cell *values* for approved fields. NEVER overwrites a formula
cell (skipped + counted). Nothing else is touched.
"""
from __future__ import annotations
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
import re

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_\-.\s/]+?)\s*\}\}")


def fill_template(template_path: str, output_path: str,
                  values_by_cell: dict[tuple[str, str], object]) -> tuple[str, int]:
    """values_by_cell: {(sheet, cell_coord): final_value}.

    Pulangan / Returns: (output_path, skipped_formulas).
    """
    skipped = 0
    wb = load_workbook(template_path)
    try:
        for ws in wb.worksheets:
            # peta sel gabungan -> sel kiri-atas (boleh tulis)
            gabung = {}
            try:
                for mr in ws.merged_cells.ranges:
                    tl = (mr.min_row, mr.min_col)
                    for rr in range(mr.min_row, mr.max_row + 1):
                        for cc in range(mr.min_col, mr.max_col + 1):
                            gabung[(rr, cc)] = tl
            except Exception:
                pass
            for (sheet, coord), val in values_by_cell.items():
                if sheet != ws.title:
                    continue
                try:
                    c = ws[coord]
                except Exception:
                    skipped += 1
                    continue
                if isinstance(c, MergedCell):
                    tl = gabung.get((c.row, c.column))
                    if tl is None:
                        skipped += 1
                        continue
                    c = ws.cell(row=tl[0], column=tl[1])
                if c.data_type == "f":
                    skipped += 1  # jangan sentuh formula / never touch formulas
                    continue
                old = c.value
                if isinstance(old, str) and "{{" in old:
                    def repl(m):
                        return str(val)
                    new_val = PLACEHOLDER_RE.sub(repl, old)
                    if old.strip().startswith("{{") and old.strip().endswith("}}"):
                        new_val = val
                    c.value = new_val
                else:
                    c.value = val
        wb.save(output_path)
    finally:
        wb.close()
    return output_path, skipped
