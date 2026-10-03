"""Pengayaan AI via OpenRouter: minta model AI cari data syarikat & cadang nilai borang.

Tiada pergantungan baharu — hanya `requests`.
Gagal lembut (fail-soft): tanpa kunci API atau luar talian, pulangkan nota ralat
dan biarkan data deterministik (ANAF/BNR) kekal digunakan.
"""
from __future__ import annotations
import json
import os
import re
import requests

from activity import emit

API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 60

MODEL_PILIHAN = [
    "openai/gpt-4o-mini",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash-001",
    "anthropic/claude-3.5-haiku",
]

DEFAULT_MODEL = MODEL_PILIHAN[0]


def dapatkan_kunci(explicit: str = "") -> str:
    return (explicit or "").strip() or os.environ.get("OPENROUTER_API_KEY", "").strip()


def _muat_json_tegar(teks: str) -> dict:
    """Hurai JSON AI secara toleran: pagar kod, aksara kawalan, potongan hujung."""
    t = (teks or "").strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    i = t.find("{")
    if i > 0:
        t = t[i:]
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    cuba = [t, t + "]}", t + "}", t + "]", t + '"]}']
    j = t.rfind("}")
    if j > 0:
        cuba += [t[:j + 1], t[:j + 1] + "]}", t[:j + 1] + "}"]
    for c in cuba:
        try:
            return json.loads(c)
        except Exception:
            continue
    raise ValueError("JSON AI tidak dapat dibaca selepas pembaikan")


def _senarai_medan(medan: list[dict], had: int = 80) -> str:
    """Senaraikan medan, dikumpulkan ikut helaian soal selidik bila ada kunci 'sheet'."""
    ambil = medan[:had]
    if any("sheet" in m for m in ambil):
        blok, helaian_akhir = [], None
        for m in ambil:
            sh = m.get("sheet") or "?"
            if sh != helaian_akhir:
                blok.append(f"Helaian `{sh}`:")
                helaian_akhir = sh
            blok.append(f"- {m['label']} (sel {m['cell']}, nilai semasa: {m.get('semasa', '')!r})")
        return "\n".join(blok)
    return "\n".join(
        f"- {m['label']} (sel {m['cell']}, nilai semasa: {m.get('semasa', '')!r})"
        for m in ambil)


