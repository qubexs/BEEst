"""Canonical blank KP205 field template (no input file needed).

blank_kp205_fields(company, year) -> (fields, meta): every value empty/missing,
same id scheme as parser_txt so reports stay consistent.
SSM/MSIC are flagged manual-only (never sent to AI for guessing).
"""
from __future__ import annotations

from kp205.parser_txt import (
    _mk, SECTION_META, SECTION_PEKERJA, SECTION_ASET, SECTION_PENDAPATAN,
    SECTION_BELANJA, SECTION_STOK, SECTION_BAHAN, SECTION_NEGERI,
    SECTION_SHIFT, SECTION_PENDIDIKAN,
)

MANUAL_ONLY = {"META::SSM No. Pendaftaran", "META::Kod MSIC (Newss)",
               "META::Alamat berdaftar", "META::Company / Syarikat"}

PENDAPATAN = [
    ("8.1", "Jualan produk buat/proses/pasang"),
    ("8.1.1", "(%) eksport nilai jualan"),
    ("8.1.2", "(%) eksport produk halal"),
    ("8.2.1", "Bayaran kerja memproses"),
    ("8.2.2", "(%) Diterima dari luar negara (memproses)"),
    ("8.2.3", "Kerja membaiki dan menyelenggara"),
    ("8.2.4", "(%) Diterima dari luar negara (membaiki)"),
    ("8.3", "Nilai jualan (runcit)"),
    ("8.4", "Nilai kerja perindustrian lain"),
    ("8.5", "Pendapatan output lain t.t.t.l"),
    ("8.6", "Perkhidmatan profesional"),
    ("8.7", "Komisen dan brokeraj"),
    ("8.8(a)", "Sewa Tanah"),
    ("8.8(b)", "Sewa tempat kediaman"),
    ("8.8(c)", "Sewa BTK"),
    ("8.8(d)", "Sewa Alat pengangkutan"),
    ("8.8(e)", "Sewa Jentera dan kelengkapan"),
    ("8.8(f)", "Sewa Perabot dan pemasangan"),
    ("8.8(g)", "Sewa Lain-lain"),
    ("8.9", "Royalti, hakcipta"),
    ("8.10(a)", "Subsidi produk"),
    ("8.10(b)", "Subsidi pengeluaran"),
    ("8.10(c)", "Tuntutan dan pampasan"),
    ("8.10(d)", "Pemulihan hutang lapuk"),
    ("8.10(e)", "Faedah"),
    ("8.10(f)", "Dividen"),
    ("8.10(g)", "Jualan / penilaian harta"),
    ("8.10(h)", "Keuntungan Tukaran wang asing"),
    ("8.10(i)", "Kiriman wang, hadiah atau geran"),
    ("8.10(j)", "Lain2 pendapatan bkn operasi"),
    ("8.11", "e-sukan"),
    ("8.12", "Lain2 pendapatan operasi"),
    ("8.13", "Jumlah pendapatan"),
    ("8.14", "Pindahan modal"),
    ("8.15", "JUMLAH BESAR"),
]

