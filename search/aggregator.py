"""Gabung sumber dalam talian + anggaran menjadi baris preview.

Setiap PreviewRow ada: cadangan utama (propusa) vs pilihan kedua (alternatif/anggaran),
supaya UI boleh papar 'setuju atau guna anggaran lain'.
"""
from __future__ import annotations
from dataclasses import dataclass
import yaml
from pathlib import Path

from .sources import fetch_anaf, fetch_bnr_rates, fetch_bnm_rates, clean_cui
from activity import emit, Stopped

CONF_HIGH, CONF_MED, CONF_LOW = "TINGGI", "SEDARHANA", "RENDAH"

# Kod mata wang untuk padanan generik ".../MYR" (BNM bawa 27 mata wang).
FX_CODES = ("USD", "EUR", "GBP", "SGD", "JPY", "CNY", "AUD", "THB", "IDR", "INR",
            "HKD", "KRW", "TWD", "PHP", "VND", "CHF", "CAD", "BND", "KHR", "MMK",
            "NPR", "PKR", "LKR", "SAR", "AED", "QAR", "BDT", "SDR")


@dataclass
class PreviewRow:
    label: str
    sheet: str
    cell: str
    proposed: object = ""
    proposed_source: str = "—"
    confidence: str = CONF_LOW
    alternate: object = ""
    alternate_source: str = "—"
    include: bool = True
    note: str = ""


def _load_estimates() -> dict:
    cfg = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"
    try:
        return (yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}).get("estimates", {})
    except Exception:
        return {}