def perkaya_syarikat(syarikat: str, tahun: int, medan: list[dict],
                     konteks: dict, api_key: str,
                     model: str = DEFAULT_MODEL,
                     anggaran: bool = False) -> tuple[dict, str]:
    """Tanya AI untuk nilai setiap medan borang.

    medan: [{"label":..., "cell":"BE2026!B3", "semasa":...}, ...]
    konteks: {"anaf": {...}, "fx": {...}} (data deterministik sedia ada)
    anggaran=True: mod anggaran — AI MESTI beri nilai anggaran berasas untuk
      setiap medan (bukan kosong), keyakinan RENDAH, sumber ANGGARAN AI.
    Pulangan: ({label: {"nilai":..., "sumber":..., "keyakinan":..., "nota":...}}, nota_log)
    """
    key = dapatkan_kunci(api_key)
    if not key:
        emit("WARN", "AI OpenRouter dilangkau: tiada kunci API.")
        return {}, "AI dilangkau: tiada kunci API OpenRouter (isi di ruangan atau set OPENROUTER_API_KEY)."
    if not medan:
        return {}, "AI dilangkau: tiada medan dikesan dari templat."
    mod = "ANGGARAN" if anggaran else "CADANGAN"
    emit("AI", f"OpenRouter [{mod}]: hantar {len(medan)} medan + konteks ANAF/FX ke model {model} ...")

    senarai = _senarai_medan(medan)
    if anggaran:
        sistem = (
            "Anda penaksir data ekonomi. Beri ANGGARAN yang munasabah untuk SETIAP medan "
            "berdasarkan profil syarikat, sektor, dan nisbah kewangan lazim "
            "(cth: caruman KWSP ~13% daripada gaji, purata industri DOSM). "
            "PENTING: nilai MESTI TEPAT dan TERPERINCI — kira ikut nisbah "
            "(cth 15320 hasil darab nisbah, BUKAN angka kasar 15000). "
            "JANGAN bundarkan kepada ribu/puluh ribu terdekat. "
            "Jawab HANYA dalam JSON yang sah. keyakinan MESTI 'RENDAH', "
            "sumber MESTI 'ANGGARAN AI', dan nota MESTI nyatakan asas anggaran "
            "secara ringkas (termasuk nisbah/kiraan yang digunakan)."
        )
        pengguna = (
            f"Syarikat: {syarikat}\nTahun laporan: {tahun}\n"
            f"Konteks disahkan: {json.dumps(konteks, ensure_ascii=False)[:2000]}\n\n"
            f"Anggarkan nilai untuk medan kosong berikut (kumpulkan ikut helaian soal selidik):\n{senarai}\n\n"
            "Format jawapan (JSON sahaja): "
            '{"medan": [{"label": "<label TEPAT seperti di atas>", '
            '"sel": "<sel TEPAT seperti di atas, cth SHEET!B3>", '
            '"nilai": "<anggaran>", '
            '"sumber": "ANGGARAN AI", '
            '"keyakinan": "RENDAH", "nota": "<asas anggaran ringkas>"}]}'
        )
    else:
        sistem = (
            "Anda pembantu data ekonomi yang tepat dan jujur. Jawab HANYA dalam JSON yang sah, "
            "tanpa teks lain. Jika anda tidak tahu sesuatu nilai, letakkan nilai sebagai rentetan kosong "
            "dan keyakinan 'RENDAH'. Jangan reka nombor kewangan (hasil, untung, pekerja) — "
            "kosongkan jika tidak diketahui umum."
        )
        pengguna = (
            f"Syarikat: {syarikat}\nTahun laporan: {tahun}\n"
            f"Konteks disahkan (sumber rasmi, utamakan ini): {json.dumps(konteks, ensure_ascii=False)[:2000]}\n\n"
            f"Borang BE-{tahun} memerlukan medan berikut. Untuk SETIAP medan, berikan nilai yang paling "
            f"mungkin berdasarkan pengetahuan anda tentang syarikat ini (profil umum, sektor, data awam), "
            f"atau rentetan kosong jika tidak diketahui:\n{senarai}\n\n"
            "Format jawapan (JSON sahaja): "
            '{"medan": [{"label": "<label TEPAT seperti di atas>", '
            '"sel": "<sel TEPAT seperti di atas, cth SHEET!B3>", '
            '"nilai": "<nilai atau string kosong>", '
            '"sumber": "<contoh: Profil awam syarikat / Anggaran AI / Data rasmi>", '
            '"keyakinan": "<TINGGI/SEDARHANA/RENDAH>", "nota": "<ringkas atau kosong>"}]}'
        )
    last_err: Exception | None = None
    for cubaan in range(1, 4):
        try:
            r = requests.post(
                API_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                         "HTTP-Referer": "be2026-filler", "X-Title": "BE2026 filler"},
                json={"model": model, "messages": [
                    {"role": "system", "content": sistem},
                    {"role": "user", "content": pengguna}],
                    "response_format": {"type": "json_object"}, "temperature": 0.1},
                timeout=TIMEOUT)
            r.raise_for_status()
            isi = r.json()["choices"][0]["message"]["content"]
            emit("AI", f"OpenRouter: respons diterima ({len(isi)} aksara), hurai JSON ...")
            data = _muat_json_tegar(isi)
            peta = {}
            items = data.get("medan", data.get("fields", []))
            for it in items:
                lab = str(it.get("label", "")).strip()
                sel = str(it.get("sel", it.get("cell", ""))).strip()
                if lab:
                    if anggaran:
                        peta[(lab, sel)] = {"nilai": it.get("nilai", it.get("value", "")),
                                            "sumber": "ANGGARAN AI",
                                            "keyakinan": "RENDAH",
                                            "nota": it.get("nota", it.get("note", ""))}
                    else:
                        peta[(lab, sel)] = {"nilai": it.get("nilai", it.get("value", "")),
                                            "sumber": it.get("sumber", it.get("source", "AI")),
                                            "keyakinan": str(it.get("keyakinan", it.get("confidence", "RENDAH"))).upper(),
                                            "nota": it.get("nota", it.get("note", ""))}
            berisi = sum(1 for v in peta.values() if v.get("nilai") not in (None, ""))
            apa = "anggaran" if anggaran else "cadangan"
            emit("AI", f"OpenRouter: {len(peta)} medan {apa}, {berisi} bernilai "
                       f"({', '.join(k[0] for k, v in list(peta.items())[:5])}...).")
            return peta, f"OK:AI {model} ({len(peta)} medan {apa})"
        except Exception as e:
            last_err = e
            kod = getattr(getattr(e, "response", None), "status_code", 0)
            boleh_cuba = isinstance(e, (ValueError, KeyError, json.JSONDecodeError)) \
                or kod in (429, 500, 502, 503, 504) or "choices" in str(e)
            emit("WARN" if boleh_cuba and cubaan < 3 else "ERR",
                 f"OpenRouter cubaan {cubaan}/3 gagal: {e}")
            if not boleh_cuba or cubaan >= 3:
                return {}, f"AI ralat: {last_err}"
    return {}, f"AI ralat: {last_err}"


