"""Penyedia AI lokal / Local AI provider (OpenAI-compatible gateway).

Default: http://localhost:4000 (LiteLLM-style proxy, /v1/chat/completions,
/v1/models). Tiada kunci diperlukan secara lalai; URL + model boleh
ditukar dalam Tetapan atau env LOCAL_AI_URL / LOCAL_AI_MODEL.

Mengembalikan bentuk yang sama seperti OpenRouter/Gemini:
({label: {...}}, nota). Fail-soft bila gateway tiada/tutup.
"""
from __future__ import annotations
import os
import requests

from activity import emit

from search.ai_openrouter import _muat_json_tegar, _senarai_medan

DEFAULT_LOCAL_URL = "http://localhost:4000/v1"
# Free models verified working 2026-10-03 (JSON mode, fastest first).
# Dead: ling-3.0 (400), lfm-2.5/ultra-550b (404), inkling* (keys exhausted),
# laguna-xs (empty), content-safety (guard text), lightning (77s too slow).
LOCAL_FREE_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",   # ~0.7s
    "cohere/north-mini-code:free",               # ~1.3s
    "qwen/qwen3.8-27b:free",                     # ~1.9s
    "google/gemma-4-26b-a4b-it:free",            # ~3.2s
    "google/gemma-4-31b-it:free",                # ~3.7s
    "openrouter/free",                           # ~5.4s
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",  # ~7s
    "apodex/apodex-1.1-mini:free",               # ~10s
    "dots-studio/dots-3-note-preview:free",      # ~10s
    "poolside/laguna-s-2.1:free",                # ~10s
]
DEFAULT_LOCAL_MODEL = LOCAL_FREE_MODELS[0]
TIMEOUT = 90
PING_TIMEOUT = 12


def local_base_url(explicit: str = "") -> str:
    u = ((explicit or "").strip() or os.environ.get("LOCAL_AI_URL", "").strip()
         or DEFAULT_LOCAL_URL).rstrip("/")
    return u


def dapatkan_kunci_local(explicit: str = "") -> str:
    return (explicit or "").strip() or os.environ.get("LOCAL_AI_KEY", "").strip()


def local_model(explicit: str = "") -> str:
    return ((explicit or "").strip() or os.environ.get("LOCAL_AI_MODEL", "").strip()
            or DEFAULT_LOCAL_MODEL)


def ping_local(base_url: str = "", timeout: int = PING_TIMEOUT) -> tuple[bool, str]:
    """Quick check: GET {base}/models. Returns (ok, nota)."""
    base = local_base_url(base_url)
    try:
        r = requests.get(f"{base}/models", timeout=timeout)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        try:
            n = len(r.json().get("data", []))
            return True, f"OK ({n} model)"
        except Exception:
            return True, "OK"
    except Exception as e:
        return False, f"gagal: {e}"


def senarai_model_local(base_url: str = "", limit: int = 500) -> list[str]:
    """Model ids from the local gateway (fail-soft: [])."""
    base = local_base_url(base_url)
    try:
        r = requests.get(f"{base}/models", timeout=PING_TIMEOUT)
        r.raise_for_status()
        ids = [m.get("id", "") for m in r.json().get("data", [])]
        return [i for i in ids if i][:limit]
    except Exception as e:
        emit("WARN", f"Model lokal tidak dapat disenaraikan: {e}")
        return []