def _norm(s: str) -> str:
    import unicodedata
    s = (s or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def aggregate(cui_raw: str, template_fields: list, year: int = 2026,
              stop=None) -> tuple[list[PreviewRow], dict]:
    """Jalankan semua carian dalam talian, padankan ke label templat.

    stop: threading.Event pilihan — semak antara setiap peringkat; bangkit
    Stopped jika pengguna tekan Berhenti.
    """
    log: dict = {"steps": []}
    emit("INFO", f"Agregat: {len(template_fields)} medan, CUI={cui_raw or '(kosong)'}, tahun={year}.")
    cui = clean_cui(cui_raw)
    anaf, anaf_note = fetch_anaf(cui, year) if cui else (None, "CUI tiada - hanya anggaran/BNR")
    log["steps"].append(anaf_note)
    if stop is not None and stop.is_set():
        emit("WARN", "Agregat dihentikan selepas ANAF.")
        raise Stopped()
    bnr, bnr_note = fetch_bnr_rates()
    log["steps"].append(bnr_note)
    if stop is not None and stop.is_set():
        emit("WARN", "Agregat dihentikan selepas BNR.")
        raise Stopped()
    bnm, bnm_note = fetch_bnm_rates()
    log["steps"].append(bnm_note)
    if stop is not None and stop.is_set():
        emit("WARN", "Agregat dihentikan selepas BNM.")
        raise Stopped()
    est = _load_estimates()
    log["anaf"] = anaf or {}
    log["fx"] = bnr or {}
    log["fx_myr"] = bnm or {}

    rows: list[PreviewRow] = []
    for f in template_fields:
        lab = f.label
        n = _norm(lab)
        row = PreviewRow(label=lab, sheet=f.sheet, cell=f.cell)
        # --- identiti syarikat dari ANAF ---
        if any(k in n for k in ("denumire", "nume firma", "societate", "company",
                                "nama syarikat", "nama firma", "syarikat")):
            row.proposed = (anaf or {}).get("denumire", "") or ""
            row.proposed_source = "ANAF" if row.proposed else "—"
            row.confidence = CONF_HIGH if row.proposed else CONF_LOW
            row.alternate, row.alternate_source = cui_raw, "Input pengguna"
        elif "cui" in n or "cod fiscal" in n or "kod fiskal" in n or ("cod" in n and "fiscal" in n):
            row.proposed = cui or cui_raw
            row.proposed_source = "Input pengguna"
            row.confidence = CONF_HIGH
            row.alternate, row.alternate_source = "RO" + cui if cui else "", "Format RO"
        elif any(k in n for k in ("adresa", "sediu", "domiciliu", "alamat", "lokasi")):
            row.proposed = (anaf or {}).get("adresa", "") or ""
            row.proposed_source = "ANAF" if row.proposed else "—"
            row.confidence = CONF_HIGH if row.proposed else CONF_LOW
            row.alternate, row.alternate_source = "", "Manual"
        elif any(k in n for k in ("reg com", "nr. reg", "j0", "j12", "j40", "registrul",
                                  "no. daftar", "pendaftaran")):
            row.proposed = (anaf or {}).get("nrRegCom", "") or ""
            row.proposed_source = "ANAF" if row.proposed else "—"
            row.confidence = CONF_HIGH if row.proposed else CONF_LOW
            row.alternate, row.alternate_source = "", "Manual"
        elif "caen" in n:
            row.proposed = (anaf or {}).get("cod_CAEN", "") or ""
            row.proposed_source = "ANAF" if row.proposed else "—"
            row.confidence = CONF_HIGH if row.proposed else CONF_LOW
            row.alternate, row.alternate_source = "", "Manual"
        elif "telefon" in n or "no. tel" in n or n.strip() in ("tel", "phone", "no telefon"):
            row.proposed = (anaf or {}).get("telefon", "") or ""
            row.proposed_source = "ANAF" if row.proposed else "—"
            row.confidence = CONF_MED if row.proposed else CONF_LOW
            row.alternate, row.alternate_source = "", "Manual"
        elif "an" in n and ("fiscal" in n or "raport" in n or "anul" in n) or lab.strip() == "An":
            row.proposed = year
            row.proposed_source = "Aplikasi"
            row.confidence = CONF_HIGH
            row.alternate, row.alternate_source = year, "Aplikasi"
        # --- BNR FX ---
        elif "eur" in n and ("ron" in n or "curs" in n or "leu" in n or "lei" in n or "kurs" in n):
            live = (bnr or {}).get("EUR")
            src = (bnr or {}).get("_src", "BNR")
            row.proposed = live if live else est.get("curs_eur_mediu_2026", 5.05)
            row.proposed_source = f"{src} {(bnr or {}).get('_date', '')}".strip() if live else "ANGGARAN"
            row.confidence = CONF_HIGH if live else CONF_LOW
            row.alternate = est.get("curs_eur_mediu_2026", 5.05)
            row.alternate_source = "ANGGARAN purata 2026"
        elif "usd" in n and ("ron" in n or "curs" in n or "dolar" in n or "kurs" in n):
            live = (bnr or {}).get("USD")
            src = (bnr or {}).get("_src", "BNR")
            row.proposed = live if live else est.get("curs_usd_mediu_2026", 4.65)
            row.proposed_source = f"{src} {(bnr or {}).get('_date', '')}".strip() if live else "ANGGARAN"
            row.confidence = CONF_HIGH if live else CONF_LOW
            row.alternate = est.get("curs_usd_mediu_2026", 4.65)
            row.alternate_source = "ANGGARAN purata 2026"
        elif "gbp" in n or ("lira" in n and "curs" in n):
            live = (bnr or {}).get("GBP")
            src = (bnr or {}).get("_src", "BNR")
            row.proposed = live if live else ""
            row.proposed_source = f"{src} {(bnr or {}).get('_date', '')}".strip() if live else "—"
            row.confidence = CONF_HIGH if live else CONF_LOW
            row.alternate, row.alternate_source = "", "Manual"
        # --- BNM: kadar vs RM (borang Melayu: tukaran/pertukaran/mata wang/RM) ---
        elif ("myr" in n or "ringgit" in n or "tukaran" in n or "pertukaran" in n
                or "mata wang" in n or "tukar" in n or "rm" in n.split()):
            kod = next((k for k in FX_CODES if k.lower() in n), "")
            if kod and (bnm or {}).get(kod):
                live = bnm[kod]
                src = bnm.get("_src", "BNM")
                row.proposed = live
                row.proposed_source = f"{src} {bnm.get('_date', '')}".strip()
                row.confidence = CONF_HIGH
                row.alternate = est.get("curs_usd_mediu_2026", 4.65) if kod == "USD" else ""
                row.alternate_source = "ANGGARAN purata 2026" if kod == "USD" else "—"
                row.note = f"Kadar rasmi {kod}/MYR."
            elif "opr" in n and (bnm or {}).get("_opr"):
                row.proposed = bnm["_opr"]
                row.proposed_source = f"{bnm.get('_src', 'BNM')}"
                row.confidence = CONF_HIGH
                row.alternate, row.alternate_source = "", "Manual"
            else:
                row.proposed = ""
                row.proposed_source = "— (isi manual / AI)"
                row.confidence = CONF_LOW
                row.alternate, row.alternate_source = "", "Manual"
                row.note = "Kadar mata wang tidak dipadan — semak kod (USD/EUR/SGD…)."
        elif "opr" in n and (bnm or {}).get("_opr"):
            row.proposed = bnm["_opr"]
            row.proposed_source = bnm.get("_src", "BNM")
            row.confidence = CONF_HIGH
            row.alternate, row.alternate_source = "", "Manual"
        # --- INSSE / anggaran makro ---
        elif "inflatie" in n or "ipc" in n or "preturilor" in n or "inflasi" in n:
            row.proposed = est.get("inflatie_2026", 5.1)
            row.proposed_source = "ANGGARAN INSSE"
            row.confidence = CONF_LOW
            row.alternate, row.alternate_source = "", "Manual (semak insse.ro)"
            row.note = "Sahkan nilai IPC terkini di insse.ro"
        elif "pib" in n or "kdnk" in n:
            row.proposed = est.get("pib_crestere_2026", 1.4)
            row.proposed_source = "ANGGARAN"
            row.confidence = CONF_LOW
            row.alternate, row.alternate_source = "", "Manual"
        else:
            # generik: kekalkan nilai sedia ada templat, selebihnya manual/AI
            row.proposed = f.current if f.current not in (None, "") else ""
            row.proposed_source = "Templat sedia ada" if row.proposed != "" else "— (isi manual / AI)"
            row.confidence = CONF_MED if row.proposed != "" else CONF_LOW
            row.alternate, row.alternate_source = "", "Manual"
            row.note = "Medan tidak ditemui dalam talian - putuskan secara manual atau guna AI"
        rows.append(row)
    log["anaf_found"] = bool(anaf)
    log["bnr_found"] = bool(bnr)
    ada = sum(1 for r in rows if r.proposed not in (None, ""))
    emit("OK", f"Agregat siap: {ada}/{len(rows)} medan ada nilai cadangan.")
    return rows, log
