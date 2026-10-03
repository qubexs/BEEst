"""Deploy profiles: named xlsx-export presets for future reuse.

Each profile stores the source template, sheet, save-as path, force flag
and the manual cell-override map. Persisted to config/deploy_profiles.json.
Cell overrides are also mirrored into config/cell_overrides.json on apply
so Imbas Peta shows them immediately.
"""
from __future__ import annotations
import json
from pathlib import Path

PROFIL_FILE = Path(__file__).resolve().parent.parent / "config" / "deploy_profiles.json"


def list_profiles() -> list[str]:
    try:
        if PROFIL_FILE.exists():
            d = json.loads(PROFIL_FILE.read_text(encoding="utf-8"))
            return sorted(k for k, v in d.items() if isinstance(v, dict))
    except Exception:
        pass
    return []


def load_profile(name: str) -> dict:
    try:
        if PROFIL_FILE.exists():
            d = json.loads(PROFIL_FILE.read_text(encoding="utf-8"))
            p = d.get(name)
            if isinstance(p, dict):
                return {"src": p.get("src", ""), "sheet": p.get("sheet", ""),
                        "out": p.get("out", ""),
                        "force": bool(p.get("force", False)),
                        "overrides": dict(p.get("overrides", {}) or {})}
    except Exception:
        pass
    return {}


def save_profile(name: str, src: str, sheet: str, out: str,
                 force: bool, overrides: dict) -> None:
    from kp205.xlsx_fill import valid_sel
    try:
        all_p = json.loads(PROFIL_FILE.read_text(encoding="utf-8")) \
            if PROFIL_FILE.exists() else {}
    except Exception:
        all_p = {}
    all_p[name] = {"src": src, "sheet": sheet, "out": out,
                   "force": bool(force),
                   "overrides": {k: v for k, v in (overrides or {}).items()
                                 if valid_sel(v)}}
    PROFIL_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFIL_FILE.write_text(json.dumps(all_p, indent=2, ensure_ascii=False),
                           encoding="utf-8")


def delete_profile(name: str) -> bool:
    try:
        if PROFIL_FILE.exists():
            all_p = json.loads(PROFIL_FILE.read_text(encoding="utf-8"))
            if name in all_p:
                del all_p[name]
                PROFIL_FILE.write_text(
                    json.dumps(all_p, indent=2, ensure_ascii=False),
                    encoding="utf-8")
                return True
    except Exception:
        pass
    return False


def describe(name: str) -> str:
    p = load_profile(name)
    if not p:
        return "—"
    n_ov = len(p.get("overrides", {}))
    return (f"{Path(p.get('src', '')).name} :: {p.get('sheet', '')} | "
            f"{n_ov} override | force={'YA' if p.get('force') else 'tidak'}")
