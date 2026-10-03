"""Simpan tetapan setempat: bahasa, kunci API, penyedia, model. / Local settings."""
from __future__ import annotations
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PATH = ROOT / "config" / "settings.json"

DEFAULTS = {
    "lang": "ms",
    "provider": "auto",          # auto | openrouter | gemini | local | hf
    "model": "openai/gpt-4o-mini",
    "openrouter_key": "",
    "gemini_key": "",
    "hf_key": "",
    "hf_model": "Qwen/Qwen2.5-7B-Instruct",
    "local_url": "http://localhost:4000/v1",
    "local_key": "",
    "local_model": "nvidia/nemotron-3-super-120b-a12b:free",
}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        if PATH.exists():
            data.update(json.loads(PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    # env sentiasa mengatasi fail (mesra CI/server) / env always wins
    if os.environ.get("OPENROUTER_API_KEY"):
        data["openrouter_key"] = os.environ["OPENROUTER_API_KEY"]
    if os.environ.get("GEMINI_API_KEY"):
        data["gemini_key"] = os.environ["GEMINI_API_KEY"]
    if os.environ.get("LOCAL_AI_URL"):
        data["local_url"] = os.environ["LOCAL_AI_URL"]
    if os.environ.get("LOCAL_AI_KEY"):
        data["local_key"] = os.environ["LOCAL_AI_KEY"]
    if os.environ.get("LOCAL_AI_MODEL"):
        data["local_model"] = os.environ["LOCAL_AI_MODEL"]
    if os.environ.get("HF_TOKEN"):
        data["hf_key"] = os.environ["HF_TOKEN"]
    if os.environ.get("HF_API_KEY"):
        data["hf_key"] = os.environ["HF_API_KEY"]
    if os.environ.get("HF_MODEL"):
        data["hf_model"] = os.environ["HF_MODEL"]
    if data.get("lang") not in ("ms", "en"):
        data["lang"] = "ms"
    return data


def save(data: dict) -> None:
    PATH.parent.mkdir(exist_ok=True)
    keep = {k: data.get(k, DEFAULTS[k]) for k in DEFAULTS}
    PATH.write_text(json.dumps(keep, indent=2, ensure_ascii=False), encoding="utf-8")
