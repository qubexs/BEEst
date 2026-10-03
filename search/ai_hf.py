"""Penyedia Hugging Face / HF Inference Providers (OpenAI-compatible router).

Endpoint: https://router.huggingface.co/v1/chat/completions dengan
Bearer hf_... Token mesti ada kebenaran "Inference Providers" (fine-grained)
dan model gated (Llama/Gemma) mesti diterima lesennya di akaun HF.

Mengembalikan bentuk yang sama seperti OpenRouter/Gemini/Lokal:
({label: {...}}, nota). Fail-soft bila kunci tiada/tidak sah.
"""
from __future__ import annotations
import os
import requests

from activity import emit

from search.ai_openrouter import _muat_json_tegar, _senarai_medan

HF_BASE = "https://router.huggingface.co/v1"
TIMEOUT = 90

# Model teks kecil yang serasi chat completions (dicuba satu-persatu).
HF_FREE_MODELS = [
    "Qwen/Qwen2.5-7B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "HuggingFaceH4/zephyr-7b-beta",
    "microsoft/Phi-3-mini-4k-instruct",
    "Qwen/Qwen2.5-14B-Instruct",
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
]
DEFAULT_HF_MODEL = HF_FREE_MODELS[0]


def dapatkan_kunci_hf(explicit: str = "") -> str:
    return ((explicit or "").strip()
            or os.environ.get("HF_TOKEN", "").strip()
            or os.environ.get("HF_API_KEY", "").strip())


def hf_model(explicit: str = "") -> str:
    return ((explicit or "").strip()
            or os.environ.get("HF_MODEL", "").strip()
            or DEFAULT_HF_MODEL)


def ping_hf(api_key: str = "", model: str = "",
            timeout: int = 30) -> tuple[bool, str]:
    """Tiny chat ping. Returns (ok, nota) — auth errors reported plainly."""
    key = dapatkan_kunci_hf(api_key)
    if not key:
        return False, "tiada kunci HF"
    mdl = hf_model(model)
    try:
        r = requests.post(
            f"{HF_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": mdl,
                  "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 2},
            timeout=timeout)
        if r.status_code == 200:
            return True, f"OK ({mdl})"
        if r.status_code in (401, 403):
            return False, (f"HTTP {r.status_code}: kunci tidak sah / tiada "
                           f"izin Inference Providers. ({r.text[:120]})")
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, f"gagal: {e}"


def perkaya_hf(syarikat: str, tahun: int, medan: list[dict], konteks: dict,
               api_key: str, model: str = "",
               anggaran: bool = False) -> tuple[dict, str]:
    """Tanya router HF (format OpenAI chat). Returns (peta, nota)."""
    import json as _json
    key = dapatkan_kunci_hf(api_key)
    if not key:
        emit("WARN", "AI HF dilangkau: tiada kunci.")
        return {}, "AI dilangkau: tiada kunci HF (isi dalam tab Tetapan)."
    mdl = hf_model(model)
    if not medan:
        return {}, "AI dilangkau: tiada medan dikesan dari templat."
    mod = "ANGGARAN" if anggaran else "CADANGAN"
    emit("AI", f"HF [{mod}]: hantar {len(medan)} medan ke {mdl} ...")
    senarai = _senarai_medan(medan)
    if anggaran:
        sistem = (
            "Anda penaksir data ekonomi. Beri ANGGARAN yang munasabah untuk SETIAP medan "
            "berdasarkan profil syarikat, sektor, dan nisbah kewangan lazim. "
            "PENTING: nilai MESTI TEPAT dan TERPERINCI, JANGAN bundarkan kepada "
            "ribu/puluh ribu terdekat. "
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
    for fb in HF_FREE_MODELS:
        if fb not in calon:
            calon.append(fb)
    last_err: Exception | None = None
    for mc in calon:
        for cubaan in range(1, 3):
            try:
                emit("NET", f"HF POST {mc} ...")
                r = requests.post(
                    f"{HF_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    json={"model": mc,
                          "messages": [{"role": "system", "content": sistem},
                                       {"role": "user", "content": pengguna}],
                          "temperature": 0.1, "max_tokens": 2000},
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
                                "sumber": it.get("sumber", it.get("source", "AI-HF")),
                                "keyakinan": str(it.get(
                                    "keyakinan",
                                    it.get("confidence", "RENDAH"))).upper(),
                                "nota": it.get("nota", it.get("note", ""))}
                berisi = sum(1 for v in peta.values()
                             if v.get("nilai") not in (None, ""))
                apa = "anggaran" if anggaran else "cadangan"
                emit("AI", f"HF: {len(peta)} medan {apa}, {berisi} bernilai.")
                return peta, f"OK:HF {mc} ({len(peta)} medan {apa})"
            except Exception as e:
                last_err = e
                kod = getattr(getattr(e, "response", None), "status_code", 0)
                teks = str(e)
                if kod in (401, 403):
                    emit("ERR", f"HF kunci ditolak ({kod}) — semak izin "
                                "Inference Providers token.")
                    return {}, f"HF ralat auth ({kod}): {teks[:150]}"
                if kod in (404, 429, 503) or "overloaded" in teks.lower():
                    emit("WARN", f"HF {mc} gagal ({kod or type(e).__name__})"
                                 " — cuba model lain ...")
                    break
                boleh_cuba = isinstance(
                    e, (ValueError, KeyError, _json.JSONDecodeError)) \
                    or kod in (500, 502, 504) or "choices" in teks
                emit("WARN" if boleh_cuba and cubaan < 2 else "ERR",
                     f"HF {mc} cubaan {cubaan}/2 gagal: {e}")
                if not boleh_cuba or cubaan >= 2:
                    break
    return {}, f"HF ralat: {last_err}"
