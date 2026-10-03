"""KP205 TXT report writer (TXT report only — no xlsx)."""
from __future__ import annotations
from pathlib import Path
from datetime import date
import re # Import re for regex matching

def _fmt(v):
    if v is None or v == "":
        return "(kosong)"
    return str(v)

def tulis_laporan(fields: list[dict], meta: dict, dossier: dict,
                  nota_ai: str, path: str | Path) -> str:
    nama = meta.get("company") or "(tidak dinyatakan)"
    L = [f"=== LAPORAN KP205: {nama} ===",
         f"Tarikh: {date.today()} | Fail sumber: {meta.get('fail', '-')}",
         f"SSM: {meta.get('ssm','-')} | MSIC: {meta.get('msic','-')}",
         f"Aktiviti: {meta.get('aktiviti','-')}",
         f"Responden: {meta.get('responden','-')} | Mula: {meta.get('tahun_mula','-')}",
         "",
         f"--- DOSIER SYARIKAT (carian web percuma) ---",
         f"STATUS: {dossier.get('status','?')}",
         f"Sebab: {dossier.get('sebab','-')}",
         f"No. SSM ditemui: {', '.join(dossier.get('no_ssm', [])) or '(tiada)'}"]
    hasil = dossier.get("hasil", []) or []
    L.append(f"Bukti internet ({len(hasil)}):")
    if not hasil:
        L.append("(tiada hasil — semak ejaan atau sambungan)")
    for i, h in enumerate(hasil[:12], 1):
        L.append(f"[{i}] {h.get('tajuk','')}")
        L.append(f"    {h.get('url','')}")
        if h.get("petikan"):
            L.append(f"    » {h['petikan'][:240]}")
    L += ["",
          "--- ANGGARAN AI ---",
          (nota_ai or "-"),
          ""]
    berisi = sum(1 for f in fields if not f.get("missing"))
    jumlah = len(fields)
    pct = round(100 * berisi / jumlah) if jumlah else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    L.append(f"Lengkap: {berisi}/{jumlah} [{bar}] {pct}%")
    L.append("")
    last_sec = None
    for f in fields:
        if f["section"] != last_sec:
            L.append(f"##### {f['section']} #####")
            last_sec = f["section"]
        v = _fmt(f.get("value"))
        L.append(f"- [{f.get('fid', f.get('id', ''))}] {f['label']} = {v}")
        
        # Add estimated range if available
        if f.get("estimated_range"):
            L.append(f"    Julat Anggaran: {f['estimated_range']}")
            
        L.append(f"    id: {f['id']} | sumber: {f.get('source','?')} "
                 f"| keyakinan: {f.get('confidence','?')}"
                 + (f" | nota: {f['note']}" if f.get("note") else ""))
    L += ["",
          "--- AMARAN VALIDASI ---"] + _validasi(fields) + ["",
          "--- NISBAH IO (Input/Output) ---"] + _nisbah_io(fields) + ["",
          "--- SEMAKAN SILANG (antara seksyen) ---"] + _semakan(fields, meta) + ["", "=== TAMAT ==="]
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return str(p)

def _validasi(fields: list[dict]) -> list[str]:
    W = []

    def val(fid_part):
        for f in fields:
            if fid_part in f["id"] and f.get("value") not in (None, ""):
                try:
                    # Attempt to parse as float, handle ranges like "15000-16000"
                    value_str = str(f["value"]).replace(",", "")
                    if '-' in value_str:
                        # Use the lower bound of the range for calculations
                        return float(value_str.split('-')[0])
                    return float(value_str)
                except Exception:
                    return None
        return None

    jpend = val("PENDAPATAN::8.13") or val("PENDAPATAN::8.15") or val("PENDAPATAN::8.1")
    jbel = val("PERBELANJAAN::9.39") or val("PERBELANJAAN::9.44")
    unt = val("PENDAPATAN::Untung::Semasa")
    if jpend is not None and jbel is not None and unt is not None:
        jangka = round(jpend - jbel)
        if abs(jangka - unt) > max(1000, abs(unt) * 0.05):
            W.append(f"Untung Semasa ({unt:g}) ≠ Jualan-Belanja ({jangka:g}) — semak.")
    if not W:
        W.append("(tiada isu dikesan — semua anggaran dilabel ANGGARAN AI/RENDAH, sahkan sebelum hantar DOSM)")
    missing = [f for f in fields if f.get("missing")]
    if missing:
        W.append(f"{len(missing)} medan masih kosong (tiada anggaran) — lihat senarai (kosong) di atas.")
    return W


