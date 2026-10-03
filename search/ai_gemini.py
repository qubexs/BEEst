"""Penyedia Gemini langsung / Direct Gemini provider (REST, tanpa SDK).

Mengembalikan bentuk yang sama seperti OpenRouter: ({label: {...}}, nota).
"""
from __future__ import annotations
import json
import os
import requests

from activity import emit

from search.ai_openrouter import _muat_json_tegar

TIMEOUT = 60
# JSON estimation test 2026-10-03 (~2 medan): lite models 1.7s OK,
# 3.1-lite 2.5s, 3.1-lite-preview 2.7s, 3.7 4s, 3.5 5.3s.
# Quota-blocked now: flash-latest/preview/3.8/omni (429, fluctuates),
# 3.6-flash 503, 2.5-flash 404 retired. Chain auto-falls through.
GEMINI_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]
DEFAULT_GEMINI_MODEL = GEMINI_MODELS[0]

RETIRED_GEMINI = {
    "gemini-2.5-flash",  # 404: no longer available to new users
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-2.0-flash",
}


def resolve_gemini_model(model: str = "") -> str:
    """Map empty/retired/OpenRouter-style ids to a working Gemini model."""
    m = (model or "").strip()
    if "/" in m:  # OpenRouter-style id passed as gemini model
        return DEFAULT_GEMINI_MODEL
    if not m or m in RETIRED_GEMINI:
        return DEFAULT_GEMINI_MODEL
    return m


def senarai_model_gemini_live(api_key: str = "",
                                timeout: int = 20) -> list[str]:
    """Live model ids from the Gemini API (fail-soft: []).

    Non-text models (tts/image/embedding) are excluded — Settings shows
    only models usable for estimation.
    """
    key = dapatkan_kunci_gemini(api_key)
    if not key:
        return []
    SKIP = ("tts", "image", "embedding", "transcription", "asr")
    try:
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key}, timeout=timeout)
        r.raise_for_status()
        out = []
        for m in r.json().get("models", []):
            mid = str(m.get("name", "")).replace("models/", "")
            if not mid or mid in RETIRED_GEMINI:
                continue
            if any(s in mid.lower() for s in SKIP):
                continue
            out.append(mid)
        emit("OK", f"Gemini live: {len(out)} model teks.")
        return out
    except Exception as e:
        emit("WARN", f"Senarai model Gemini live gagal: {e}")
        return []


def gemini_candidates(model: str = "") -> list[str]:
    """Primary model first, then remaining known-good models (deduped)."""
    first = resolve_gemini_model(model)
    out = [first]
    for m in GEMINI_MODELS:
        if m not in out and m not in RETIRED_GEMINI:
            out.append(m)
    return out