BELANJA = [
    ("9.1", "Kos bahan mentah / komponen"),
    ("9.2", "Bahan dan bekas pembungkus"),
    ("9.3", "Bahan pembaikan/penyelenggaraan"),
    ("9.4", "Keperluan kilang"),
    ("9.5", "Alat tulis dan bekalan pejabat"),
    ("9.6", "Air yang dibeli"),
    ("9.7", "Tenaga elektrik"),
    ("9.8", "Bahan pembakar, pelincir dan gas"),
    ("9.9", "Kos barang yang dijual (runcit)"),
    ("9.10", "Bayaran kerja memproses"),
    ("9.11", "Bayaran pembaikan/penyelenggaraan"),
    ("9.12", "Perbelanjaan penyelidikan dan pembangunan"),
    ("9.12(a)", "(%) Dalaman / In-house"),
    ("9.12(b)", "(%) Sumber luaran / Outsource"),
    ("9.13", "Pengangkutan barang"),
    ("9.14", "Perbelanjaan perjalanan"),
    ("9.15", "Perakaunan, kesetiausahaan/audit"),
    ("9.16", "Bayaran guaman"),
    ("9.17", "Bayaran pengurusan"),
    ("9.18", "Perbelanjaan keraian"),
    ("9.19", "Bayaran pos"),
    ("9.20", "Bayaran bank"),
    ("9.21", "Premium insurans"),
    ("9.22", "Komisen dan bayaran agensi"),
    ("9.23", "Pengiklanan dan promosi"),
    ("9.24", "Perkhidmatan profesional lain"),
    ("9.25", "Bayaran pemprosesan data dan IT"),
    ("9.26", "Bayaran telekomunikasi"),
    ("9.27", "Lain2 bayaran perkhidmatan"),
    ("9.28(a)", "Sewaan Tanah"),
    ("9.28(b)", "Sewaan operasi"),
    ("9.29", "Susut nilai"),
    ("9.30", "Bayaran faedah"),
    ("9.31(a)", "Royalti Kerajaan / Badan Berkanun"),
    ("9.31(b)", "Bukan kerajaan / tajaan korporat"),
    ("9.32(a)(i)", "Cukai eksais produk"),
    ("9.32(a)(ii)", "Cukai eksport"),
    ("9.32(b)(i)", "Taksiran bangunan dan cukai tanah"),
    ("9.32(b)(ii)", "Cukai jalan"),
    ("9.32(b)(iii)", "Pendaftaran perniagaan, lesen memandu"),
    ("9.32(c)", "Cukai perkhidmatan atau cukai jualan"),
    ("9.33(a)", "Kerugian pertukaran wang asing"),
    ("9.33(b)", "Kerugian jualan / penilaian harta"),
    ("9.33(c)", "Hutang lapuk dihapuskan"),
    ("9.33(d)", "Hadiah, derma, denda, dsb."),
    ("9.33(e)", "Lain2 perbelanjaan bkn operasi"),
    ("9.34.1", "e-sukan"),
    ("9.35", "Lain2 perbelanjaan operasi"),
    ("9.36(a)", "Gaji & upah dibayar"),
    ("9.36(b)", "Pampasan, persaraan"),
    ("9.36(c)(i)", "Rawatan perubatan"),
    ("9.36(c)(ii)", "Makanan, tempat tinggal dsb"),
    ("9.36(d)(i)", "KWSP"),
    ("9.36(d)(ii)", "Kumpulan wang simpanan lain"),
    ("9.36(d)(iii)", "PERKESO"),
    ("9.36(d)(iv)", "Skim keselamatan sosial persendirian"),
    ("9.36(d)(v)", "Skim pampasan, persaraan / pemberhentian"),
    ("9.36(e)", "Bayaran kepada pengarah"),
    ("9.36(f)", "Pakaian percuma"),
    ("9.36(g)", "Kos latihan"),
    ("9.36(h)", "Kos pengangkutan pekerja"),
    ("9.36(i)", "Bayaran levi pekerja"),
    ("9.36(j)", "Perbelanjaan saham kpd pekerja"),
    ("9.36(k)", "Kos pekerja lain"),
    ("9.37", "Bayaran kontraktor bekalkan pekerja"),
    ("9.38", "Bayaran bagi perkhidmatan keselamatan"),
    ("9.39", "Jumlah perbelanjaan"),
    ("9.40", "Pindahan modal"),
    ("9.41", "Perbelanjaan pajakan kewangan"),
    ("9.42", "Dividen dibayar"),
    ("9.43", "Cukai langsung dibayar"),
    ("9.44", "JUMLAH BESAR"),
]

ASET = ["Tanah", "Kediaman", "Bangunan", "Lain Binaan", "Pembangunan",
        "Kereta", "Lain Kenderaan", "Lain Pengangkutan", "Komputer",
        "Perisian", "Komunikasi", "Jentera", "Drone", "Perabut",
        "Paten", "Muhibah", "Kerja Dlm Perlaksanaan", "Lain-Lain", "Jumlah"]

STOK = ["Bahan Mentah/Bakar", "Barang Dalam Proses", "Stok Barang Siap",
        "Stok Runcit", "Jumlah"]

NEGERI = ["Johor", "Kedah", "Kelantan", "Melaka", "Negeri Sembilan", "Pahang",
          "Pulau Pinang", "Perak", "Perlis", "Selangor", "Terengganu", "Sabah",
          "Sarawak", "W.P.Kuala Lumpur", "W.P.Labuan", "W.P.Putrajaya"]

PEKERJA = ["Pemilik", "Keluarga", "Pengurus", "Profesional (Pro)",
           "Penyelidik", "Juruteknik", "Kerani", "Jualan",
           "Mahir berkaitan", "Operator", "Asas"]

PENDIDIKAN = ["Pasca (L/P)", "Deg A (L/P)", "Deg T (L/P)", "Dip A (L/P)",
              "Dip TVet (L/P)", "STPM (L/P)", "Cert A (L/P)", "TVET (L/P)",
              "SPM (L/P)", "Under SPM (L/P)"]