def gabung_ai_ke_baris(baris_list, peta_ai: dict, model: str) -> int:
    """Gabung cadangan AI ke dalam baris preview.

    Padanan UTAMA ikut alamat sel (SHEET!CELL) — tepat walaupun banyak medan
    berkongsi label sama. Padanan label hanya sandaran untuk respons AI lama.
    Peraturan: jika nilai propusa kosong -> AI jadi cadangan utama, else Alternatif.
    Pulangan: bilangan baris yang disentuh AI.
    """
    import unicodedata

    def norm(s):
        s = (s or "").lower()
        s = unicodedata.normalize("NFD", s)
        return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()

    def norm_sel(s):
        return re.sub(r"\s+", "", (s or "").upper())

    peta_sel: dict = {}
    peta_lab: dict = {}
    for k, v in (peta_ai or {}).items():
        if isinstance(k, tuple):
            lab, sel = k
            if sel and norm_sel(sel):
                peta_sel.setdefault(norm_sel(sel), v)
            else:
                peta_lab.setdefault(norm(lab), v)
        else:
            peta_lab.setdefault(norm(k), v)
    sentuh = 0
    utama = 0
    for b in baris_list:
        ai = peta_sel.get(norm_sel(f"{b.sheet}!{b.cell}"))
        if ai is None:
            ai = peta_lab.get(norm(b.label))
        if not ai:
            continue
        nilai = ai.get("nilai", "")
        if nilai in (None, ""):
            continue
        keyakinan = ai.get("keyakinan", "RENDAH")
        if keyakinan not in ("TINGGI", "SEDARHANA", "RENDAH"):
            keyakinan = "SEDARHANA"
        tag = f"AI:{model.split('/')[-1]}"
        if b.proposed in (None, "", 0) and b.proposed != 0:
            b.proposed = nilai
            b.proposed_source = tag
            b.confidence = keyakinan
            if ai.get("nota"):
                b.note = str(ai["nota"])
            sentuh += 1
            utama += 1
        else:
            b.alternate = nilai
            b.alternate_source = tag
            if ai.get("nota"):
                b.note = str(ai["nota"])
            sentuh += 1
    emit("INFO", f"Gabung AI: {sentuh} baris disentuh ({utama} jadi cadangan utama, "
                 f"{sentuh - utama} jadi Alternatif).")
    return sentuh
