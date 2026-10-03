"""Parser for KP205 plain-text dump (e.g. SZK KENANGA VENTURES sample).

Input: .txt file — tab/space separated dump, NOT xlsx.
Output: (fields, meta) where fields = list of dicts:
  {id, section, label, value, raw, missing, source, confidence, note}

Missing rule: raw stripped in ("", "-", "#VALUE!", "NULL", "N/A", ".", "(kosong)")
is missing. Numeric "0" is kept as value 0 (valid for utilities).
Numbers like "880,610", "45,800", "RM 2.28" are parsed to float.
"""
from __future__ import annotations
import re
from pathlib import Path

MISSING_TOKENS = {"", "-", "#VALUE!", "#value!", "#N/A", "NULL", "N/A", ".",
                  "(kosong)", "(tiada)", "--", "–", "—"}

SECTION_META = "META"
SECTION_PEKERJA = "PEKERJA"
SECTION_ASET = "ASET"
SECTION_PENDAPATAN = "PENDAPATAN"
SECTION_BELANJA = "PERBELANJAAN"
SECTION_STOK = "STOK"
SECTION_UTILITI = "UTILITI"
SECTION_BAHAN = "BAHAN"
SECTION_NEGERI = "NEGERI"
SECTION_SHIFT = "SHIFT"
SECTION_PENDIDIKAN = "PENDIDIKAN"

NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")
CODE89_RE = re.compile(r"^(\d+\.\d+[a-z]?(?:\([^)]*\))*(?:\.[a-z])?)\s+(.*)$", re.I)
# e.g. "8.1 Jualan produk...", "9.36(d)(i) KWSP", "9.32(b)(ii) Cukai jalan"


def _clean_num(raw: str):
    """Return (value, is_missing). value = float|int|str|None."""
    if raw is None:
        return None, True
    s = str(raw).strip()
    if s.upper() in MISSING_TOKENS:
        return None, True
    # dates like 1/1/2022, 31/12/2022, 5/5/2023 -> keep as text
    if re.match(r"^\d{1,2}/\d{1,2}/\d{2,4}$", s):
        return s, False
    # text with letters (names, activities, addresses) -> keep full text,
    # do NOT extract embedded numbers like "(3)" or "03-8727"
    if re.search(r"[A-Za-z]", s):
        return (s, False) if re.search(r"[A-Za-z0-9]", s) else (None, True)
    # strip RM / units but keep number
    # e.g. "RM 2.28" -> 2.28 ; "8,092" -> 8092 ; "265" -> 265
    m = NUM_RE.search(s.replace("RM", " "))
    if m is None:
        # non-numeric text: keep as-is if meaningful, else missing
        if len(s) >= 1 and s not in ("0",):
            # text value like "Mr Seng", "03-8727 1359", "Sdn Bhd"
            if re.search(r"[A-Za-z0-9]", s):
                return s, False
        return None, True
    num_s = m.group(0).replace(",", "")
    try:
        v = float(num_s)
        if v.is_integer():
            v = int(v)
        return v, False
    except ValueError:
        return None, True


def _mk(sec, label, raw, fid=None, note=""):
    value, missing = _clean_num(raw)
    return {
        "id": fid or f"{sec}::{label}",
        "section": sec,
        "label": label,
        "value": value,
        "raw": str(raw) if raw is not None else "",
        "missing": missing,
        "source": "FAIL_TXT" if not missing else "—",
        "confidence": "SEDERHANA" if not missing else "RENDAH",
        "note": note,
    }


def _split_cells(line: str) -> list[str]:
    # tabs first, else 2+ spaces
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in re.split(r"\s{2,}|\t", line.strip())]