def perkaya_local(syarikat: str, tahun: int, medan: list[dict], konteks: dict,
                  base_url: str = "", model: str = "",
                  api_key: str = "",
                  anggaran: bool = False) -> tuple[dict, str]:
    """Tanya gateway lokal (format OpenAI chat). Returns (peta, nota)."""
    import json as _json
    base = local_base_url(base_url)
    key = dapatkan_kunci_local(api_key)
    mdl = local_model(model)
    if not medan:
        return {}, "AI dilangkau: tiada medan dikesan dari templat."
    mod = "ANGGARAN" if anggaran else "CADANGAN"
    emit("AI", f"Lokal [{mod}]: hantar {len(medan)} medan ke {mdl} ...")
    senarai = _senarai_medan(medan)
    if anggaran:
        sistem = (
            "Anda penaksir data ekonomi. Beri ANGGARAN yang munasabah untuk SETIAP medan "
            "berdasarkan profil syarikat, sektor, dan nisbah kewangan lazim. "
            "PENTING: nilai MESTI TEPAT dan TERPERINCI — kira ikut nisbah, "
            "JANGAN bundarkan kepada ribu/puluh ribu terdekat. "
            "Jawab HANYA JSON sah bentuk {\"medan\": [{\"label\": ..., \"sel\": ..., "
            "\"nilai\": ..., \"sumber\": \"ANGGARAN AI\", \"keyakinan\": \"RENDAH\", "
            "\"nota\": ...}]}. Salin 'sel' TEPAT seperti diberi."
        )
        pengguna = (
            f"Syarikat: {syarikat}\nTahun laporan: {tahun}\n"
            f"Konteks rasmi: {_json.dumps(konteks, ensure_ascii=False)[:2000]}\n\n"
            f"Anggarkan nilai untuk medan kosong berikut:\n{senarai}"
        )
    else:
        sistem = (
            "Anda pembantu data ekonomi yang tepat dan jujur. Jawab HANYA JSON sah "
            "dengan bentuk {\"medan\": [{\"label\": ..., \"sel\": ..., \"nilai\": ..., "
            "\"sumber\": ..., \"keyakinan\": \"TINGGI/SEDARHANA/RENDAH\", \"nota\": ...}]}. "
            "Salin 'sel' TEPAT seperti diberi. Jika tidak tahu sesuatu nilai, "
            "kosongkan dan letak keyakinan RENDAH. Jangan reka nombor kewangan."
        )
        pengguna = (
            f"Syarikat: {syarikat}\nTahun laporan: {tahun}\n"
            f"Konteks rasmi (utamakan): {_json.dumps(konteks, ensure_ascii=False)[:2000]}\n\n"
            f"Medan borang:\n{senarai}"
        )
    calon = [mdl]
    for fb in LOCAL_FREE_MODELS:
        if fb not in calon:
            calon.append(fb)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    last_err: Exception | None = None
    for mc in calon:
        for cubaan in range(1, 3):
            try:
                emit("NET", f"Lokal POST {mc} ...")
                r = requests.post(
                    f"{base}/chat/completions",
                    headers=headers,
                    json={"model": mc,
                          "messages": [{"role": "system", "content": sistem},
                                       {"role": "user", "content": pengguna}],
                          "response_format": {"type": "json_object"},
                          "temperature": 0.1},
                    timeout=TIMEOUT)
                r.raise_for_status()
                isi = r.json()["choices"][0]["message"]["content"] or ""
                data = _muat_json_tegar(isi)
                peta = {}
                for it in data.get("medan", data.get("fields", [])):
                    lab = str(it.get("label", "")).strip()
                    sel = str(it.get("sel", it.get("cell", ""))).strip()
                    if lab:
                        if anggaran:
                            peta[(lab, sel)] = {
                                "nilai": it.get("nilai", it.get("value", "")),
                                "sumber": "ANGGARAN AI",
                                "keyakinan": "RENDAH",
                                "nota": it.get("nota", it.get("note", ""))}
                        else:
                            peta[(lab, sel)] = {
                                "nilai": it.get("nilai", it.get("value", "")),
                                "sumber": it.get("sumber", it.get("source", "AI-Lokal")),
                                "keyakinan": str(it.get(
                                    "keyakinan",
                                    it.get("confidence", "RENDAH"))).upper(),
                                "nota": it.get("nota", it.get("note", ""))}
                berisi = sum(1 for v in peta.values()
                             if v.get("nilai") not in (None, ""))
                apa = "anggaran" if anggaran else "cadangan"
                emit("AI", f"Lokal: {len(peta)} medan {apa}, {berisi} bernilai.")
                return peta, f"OK:Lokal {mc} ({len(peta)} medan {apa})"
            except Exception as e:
                last_err = e
                kod = getattr(getattr(e, "response", None), "status_code", 0)
                teks = str(e)
                # gateway tutup / model ditolak upstream -> cuba calon seterusnya
                if kod in (404, 429, 503) or "proxy_error" in teks \
                        or "Connection" in type(e).__name__ \
                        or "Failed to establish" in teks \
                        or "Max retries" in teks:
                    emit("WARN", f"Lokal {mc} gagal ({kod or type(e).__name__})"
                                 " — cuba model lain ...")
                    break
                boleh_cuba = isinstance(
                    e, (ValueError, KeyError, _json.JSONDecodeError)) \
                    or kod in (500, 502, 504) or "choices" in teks
                emit("WARN" if boleh_cuba and cubaan < 2 else "ERR",
                     f"Lokal {mc} cubaan {cubaan}/2 gagal: {e}")
                if not boleh_cuba or cubaan >= 2:
                    break
    if last_err is not None and "Failed to establish" in str(last_err):
        return {}, "AI lokal dilangkau: gateway tiada (pastikan localhost:4000 hidup)."
    return {}, f"Lokal ralat: {last_err}"