def dapatkan_kunci_gemini(explicit: str = "") -> str:
    return (explicit or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()


def _senarai_berkumpulan(medan: list[dict], had: int = 80) -> str:
    ambil = medan[:had]
    if any("sheet" in m for m in ambil):
        blok, akhir = [], None
        for m in ambil:
            sh = m.get("sheet") or "?"
            if sh != akhir:
                blok.append(f"Helaian `{sh}`:")
                akhir = sh
            blok.append(f"- {m['label']} (sel {m['cell']}, nilai semasa: {m.get('semasa', '')!r})")
        return "\n".join(blok)
    return "\n".join(
        f"- {m['label']} (sel {m['cell']}, nilai semasa: {m.get('semasa', '')!r})"
        for m in ambil)


def perkaya_gemini(syarikat: str, tahun: int, medan: list[dict], konteks: dict,
                   api_key: str, model: str = DEFAULT_GEMINI_MODEL,
                   anggaran: bool = False) -> tuple[dict, str]:
    key = dapatkan_kunci_gemini(api_key)
    if not key:
        emit("WARN", "AI Gemini dilangkau: tiada kunci.")
        return {}, "AI dilangkau: tiada kunci Gemini (isi dalam tab Tetapan)."
    if not medan:
        return {}, "AI dilangkau: tiada medan dikesan dari templat."
    mod = "ANGGARAN" if anggaran else "CADANGAN"
    model_utama = resolve_gemini_model(model)
    if model_utama != (model or ""):
        emit("WARN", f"Gemini model '{model}' diganti -> '{model_utama}' "
                     f"(retired/tidak sah).")
    emit("AI", f"Gemini [{mod}]: hantar {len(medan)} medan ke {model_utama} ...")
    senarai = _senarai_berkumpulan(medan)
    if anggaran:
        arahan = (
            "Anda penaksir data ekonomi. Beri ANGGARAN yang munasabah untuk SETIAP medan "
            "berdasarkan profil syarikat, sektor, dan nisbah kewangan lazim. "
            "PENTING: nilai MESTI TEPAT dan TERPERINCI — kira ikut nisbah "
            "(cth 15320 hasil darab nisbah, BUKAN angka kasar 15000). "
            "JANGAN bundarkan kepada ribu/puluh ribu terdekat. "
            "Jawab HANYA JSON sah bentuk {\"medan\": [{\"label\": ..., \"sel\": ..., "
            "\"nilai\": ..., "
            "\"sumber\": \"ANGGARAN AI\", \"keyakinan\": \"RENDAH\", \"nota\": ...}]}. "
            "Salin 'sel' TEPAT seperti diberi (cth SHEET!B3). "
            "Nota MESTI nyatakan asas anggaran secara ringkas (termasuk nisbah/kiraan).")
        prompt = (f"Syarikat: {syarikat}\nTahun laporan: {tahun}\n"
                  f"Konteks rasmi: {json.dumps(konteks, ensure_ascii=False)[:2000]}\n\n"
                  f"Anggarkan nilai untuk medan kosong berikut (ikut helaian soal selidik):\n{senarai}")
    else:
        arahan = (
            "Anda pembantu data ekonomi yang tepat dan jujur. Jawab HANYA JSON sah "
            "dengan bentuk {\"medan\": [{\"label\": ..., \"sel\": ..., \"nilai\": ..., "
            "\"sumber\": ..., "
            "\"keyakinan\": \"TINGGI/SEDARHANA/RENDAH\", \"nota\": ...}]}. "
            "Salin 'sel' TEPAT seperti diberi (cth SHEET!B3). "
            "Jika tidak tahu sesuatu nilai, kosongkan dan letak keyakinan RENDAH. "
            "Jangan reka nombor kewangan.")
        prompt = (f"Syarikat: {syarikat}\nTahun laporan: {tahun}\n"
                  f"Konteks rasmi (utamakan): {json.dumps(konteks, ensure_ascii=False)[:2000]}\n\n"
                  f"Medan borang BE-{tahun}:\n{senarai}")
    url = None  # built per candidate below
    last_err: Exception | None = None
    for model_cuba in gemini_candidates(model):
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model_cuba}:generateContent")
        for cubaan in range(1, 3):
            try:
                emit("NET", f"Gemini POST {model_cuba}:generateContent ...")
                r = requests.post(url, params={"key": key},
                                  json={"system_instruction": {"parts": [{"text": arahan}]},
                                        "contents": [{"parts": [{"text": prompt}]}],
                                        "generationConfig": {"temperature": 0.1,
                                                             "response_mime_type": "application/json"}},
                                  timeout=TIMEOUT)
                r.raise_for_status()
                parts = r.json()["candidates"][0]["content"]["parts"]
                teks = "".join(p.get("text", "") for p in parts).strip()
                data = _muat_json_tegar(teks)
                peta = {}
                for it in data.get("medan", data.get("fields", [])):
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
                                                "sumber": it.get("sumber", it.get("source", "AI-Gemini")),
                                                "keyakinan": str(it.get("keyakinan",
                                                                        it.get("confidence", "RENDAH"))).upper(),
                                                "nota": it.get("nota", it.get("note", ""))}
                berisi = sum(1 for v in peta.values() if v.get("nilai") not in (None, ""))
                apa = "anggaran" if anggaran else "cadangan"
                emit("AI", f"Gemini: {len(peta)} medan {apa}, {berisi} bernilai.")
                return peta, f"OK:Gemini {model_cuba} ({len(peta)} medan {apa})"
            except Exception as e:
                last_err = e
                kod = getattr(getattr(e, "response", None), "status_code", 0)
                teks_err = str(e)
                if kod == 0:
                    try:
                        import re as _re
                        m = _re.search(r'"code":\s*(\d{3})', teks_err)
                        if m:
                            kod = int(m.group(1))
                    except Exception:
                        pass
                boleh_cuba = isinstance(e, (ValueError, KeyError, json.JSONDecodeError)) \
                    or kod in (429, 500, 502, 503, 504) or "candidates" in str(e)
                # 404 = retired model, 429/503 = quota/busy -> try next candidate
                if kod in (404, 429, 503) or "NOT_FOUND" in teks_err \
                        or "quota" in teks_err.lower():
                    if kod in (503, 500, 502, 504) and "quota" not in teks_err.lower():
                        # transient spike — normal, auto-switches silently
                        emit("INFO", f"Gemini {model_cuba} sibuk sementara "
                                    f"({kod}) — auto-tukar model lain ...")
                    else:
                        emit("WARN", f"Gemini {model_cuba} gagal ({kod}) — cuba model lain ...")
                    break  # next candidate model
                emit("WARN" if boleh_cuba and cubaan < 2 else "ERR",
                     f"Gemini {model_cuba} cubaan {cubaan}/2 gagal: {e}")
                if not boleh_cuba or cubaan >= 2:
                    # retry same-model exhausted; outer loop tries next candidate
                    # only if this was a transient error, else fail fast below
                    if boleh_cuba:
                        break
                    return {}, f"Gemini ralat: {last_err}"
    return {}, f"Gemini ralat: {last_err}"
