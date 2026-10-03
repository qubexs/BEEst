"""Semakan silang antara seksyen (cross-section consistency).

Each check compares related sections and flags values outside the
expected band for the sector profile:
- bahan mentah (9.1) vs jualan (8.1)      <- issue #1: too small for pembuatan
- gaji (9.36a) vs bilangan pekerja        <- avg wage sanity
- gaji vs jualan share
- susut (9.29) vs jumlah aset              <- asset relevance
- stok bahan vs penggunaan (9.1)           <- stock cover
- sewa (9.28b) vs belanja
- KWSP / PERKESO vs gaji                   <- statutory ratios
- margin untung
"""
from __future__ import annotations

PB, PP = "PERBELANJAAN", "PENDAPATAN"

BANDS = {
    "pembuatan": {
        "bahan": (0.25, 0.75), "gaji_share": (0.08, 0.35),
    },
    "pembinaan": {
        "bahan": (0.20, 0.60), "gaji_share": (0.10, 0.40),
    },
    "perkhidmatan": {
        "bahan": (0.03, 0.45), "gaji_share": (0.15, 0.55),
    },
}


def _num(v):
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def semak(fields: list[dict], profil: str = "perkhidmatan") -> list[str]:
    """Returns check lines: OK ... / AMARAN ... / SKIP ...."""
    prof = profil if profil in BANDS else "perkhidmatan"
    b = BANDS[prof]

    def get(fid: str):
        for f in fields:
            if f["id"] == fid and f.get("value") not in (None, ""):
                return _num(f["value"])
        return None

    out: list[str] = []

    def band(nama: str, val, lo: float, hi: float, fmt: str,
            lana: str = ""):
        if val is None:
            out.append(f"SKIP {nama}: data tak cukup{lana}")
            return
        s = fmt.format(val)
        if lo <= val <= hi:
            out.append(f"OK {nama}: {s} (julat {lo:g}–{hi:g})")
        else:
            arah = "terlalu kecil" if val < lo else "terlalu besar"
            out.append(f"AMARAN {nama}: {s} {arah} "
                       f"(julat {lo:g}–{hi:g}, profil {prof})")

    jualan = get(f"{PP}::8.1") or get(f"{PP}::8.13") or get(f"{PP}::8.15")
    belanja = get(f"{PB}::9.39") or get(f"{PB}::9.44")
    bahan = get(f"{PB}::9.1")
    gaji = get(f"{PB}::9.36(a)")
    kwsp = get(f"{PB}::9.36(d)(i)")
    perkeso = get(f"{PB}::9.36(d)(iii)")
    susut = get(f"{PB}::9.29")
    aset = get("ASET::Jumlah")
    stok = get("STOK::Jumlah::Akhir")
    sewa = get(f"{PB}::9.28(b)")
    tot_p = get("PEKERJA::Pekerja — Jumlah besar (Total)")

    # 1. bahan mentah vs jualan
    r = (bahan / jualan) if bahan is not None and jualan else None
    band("9.1 Bahan/Jualan 8.1", r, *b["bahan"], "{:.1%}",
         " — 9.1 atau 8.1 kosong" if r is None else "")
    # 2. gaji vs jualan
    r = (gaji / (get(f"{PP}::8.13") or get(f"{PP}::8.15") or jualan)) \
        if gaji is not None and (jualan or get(f"{PP}::8.13")) else None
    band("9.36(a) Gaji/Jualan", r, *b["gaji_share"], "{:.1%}", "")
    # 3. purata gaji sebulan seorang pekerja
    avg = (gaji / tot_p / 12) if gaji and tot_p else None
    band("Purata gaji/bln/orang", avg, 1500, 15000, "RM{:.0f}", "")
    # 4. ASET MESTI > SUSUT (peraturan keras) + nisbah susut munasabah
    r = (susut / aset) if susut is not None and aset else None
    if susut is None or aset is None:
        out.append("SKIP Aset vs Susut: data tak cukup")
    elif not aset and not susut:
        out.append("OK Aset vs Susut: tiada aset/susut direkodkan")
    elif aset > susut:
        band("9.29 Susut/Aset", r, 0, 0.40, "{:.1%}", "")
    else:
        out.append(f"AMARAN Aset vs Susut: ASET RM{aset:g} MESTI > "
                   f"SUSUT RM{susut:g} — salah satu angka tidak munasabah, "
                   "semak semula")
    # 5. liputan stok bahan (bulan penggunaan 9.1)
    r = (stok / (bahan / 12)) if stok is not None and bahan else None
    band("Stok Akhir/bulan-bahan", r, 0, 8, "{:.1f} bln", "")
    # 6. sewa vs belanja
    r = (sewa / belanja) if sewa is not None and belanja else None
    band("9.28(b) Sewa/Belanja", r, 0, 0.30, "{:.1%}", "")
    # 7/8. KWSP / PERKESO vs gaji
    r = (kwsp / gaji) if kwsp is not None and gaji else None
    band("KWSP/Gaji (13%)", r, 0.11, 0.15, "{:.1%}", "")
    r = (perkeso / gaji) if perkeso is not None and gaji else None
    band("PERKESO/Gaji (1.75%)", r, 0.010, 0.025, "{:.2%}", "")
    # 9. margin untung
    h15 = get(f"{PP}::8.15") or get(f"{PP}::8.13")
    b44 = get(f"{PB}::9.44") or get(f"{PB}::9.39")
    r = ((h15 - b44) / h15) if h15 and b44 else None
    band("Margin (Hasil-Belanja)/Hasil", r, -0.5, 0.6, "{:.1%}", "")

    # 10. jumlah pekerja = L + P
    L = get("PEKERJA::Pekerja Lelaki (L)")
    P = get("PEKERJA::Pekerja Perempuan (P)")
    if L is None or P is None or tot_p is None:
        out.append("SKIP Pekerja L+P=Jumlah: data tak cukup")
    elif L + P == tot_p:
        out.append(f"OK Pekerja L+P=Jumlah: {L:g}+{P:g}={tot_p:g}")
    else:
        out.append(f"AMARAN Pekerja L+P=Jumlah: {L:g}+{P:g}={L + P:g} "
                   f"≠ Jumlah {tot_p:g} — selaraskan")

    # 11. warga + BWN = jumlah
    warga = get("PEKERJA::Pekerja — Warganegara (Warga)")
    bwn = get("PEKERJA::Pekerja — Bukan Warganegara (BWN)")
    if warga is None or bwn is None or tot_p is None:
        out.append("SKIP Warga+BWN=Jumlah: data tak cukup")
    elif warga + bwn == tot_p:
        out.append(f"OK Warga+BWN=Jumlah: {warga:g}+{bwn:g}={tot_p:g}")
    else:
        out.append(f"AMARAN Warga+BWN=Jumlah: {warga:g}+{bwn:g}={warga + bwn:g} "
                   f"≠ Jumlah {tot_p:g} — selaraskan")

    # 12/13. jumlah kategori L/P = jumlah L/P
    by_id = {f["id"]: f for f in fields}
    for gender, tag in (("L", "Lelaki"), ("P", "Perempuan")):
        tot_g = L if gender == "L" else P
        if tot_g is None:
            out.append(f"SKIP Kategori {tag}=Jumlah {tag}: data tak cukup")
            continue
        s, miss = 0, []
        for f in fields:
            if f["id"].startswith(f"PEKERJA::{gender}::"):
                v = _num(f.get("value"))
                if v is None:
                    miss.append(f["label"])
                else:
                    s += v
        if miss:
            out.append(f"SKIP Kategori {tag}=Jumlah {tag}: kosong: "
                       + ", ".join(miss[:4])
                       + (" ..." if len(miss) > 4 else ""))
        elif s == tot_g:
            out.append(f"OK Kategori {tag}=Jumlah {tag}: {s:g}={tot_g:g}")
        else:
            out.append(f"AMARAN Kategori {tag}=Jumlah {tag}: jumlah kategori "
                       f"{s:g} ≠ {tot_g:g} — selaraskan")

    # 14. gaji bulanan setiap jawatan dalam julat skala
    try:
        from kp205.gaji import get_skala
        skala = get_skala()
    except Exception:
        skala = {}
    bad = []
    for gender, tag in (("L", "Lelaki"), ("P", "Perempuan")):
        for kat, (lo, hi) in skala.items():
            v = _num((by_id.get(f"GAJI::{gender}::{kat}") or {}).get("value"))
            if v is None:
                continue
            if not (lo <= v <= hi):
                bad.append(f"{tag} {kat} RM{v:g} (julat RM{lo:g}–RM{hi:g})")
    if bad:
        out.append("AMARAN Gaji luar julat skala: " + "; ".join(bad[:5])
                   + (" ..." if len(bad) > 5 else ""))
    else:
        out.append("OK Gaji semua jawatan dalam julat skala")

    # 15. belanja pekerja tidak melebihi jumlah belanja
    if belanja is None:
        out.append("SKIP Belanja Pekerja/Belanja: data tak cukup")
    else:
        wp = sum((_num((by_id.get(f"PERBELANJAAN::{c}") or {}).get("value"))
                      or 0) for c in
                 ["9.36(a)", "9.36(b)", "9.36(c)(i)", "9.36(c)(ii)",
                  "9.36(d)(i)", "9.36(d)(ii)", "9.36(d)(iii)",
                  "9.36(d)(iv)", "9.36(d)(v)", "9.36(e)", "9.36(f)",
                  "9.36(g)", "9.36(h)", "9.36(i)", "9.36(j)", "9.36(k)",
                  "9.37"])
        if wp <= belanja:
            out.append(f"OK Belanja Pekerja/Belanja: RM{wp:g} "
                       f"({wp / belanja:.1%} daripada belanja)")
        else:
            out.append(f"AMARAN Belanja Pekerja/Belanja: RM{wp:g} MELEBIHI "
                       f"belanja RM{belanja:g} — mustahil, semak semula")

    # 16. pekerja shif vs jumlah pekerja (semua shif diisi baru disemak)
    sh = [_num((by_id.get(f"SHIFT::Bil Pekerja Shift {i}") or {})
               .get("value")) for i in (1, 2, 3)]
    if tot_p is None or any(v is None for v in sh):
        out.append("SKIP Shif1+2+3=Jumlah: data tak cukup")
    elif sum(sh) == tot_p:
        out.append(f"OK Shif1+2+3=Jumlah: {sh[0]:g}+{sh[1]:g}+{sh[2]:g}="
                   f"{tot_p:g}")
    else:
        out.append(f"AMARAN Shif1+2+3=Jumlah: {sh[0]:g}+{sh[1]:g}+{sh[2]:g}="
                   f"{sum(sh):g} ≠ Jumlah {tot_p:g} — selaraskan")

    # 17. jumlah bil gaji (orang x kadar x 12) vs 9.36(a) gaji tahunan
    try:
        from kp205.gaji import get_skala as _sk
        _skala = _sk()
    except Exception:
        _skala = {}
    bil, bil_hilang = 0.0, []
    for gender in ("L", "P"):
        for kat in _skala:
            hv = _num((by_id.get(f"PEKERJA::{gender}::{kat}") or {})
                      .get("value"))
            mv = _num((by_id.get(f"GAJI::{gender}::{kat}") or {})
                      .get("value"))
            if hv is None or mv is None:
                if hv:
                    bil_hilang.append(f"{gender}/{kat}")
                continue
            bil += hv * mv * 12
    if gaji is None or bil_hilang:
        out.append("SKIP Bil Gaji/9.36(a): data tak cukup"
                   + (f" (kosong: {', '.join(bil_hilang[:3])})"
                      if bil_hilang else ""))
    elif bil == 0 and gaji == 0:
        out.append("OK Bil Gaji/9.36(a): tiada pekerja/tiada gaji")
    elif abs(bil - gaji) <= max(1000, 0.05 * gaji):
        out.append(f"OK Bil Gaji/9.36(a): RM{bil:g} ≈ RM{gaji:g}")
    else:
        out.append(f"AMARAN Bil Gaji/9.36(a): RM{bil:g} (orang×kadar×12) "
                   f"≠ 9.36(a) RM{gaji:g} — selaraskan")

    # 18. JAM OT vs Upah OT: sifar serentak + kadar munasabah
    jam_ot = _num((by_id.get("SHIFT::JAM OT") or {}).get("value"))
    upah_ot = _num((by_id.get("SHIFT::Upah OT") or {}).get("value"))
    if jam_ot is None or upah_ot is None:
        out.append("SKIP OT Jam/Upah: data tak cukup")
    elif not jam_ot and not upah_ot:
        out.append("OK OT Jam/Upah: tiada OT direkodkan")
    elif bool(jam_ot) != bool(upah_ot):
        out.append(f"AMARAN OT Jam/Upah: {jam_ot:g} jam vs RM{upah_ot:g} — "
                   f"satu sifar satu berisi, selaraskan")
    else:
        kadar = upah_ot / jam_ot if jam_ot else 0
        if 5 <= kadar <= 200:
            out.append(f"OK OT Jam/Upah: RM{kadar:.2f}/jam munasabah")
        else:
            out.append(f"AMARAN OT Jam/Upah: RM{kadar:.2f}/jam luar julat "
                       f"RM5–RM200 — semak")

    # 19. Jumlah Jam = Hari beroperasi x Jam/Shift
    hari = _num((by_id.get("SHIFT::Hari beroperasi") or {}).get("value"))
    jam = _num((by_id.get("SHIFT::Jam/Shift") or {}).get("value"))
    jml = _num((by_id.get("SHIFT::Jumlah Jam") or {}).get("value"))
    if hari is None or jam is None or jml is None:
        out.append("SKIP Jumlah Jam=Hari×Jam: data tak cukup")
    elif jml == hari * jam:
        out.append(f"OK Jumlah Jam=Hari×Jam: {jml:g}={hari:g}×{jam:g}")
    else:
        out.append(f"AMARAN Jumlah Jam=Hari×Jam: {jml:g} ≠ "
                   f"{hari:g}×{jam:g}={hari * jam:g} — selaraskan")

    # 20. BWN vs levi 9.36(i): ada pekerja asing mesti ada levi
    levi = _num((by_id.get(f"{PB}::9.36(i)") or {}).get("value"))
    if bwn is None:
        out.append("SKIP BWN/Levi: data tak cukup")
    elif not bwn and levi in (None, 0):
        out.append("OK BWN/Levi: tiada pekerja asing, tiada levi")
    elif not bwn:
        out.append(f"AMARAN BWN/Levi: BWN={bwn:g} tetapi levi RM{levi:g} — "
                   f"kosongkan levi")
    elif levi in (None, 0):
        out.append(f"AMARAN BWN/Levi: BWN={bwn:g} tetapi levi kosong — "
                   f"levi mesti berisi")
    else:
        seorg = levi / bwn if bwn else 0
        if 300 <= seorg <= 6000:
            out.append(f"OK BWN/Levi: RM{levi:g}/{bwn:g}=RM{seorg:g}/orang")
        else:
            out.append(f"AMARAN BWN/Levi: RM{seorg:g}/orang luar julat "
                       f"RM300–RM6000 — semak kadar levi")
    return out