def parse_kp205_text(text: str) -> tuple[list[dict], dict]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    fields: list[dict] = []
    meta: dict = {"company": "", "ssm": "", "msic": "", "aktiviti": "",
                  "responden": "", "tahun_mula": "", "tahun_kewangan": ""}

    # --- 1. META line scans (regex over whole text) ---
    whole = text
    m = re.search(r"Company\s+([A-Z0-9 .&'\-]+?)(?:\s{2,}|\t|\n)", whole, re.I)
    if m:
        meta["company"] = m.group(1).strip()
    m = re.search(r"SSM\s*:?\s*([A-Z0-9\-/]+|0)", whole, re.I)
    if m:
        meta["ssm"] = m.group(1).strip()
    m = re.search(r"Newss?\s+(\d+)", whole, re.I)
    if m:
        meta["msic"] = m.group(1).strip()
    m = re.search(r"Aktiviti\s+([^\n\t]+)", whole, re.I)
    if m:
        meta["aktiviti"] = m.group(1).strip()[:160]
    m = re.search(r"Responden Name\s+([^\t\n]+?)(?:\t|\s{2,}|$)", whole, re.I)
    if m:
        meta["responden"] = m.group(1).strip()[:80]
    m = re.search(r"Start Year\s+(\d{4})", whole, re.I)
    if m:
        meta["tahun_mula"] = m.group(1)
    m = re.search(r"End Financial\s+([\d/]+)", whole, re.I)
    if m:
        meta["tahun_kewangan"] = m.group(1)

    # META fields (always emitted so AI can verify/fill)
    for k, lab in (("company", "Company / Syarikat"),
                   ("ssm", "SSM No. Pendaftaran"),
                   ("msic", "Kod MSIC (Newss)"),
                   ("aktiviti", "Aktiviti utama"),
                   ("responden", "Nama responden"),
                   ("tahun_mula", "Tahun mula operasi"),
                   ("tahun_kewangan", "Akhir tahun kewangan")):
        raw = meta.get(k, "")
        fields.append(_mk(SECTION_META, lab, raw if raw else "",
                          fid=f"META::{lab}"))

    # extra META: Capital / Reserve / Pemilikan if present
    m = re.search(r"Capital\s+([\d,]+)", whole, re.I)
    fields.append(_mk(SECTION_META, "Modal berbayar (Capital)",
                      m.group(1) if m else ""))
    # Financial Year start
    m = re.search(r"Financial Year\s+([\d/]+)", whole, re.I)
    if m:
        fields.append(_mk(SECTION_META, "Mula tahun kewangan", m.group(1)))

    # --- 2. Line-by-line coded + keyword extraction ---
    ASET_KEYS = ["Tanah", "Kediaman", "Bangunan", "Lain Binaan", "Pembangunan",
                 "Kereta", "Lain Kenderaan", "Lain Pengangkutan", "Komputer",
                 "Perisian", "Komunikasi", "Jentera", "Drone", "Perabut",
                 "Paten", "Muhibah", "Kerja Dlm Perlaksanaan", "Lain-Lain", "Jumlah"]
    STOK_KEYS = ["Bahan Mentah/Bakar", "Barang Dalam Proses", "Stok Barang Siap",
                 "Stok Runcit", "Jumlah"]
    UTIL_KEYS = ["Dibeli", "Diesel", "Petrol", "LPG", "Elektrik", "Air", "Pelincir",
                 "Bahan Bakar"]
    NEGERI = ["Johor", "Kedah", "Kelantan", "Melaka", "Negeri Sembilan", "Pahang",
              "Pulau Pinang", "Perak", "Perlis", "Selangor", "Terengganu", "Sabah",
              "Sarawak", "W.P.Kuala Lumpur", "W.P.Labuan", "W.P.Putrajaya"]

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        # coded 8.x / 9.x rows
        mc = CODE89_RE.match(s)
        if mc and (s.startswith("8.") or s.startswith("9.")):
            code, rest = mc.group(1), mc.group(2)
            # value = last number token on the line (RM amounts)
            cells = _split_cells(s)
            # rest may contain label + value; take last numeric-looking cell
            raw_val = ""
            for c in reversed(cells):
                if NUM_RE.search(c) or c.strip().upper() in MISSING_TOKENS or c.strip() == "-":
                    raw_val = c
                    break
            label_full = f"{code} {rest[:90]}".strip()
            sec = SECTION_PENDAPATAN if code.startswith("8.") else SECTION_BELANJA
            # avoid dupes
            if not any(f["id"] == f"{sec}::{code}" for f in fields):
                f = _mk(sec, label_full, raw_val, fid=f"{sec}::{code}")
                fields.append(f)
            continue
        # asset rows: "Komputer  8,092 ... 1,206  6,886"
        for ak in ASET_KEYS:
            if re.match(rf"^{re.escape(ak)}\b", s, re.I):
                cells = _split_cells(s)
                nums = [c for c in cells[1:] if c != ""]
                # Columns: Awal|Beli baru|Beli Terpakai|Bina|Jual|Susut|Bersih|Sewa
                # 3 nums -> [Awal, Susut, Bersih]; 4 nums -> [Awal, Susut, Bersih, Sewa]
                if len(nums) >= 4:
                    raw_main, raw_sewa = nums[-2], nums[-1]
                elif nums:
                    raw_main, raw_sewa = nums[-1], ""
                else:
                    mnum = NUM_RE.findall(s)
                    raw_main, raw_sewa = (mnum[-1] if mnum else ""), ""
                fid = f"{SECTION_ASET}::{ak}"
                if not any(f["id"] == fid for f in fields):
                    fields.append(_mk(SECTION_ASET, f"Aset {ak} (Bersih)",
                                      raw_main, fid=fid, note=f"Row: {s[:140]}"))
                    if raw_sewa and ak == "Jumlah":
                        fields.append(_mk(SECTION_ASET, "Aset Jumlah (Sewa)",
                                          raw_sewa, fid=f"{SECTION_ASET}::Jumlah_Sewa"))
                break
        # stok rows handled via Awal/Akhir pairs below; skip here
        # Negeri rows
        for ng in NEGERI:
            if re.match(rf"^{re.escape(ng)}\b", s, re.I):
                cells = _split_cells(s)
                nums = [c for c in cells[1:]]
                raw1 = nums[0] if len(nums) > 0 else ""
                raw2 = nums[1] if len(nums) > 1 else ""
                fid1, fid2 = f"{SECTION_NEGERI}::{ng}::BahanMentah", f"{SECTION_NEGERI}::{ng}::Jualan"
                if not any(f["id"] == fid1 for f in fields):
                    fields.append(_mk(SECTION_NEGERI, f"{ng} — Bahan mentah", raw1, fid=fid1))
                    fields.append(_mk(SECTION_NEGERI, f"{ng} — Jualan", raw2, fid=fid2))
                break

    # --- 3. Stocks Awal/Akhir pairs (Bahan Mentah/Bakar 6503 8905 etc.) ---
    for key in STOK_KEYS:
        pat = re.compile(rf"^{re.escape(key)}\s+([#\w.,\-/]+)?\s+([#\w.,\-/]+)?", re.I | re.M)
        mm = pat.search(whole)
        if mm:
            for tag, g in (("Awal", mm.group(1) or ""), ("Akhir", mm.group(2) or "")):
                fid = f"{SECTION_STOK}::{key}::{tag}"
                if not any(f["id"] == fid for f in fields):
                    fields.append(_mk(SECTION_STOK, f"Stok {key} ({tag})", g, fid=fid))

    # --- 4. Profit Semasa/Sebelum ---
    for tag in ("Semasa", "Sebelum"):
        mm = re.search(rf"(?:Profit/Loss|Untung).*?{tag}\s+([\d,\-]+)", whole, re.I | re.S)
        if not mm:
            mm = re.search(rf"^{tag}\s+([\d,\-]+)", whole, re.I | re.M)
        if mm and not any(f["id"] == f"{SECTION_PENDAPATAN}::Untung::{tag}" for f in fields):
            fields.append(_mk(SECTION_PENDAPATAN, f"Untung/Rugi ({tag})",
                              mm.group(1), fid=f"{SECTION_PENDAPATAN}::Untung::{tag}"))

    # --- 5. Employment / Pendidikan / Shift placeholders ---
    # These are mostly #VALUE! in sample — emit labelled missing fields so AI fills all.
    pekerja_labels = [
        "Pekerja Lelaki — Pemilik (Warga/BWN/Gaji)",
        "Pekerja Lelaki — Keluarga", "Pekerja Lelaki — Pengurus",
        "Pekerja Lelaki — Profesional (Pro)", "Pekerja Lelaki — Penyelidik",
        "Pekerja Lelaki — Juruteknik", "Pekerja Lelaki — Kerani",
        "Pekerja Lelaki — Jualan", "Pekerja Lelaki — Mahir berkaitan",
        "Pekerja Lelaki — Operator", "Pekerja Lelaki — Asas",
        "Pekerja Lelaki — Jumlah", "Pekerja Lelaki — Sambilan",
        "Pekerja Perempuan — (sama kategori)",
        "Pekerja — Jumlah besar (Total)",
    ]
    for lab in pekerja_labels:
        fid = f"{SECTION_PEKERJA}::{lab}"
        if not any(f["id"] == fid for f in fields):
            # try find a number near label in text, else missing
            fields.append(_mk(SECTION_PEKERJA, lab, "", fid=fid,
                              note="Asal #VALUE!/kosong — perlu anggaran"))
    for lab in ["Hari beroperasi", "Jam/Shift", "Jumlah Jam", "JAM OT", "Upah OT",
                "Bil Pekerja Shift 1", "Bil Pekerja Shift 2", "Bil Pekerja Shift 3"]:
        fid = f"{SECTION_SHIFT}::{lab}"
        if not any(f["id"] == fid for f in fields):
            mm = re.search(rf"{re.escape(lab)}\s+([\d.,#A-Z\-/]+)", whole, re.I)
            if mm is None and lab == "Hari beroperasi":
                mm = re.search(r"^Hari\s+([\d.,]+)", whole, re.I | re.M)
            if mm is None and lab == "Jam/Shift":
                mm = re.search(r"Jam\s+([\d.,]+)", whole, re.I)
            raw = mm.group(1) if mm else ""
            # Hari 265 / Jam 8 are known
            fields.append(_mk(SECTION_SHIFT, lab, raw, fid=fid))
    for lab in ["Pasca (L/P)", "Deg A (L/P)", "Deg T (L/P)", "Dip A (L/P)",
                "Dip TVet (L/P)", "STPM (L/P)", "Cert A (L/P)", "TVET (L/P)",
                "SPM (L/P)", "Under SPM (L/P)"]:
        fid = f"{SECTION_PENDIDIKAN}::{lab}"
        if not any(f["id"] == fid for f in fields):
            fields.append(_mk(SECTION_PENDIDIKAN, f"Pendidikan {lab}", "", fid=fid,
                              note="Asal #VALUE! — perlu anggaran"))

    # --- 6. Bahan mentah utama (Iron Tan 500 292209 Kapasiti 75) ---
    mm = re.search(r"Iron\s+Tan\s+(\d+)\s+([\d,]+)\s+(\d+)?", whole, re.I)
    if mm:
        fields.append(_mk(SECTION_BAHAN, "Bahan Iron — Unit Guna",
                          mm.group(1), fid=f"{SECTION_BAHAN}::Iron::Unit"))
        fields.append(_mk(SECTION_BAHAN, "Bahan Iron — RM",
                          mm.group(2), fid=f"{SECTION_BAHAN}::Iron::RM"))
        if mm.group(3):
            fields.append(_mk(SECTION_BAHAN, "Kapasiti (%)",
                              mm.group(3), fid=f"{SECTION_BAHAN}::Kapasiti"))

    # dedupe keep order
    seen, out = set(), []
    for f in fields:
        if f["id"] not in seen:
            seen.add(f["id"])
            out.append(f)
    return out, meta


def parse_kp205_file(path: str | Path) -> tuple[list[dict], dict]:
    p = Path(path)
    if not p.exists():
        hint = ""
        try:
            root = Path(__file__).resolve().parent.parent
            cands = sorted(root.glob("tests/fixtures/*.txt"))
            if cands:
                hint = (" Contoh tersedia: "
                        + ", ".join(str(c.relative_to(root)) for c in cands[:5]))
        except Exception:
            pass
        raise FileNotFoundError(
            f"Fail input tidak ditemui: {path}."
            f" Semak laluan (seret fail ke terminal untuk path penuh).{hint}")
    text = p.read_text(encoding="utf-8", errors="replace")
    fields, meta = parse_kp205_text(text)
    meta["fail"] = str(p)
    return fields, meta
