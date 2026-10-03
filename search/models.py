"""Cari model terbaik / Find the best model via live OpenRouter model list.

Ranking: PERCUMA dahulu (senarai keutamaan dikenali baik), kemudian termurah,
bonus konteks besar. Fail-soft: senarai simpanan jika luar talian.
"""
from __future__ import annotations
import os
import requests

from activity import emit

MODELS_URL = "https://openrouter.ai/api/v1/models"
TIMEOUT = 20

# Kecualikan model bukan-teks (muzik, imej, audio, embedding) dari cadangan generik.
SKIP_SUBSTR = ("lyria", "music", "clip", "image", "tts", "whisper",
               "embedding", "transcription", "moderation", "sora", "veo")

# Model percuma yang terbukti baik untuk tugasan borang berstruktur.
FREE_PRIORITY = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "mistralai/mistral-small-24b-instruct-2501:free",
    "deepseek/deepseek-chat-v3-0324:free",
]

PAID_PRIORITY = [
    "openai/gpt-4o-mini",
    "google/gemini-2.0-flash-001",
    "anthropic/claude-3.5-haiku",
    "qwen/qwen-2.5-72b-instruct",
]

FALLBACK = [{"id": m, "price": 0.0, "ctx": 0, "why": "FREE"} for m in FREE_PRIORITY] + \
           [{"id": m, "price": -1.0, "ctx": 0, "why": ""} for m in PAID_PRIORITY]


def _price(m: dict) -> float:
    try:
        return float((m.get("pricing") or {}).get("prompt", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _boleh_teks(mid: str) -> bool:
    n = (mid or "").lower()
    return not any(s in n for s in SKIP_SUBSTR)


def _ctx(m: dict) -> int:
    try:
        return int(m.get("context_length") or m.get("top_provider", {}).get("context_length") or 0)
    except (TypeError, ValueError):
        return 0


def cari_model_free_live() -> tuple[list[dict], str]:
    """ALL live free (price 0) text models, context terbesar dahulu.

    For the Settings browser "free sahaja" view. Fail-soft: ([], nota).
    """
    emit("NET", "OpenRouter GET /models (senarai free live) ...")
    try:
        r = requests.get(MODELS_URL, headers={"User-Agent": "BE2026-filler/1.0"},
                         timeout=TIMEOUT)
        r.raise_for_status()
        semua = r.json().get("data", [])
    except Exception as e:
        emit("WARN", f"Senarai free live gagal: {e}")
        return [], f"free-gagal: {e}"
    rows = sorted(
        ({"id": m["id"], "price": 0.0, "ctx": _ctx(m), "why": "FREE"}
         for m in semua
         if _price(m) == 0 and m.get("id") and _boleh_teks(m.get("id", ""))),
        key=lambda r: (-r["ctx"], r["id"]))
    emit("OK", f"OpenRouter free live: {len(rows)} model.")
    return rows, f"free-live-ok ({len(rows)} model percuma)"


def uji_model_hidup(mid: str, api_key: str = "",
                    timeout: int = 25) -> tuple[bool, str]:
    """Ping satu model OpenRouter (max_tokens=2). Returns (hidup, nota).

    Used by Settings "Uji Live": dead models are dropped from the browser.
    """
    key = ((api_key or "").strip()
           or os.environ.get("OPENROUTER_API_KEY", "").strip())
    if not key:
        return False, "tiada kunci OpenRouter"
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "HTTP-Referer": "be2026-filler", "X-Title": "BE2026 uji"},
            json={"model": mid,
                  "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 2},
            timeout=timeout)
        if r.status_code == 200:
            return True, "OK"
        return False, f"HTTP {r.status_code}"
    except Exception as e:
        return False, f"gagal: {e}"


def cari_model_live(limit: int = 14) -> tuple[list[dict], str]:
    """Live-only ranking for the Settings browser (no hardcoded fallback).

    Returns ([], nota-offline) when the list cannot be fetched, so the
    Settings tab never shows stale hardcoded models.
    """
    ranked, nota = cari_model_terbaik(limit=limit)
    if nota.startswith("offline-fallback"):
        return [], f"live-gagal ({nota}) — semak sambungan."
    return ranked, nota


def cari_model_terbaik(limit: int = 12) -> tuple[list[dict], str]:
    """Pulangan: ([{id, price, ctx, why}], nota). price = USD per 1M prompt token."""
    emit("NET", "OpenRouter GET /models (senarai model live) ...")
    try:
        r = requests.get(MODELS_URL, headers={"User-Agent": "BE2026-filler/1.0"}, timeout=TIMEOUT)
        r.raise_for_status()
        semua = r.json().get("data", [])
        emit("OK", f"OpenRouter: {len(semua)} model diterima, susun ranking ...")
    except Exception as e:
        emit("WARN", f"Senarai model luar talian ({e}) — guna simpanan.")
        return list(FALLBACK[:limit]), f"offline-fallback: {e}"

    by_id = {m.get("id"): m for m in semua if m.get("id")}
    ranked: list[dict] = []
    seen = set()

    def add(mid: str, why: str):
        if mid in seen:
            return
        m = by_id.get(mid)
        if m is None:
            return
        seen.add(mid)
        ranked.append({"id": mid, "price": _price(m), "ctx": _ctx(m), "why": why})

    for mid in FREE_PRIORITY:      # percuma yang dikenali baik
        add(mid, "FREE")
    # percuma lain yang sah (harga 0, model teks), konteks terbesar dahulu
    free_lain = sorted(
        [m for m in semua if _price(m) == 0 and m.get("id") not in seen
         and _boleh_teks(m.get("id", ""))],
        key=_ctx, reverse=True)
    for m in free_lain[:6]:
        seen.add(m["id"])
        ranked.append({"id": m["id"], "price": 0.0, "ctx": _ctx(m), "why": "FREE"})
    # berbayar termurah dengan konteks >= 32k (model teks sahaja)
    berbayar = sorted(
        [m for m in semua if _price(m) > 0 and m.get("id") not in seen and _ctx(m) >= 32000
         and _boleh_teks(m.get("id", ""))],
        key=lambda m: (_price(m), -_ctx(m)))
    for m in berbayar[:6]:
        seen.add(m["id"])
        why = "Murah" if _price(m) < 0.5 else ("Konteks besar" if _ctx(m) >= 200000 else "")
        ranked.append({"id": m["id"], "price": _price(m), "ctx": _ctx(m), "why": why})
    return ranked[:limit], f"live-ok ({len(semua)} model)"