def blank_kp205_fields(company: str, year: int) -> tuple[list[dict], dict]:
    fields: list[dict] = []
    meta = {"company": company, "ssm": "", "msic": "",
            "aktiviti": "", "responden": "", "tahun_mula": "",
            "tahun_kewangan": str(year), "fail": "(template blanko)"}

    fields.append(_mk(SECTION_META, "Company / Syarikat", company,
                      fid="META::Company / Syarikat"))
    for lab in ("SSM No. Pendaftaran", "Kod MSIC (Newss)", "Aktiviti utama",
                "Alamat berdaftar", "Nama responden", "Tahun mula operasi"):
        f = _mk(SECTION_META, lab, "", fid=f"META::{lab}")
        if f"META::{lab}" in MANUAL_ONLY:
            f["note"] = "Semak manual di SSM e-Info (tidak dianggar AI)"
        fields.append(f)
    fields.append(_mk(SECTION_META, "Akhir tahun kewangan", str(year),
                      fid="META::Akhir tahun kewangan"))
    fields.append(_mk(SECTION_META, "Modal berbayar (Capital)", "",
                      fid="META::Modal berbayar (Capital)"))

    for ak in ASET:
        fields.append(_mk(SECTION_ASET, f"Aset {ak} (Bersih)", "",
                          fid=f"{SECTION_ASET}::{ak}"))
    for code, lab in PENDAPATAN:
        fields.append(_mk(SECTION_PENDAPATAN, f"{code} {lab}", "",
                          fid=f"{SECTION_PENDAPATAN}::{code}"))
    for tag in ("Semasa", "Sebelum"):
        fields.append(_mk(SECTION_PENDAPATAN, f"Untung/Rugi ({tag})", "",
                          fid=f"{SECTION_PENDAPATAN}::Untung::{tag}"))
    for code, lab in BELANJA:
        fields.append(_mk(SECTION_BELANJA, f"{code} {lab}", "",
                          fid=f"{SECTION_BELANJA}::{code}"))
    for key in STOK:
        for tag in ("Awal", "Akhir"):
            fields.append(_mk(SECTION_STOK, f"Stok {key} ({tag})", "",
                              fid=f"{SECTION_STOK}::{key}::{tag}"))
    for lab in ("Bahan utama — Unit Guna", "Bahan utama — RM (Tempatan)",
                "Bahan utama — RM (Import)", "Kapasiti (%)"):
        fields.append(_mk(SECTION_BAHAN, lab, "",
                          fid=f"{SECTION_BAHAN}::{lab}"))
    for ng in NEGERI:
        fields.append(_mk(SECTION_NEGERI, f"{ng} — Bahan mentah", "",
                          fid=f"{SECTION_NEGERI}::{ng}::BahanMentah"))
        fields.append(_mk(SECTION_NEGERI, f"{ng} — Jualan", "",
                          fid=f"{SECTION_NEGERI}::{ng}::Jualan"))
    for kat in PEKERJA:
        fields.append(_mk(SECTION_PEKERJA, f"Pekerja Lelaki — {kat}", "",
                          fid=f"{SECTION_PEKERJA}::L::{kat}"))
        fields.append(_mk(SECTION_PEKERJA, f"Pekerja Perempuan — {kat}", "",
                          fid=f"{SECTION_PEKERJA}::P::{kat}"))
    for lab in ("Pekerja — Jumlah besar (Total)", "Pekerja — Sambilan",
                "Pekerja Lelaki (L)", "Pekerja Perempuan (P)",
                "Pekerja — Warganegara (Warga)",
                "Pekerja — Bukan Warganegara (BWN)"):
        fields.append(_mk(SECTION_PEKERJA, lab, "",
                          fid=f"{SECTION_PEKERJA}::{lab}"))
    for kat in PEKERJA:
        fields.append(_mk("GAJI", f"Gaji bulanan Lelaki — {kat}", "",
                          fid=f"GAJI::L::{kat}"))
        fields.append(_mk("GAJI", f"Gaji bulanan Perempuan — {kat}", "",
                          fid=f"GAJI::P::{kat}"))
    for lab in ("Hari beroperasi", "Jam/Shift", "Jumlah Jam", "JAM OT",
                "Upah OT", "Bil Pekerja Shift 1", "Bil Pekerja Shift 2",
                "Bil Pekerja Shift 3"):
        fields.append(_mk(SECTION_SHIFT, lab, "", fid=f"{SECTION_SHIFT}::{lab}"))
    for lab in PENDIDIKAN:
        fields.append(_mk(SECTION_PENDIDIKAN, f"Pendidikan {lab}", "",
                          fid=f"{SECTION_PENDIDIKAN}::{lab}"))
    return fields, meta