# Kod belanja bahagian pekerja: siri 9.36 SAHAJA (gaji, KWSP, PERKESO,
# bonus/pampasan, pengarah, latihan, pakaian, pengangkutan, levi, saham,
# lain). 9.37 (kontraktor bekalkan pekerja) DIKECUALIKAN — ia bayaran
# kontraktor, bukan belanja pekerja langsung.
PEKERJA_CODES = ["9.36(a)", "9.36(b)", "9.36(c)(i)", "9.36(c)(ii)",
                 "9.36(d)(i)", "9.36(d)(ii)", "9.36(d)(iii)",
                 "9.36(d)(iv)", "9.36(d)(v)", "9.36(e)", "9.36(f)",
                 "9.36(g)", "9.36(h)", "9.36(i)", "9.36(j)", "9.36(k)"]
# Kod teras (wajib ada nilai); kod minor yang kosong diandaikan 0
# dan didedahkan — supaya satu sel kosong tidak membatalkan seluruh IO.
CORE_CODES = {"9.36(a)", "9.36(d)(i)", "9.36(d)(iii)"}


def _semakan(fields: list[dict], meta: dict) -> list[str]:
    from kp205.semakan import semak
    return semak(fields, meta.get("profil", "perkhidmatan"))


def _nisbah_io(fields: list[dict]) -> list[str]:
    """IO = (Belanja − Susut − Belanja Pekerja) / Pendapatan."""
    def get(fid: str):
        for f in fields:
            if f["id"] == fid and f.get("value") not in (None, ""):
                try:
                    return float(str(f["value"]).replace(",", ""))
                except (ValueError, TypeError):
                    return None
        return None

    PB, PP = "PERBELANJAAN", "PENDAPATAN"
    belanja = get(f"{PB}::9.39") or get(f"{PB}::9.44")
    hasil = get(f"{PP}::8.13") or get(f"{PP}::8.15")
    susut = get(f"{PB}::9.29")
    kosong = []
    if belanja is None:
        kosong.append("9.39/9.44 Jumlah belanja")
    if hasil is None:
        kosong.append("8.13/8.15 Jumlah pendapatan")
    if susut is None:
        kosong.append("9.29 Susut nilai")
    pek_vals = {}
    andaian_sifar = []
    for c in PEKERJA_CODES:
        v = get(f"{PB}::{c}")
        if v is None:
            if c in CORE_CODES:
                kosong.append(c + " (teras)")
            else:
                andaian_sifar.append(c)
        else:
            pek_vals[c] = v
    if kosong:
        return ["(tidak dapat dikira — medan kosong: "
                + ", ".join(kosong[:8])
                + (" ..." if len(kosong) > 8 else "") + ")"]
    pek = sum(pek_vals.values())
    if not hasil:
        return ["(tidak dapat dikira — pendapatan sifar/kosong)"]
    io = (belanja - susut - pek) / hasil
    L = [f"Formula: (Belanja − Susut − Belanja Pekerja) / Pendapatan",
         f"= ({belanja:g} − {susut:g} − {pek:g}) / {hasil:g}",
         f"IO = {io:.4f}",
         f"  Belanja pekerja = RM{pek:g} "
         f"({100 * pek / belanja:.1f}% daripada belanja)"]
    if andaian_sifar:
        L.append(f"  Diandaikan RM0 (tiada data): {', '.join(andaian_sifar)}")
    if io < 0.6:
        tafsir = ("BERMASALAH (bawah julat sihat 0.6–0.9) — kos input terlalu "
                  "rendah vs hasil: semak belanja kurang lapor / data tidak lengkap")
    elif io <= 0.9:
        tafsir = "SIHAT (dalam julat 0.6–0.9)"
    else:
        tafsir = ("BERMASALAH (atas julat sihat 0.6–0.9) — kos hampir/melebihi "
                  "hasil: semak kecekapan operasi & ketepatan data")
    L.append(f"Tafsiran: {tafsir}")
    return L
