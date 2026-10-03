"""Parse a generated x205.txt report back into structured data for the GUI viewer."""
from __future__ import annotations
import re
from pathlib import Path


def parse_laporan(path: str | Path) -> dict:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    d: dict = {
        "tajuk": "", "syarikat": "", "tarikh": "", "ssm": "",
        "status": "", "sebab": "", "bukti": 0,
        "berisi": 0, "jumlah": 0, "pct": 0,
        "fields": [], "warnings": [], "nota_ai": "",
        "io_lines": [], "io_val": "", "io_tafsir": "",
        "semakan": [],
    }
    m = re.search(r"===\s*LAPORAN KP205:\s*(.*?)\s*===", text)
    if m:
        d["tajuk"] = m.group(0)
        d["syarikat"] = m.group(1).strip()
    m = re.search(r"^Tarikh:\s*(.*?)(?:\s*\|\s*Fail sumber:.*)?$", text, re.M)
    if m:
        d["tarikh"] = m.group(1).strip()
    m = re.search(r"^SSM:\s*(.*?)\s*\|\s*MSIC:\s*(.*?)\s*$", text, re.M)
    if m:
        d["ssm"] = m.group(1).strip()
    m = re.search(r"^STATUS:\s*(.*?)\s*$", text, re.M)
    if m:
        d["status"] = m.group(1).strip()
    m = re.search(r"^Sebab:\s*(.*?)\s*$", text, re.M)
    if m:
        d["sebab"] = m.group(1).strip()
    m = re.search(r"^Bukti internet \((\d+)\):", text, re.M)
    if m:
        d["bukti"] = int(m.group(1))
    m = re.search(r"^Lengkap:\s*(\d+)/(\d+).*?(\d+)%", text, re.M)
    if m:
        d["berisi"], d["jumlah"], d["pct"] = int(m.group(1)), int(m.group(2)), int(m.group(3))

    # AI note: lines between "--- ANGGARAN AI ---" and blank line
    m = re.search(r"--- ANGGARAN AI ---\n(.*?)\n\n", text, re.S)
    if m:
        d["nota_ai"] = m.group(1).strip()

    sec, i = "?", 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        mh = re.match(r"^#####\s*(.*?)\s*#####$", ln)
        if mh:
            sec = mh.group(1).strip()
            i += 1
            continue
        mf = re.match(r"^-\s*(.*?)\s*=\s*(.*?)\s*$", ln)
        if mf and sec != "?":
            label, val = mf.group(1).strip(), mf.group(2).strip()
            label = re.sub(r"^\[.*?\]\s*", "", label)  # strip "- [fid]" prefix
            src, conf, note, fid = "?", "?", "", ""
            if i + 1 < n and lines[i + 1].strip().startswith("id:"):
                det = lines[i + 1].strip()
                f0 = re.search(r"^id:\s*(.*?)\s*\|\s*sumber:", det)
                if f0:
                    fid = f0.group(1).strip()
                ms = re.search(r"sumber:\s*(.*?)\s*\|\s*keyakinan:", det)
                if ms:
                    src = ms.group(1).strip()
                mc = re.search(r"keyakinan:\s*(.*?)(?:\s*\|\s*nota:|$)", det)
                if mc:
                    conf = mc.group(1).strip()
                mn = re.search(r"\|\s*nota:\s*(.*)$", det)
                if mn:
                    note = mn.group(1).strip()
                i += 1
            missing = (val == "(kosong)")
            d["fields"].append({
                "section": sec, "label": label,
                "value": ("" if missing else val), "missing": missing,
                "source": src, "confidence": conf, "note": note, "fid": fid,
            })
            i += 1
            continue
        i += 1
    if not d["jumlah"]:
        d["jumlah"] = len(d["fields"])
        d["berisi"] = sum(1 for f in d["fields"] if not f["missing"])
        d["pct"] = round(100 * d["berisi"] / d["jumlah"]) if d["jumlah"] else 0

    m = re.search(r"--- AMARAN VALIDASI ---\n(.*?)\n\n===", text, re.S)
    if m:
        d["warnings"] = [w.strip() for w in m.group(1).strip().splitlines()
                         if w.strip()]

    m = re.search(r"--- NISBAH IO.*?---\n(.*?)(?:\n\n=== |\n===)", text, re.S)
    if m:
        d["io_lines"] = [w.strip() for w in m.group(1).strip().splitlines()
                         if w.strip()]
        for ln in d["io_lines"]:
            mi = re.match(r"^IO\s*=\s*([\d.]+)", ln)
            if mi:
                d["io_val"] = mi.group(1)
            mt = re.match(r"^Tafsiran:\s*(.*)", ln)
            if mt:
                d["io_tafsir"] = mt.group(1).strip()

    m = re.search(r"--- SEMAKAN SILANG.*?---\n(.*?)(?:\n\n=== |\n===)", text, re.S)
    if m:
        d["semakan"] = [w.strip() for w in m.group(1).strip().splitlines()
                        if w.strip()]
    return d
