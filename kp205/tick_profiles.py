"""Tick profiles for the Profil tab: named tick/untick presets.

Built-in per-section sets + IO-core set, plus user profiles persisted
to config/tick_profiles.json. A profile resolves to a set of TICKED
field ids; everything else is unticked (stays kosong on Jana).
"""
from __future__ import annotations
import json
from pathlib import Path

PROFIL_FILE = Path(__file__).resolve().parent.parent / "config" / "tick_profiles.json"

# section sets (resolved against loaded fields at apply time)
BUILTIN_SECTIONS = {
    "Kewangan sahaja": {"PENDAPATAN", "PERBELANJAAN"},
    "Pekerja sahaja": {"PEKERJA", "GAJI", "SHIFT", "PENDIDIKAN"},
    "Aset + Stok": {"ASET", "STOK"},
}

# exact IO-critical field ids (ticked; rest unticked)
TERAS_IO = {
    "PENDAPATAN::8.13", "PENDAPATAN::8.15",
    "PERBELANJAAN::9.39", "PERBELANJAAN::9.44",
    "PERBELANJAAN::9.29",
    "PERBELANJAAN::9.36(a)", "PERBELANJAAN::9.36(b)",
    "PERBELANJAAN::9.36(c)(i)", "PERBELANJAAN::9.36(c)(ii)",
    "PERBELANJAAN::9.36(d)(i)", "PERBELANJAAN::9.36(d)(ii)",
    "PERBELANJAAN::9.36(d)(iii)", "PERBELANJAAN::9.36(d)(iv)",
    "PERBELANJAAN::9.36(d)(v)", "PERBELANJAAN::9.36(e)",
    "PERBELANJAAN::9.36(f)", "PERBELANJAAN::9.36(g)",
    "PERBELANJAAN::9.36(h)", "PERBELANJAAN::9.36(i)",
    "PERBELANJAAN::9.36(j)", "PERBELANJAAN::9.36(k)",
    "ASET::Jumlah",
}

BUILTINS = ["Semua", "Kewangan sahaja", "Pekerja sahaja", "Aset + Stok",
            "Teras IO"]


def _key(f: dict) -> str:
    return f.get("fid") or f.get("id") or f.get("label", "")


def load_custom() -> dict:
    """{name: [ticked ids]}."""
    try:
        if PROFIL_FILE.exists():
            d = json.loads(PROFIL_FILE.read_text(encoding="utf-8"))
            return {k: list(v) for k, v in d.items() if isinstance(v, list)}
    except Exception:
        pass
    return {}


def save_custom(name: str, ticked: set | list) -> None:
    d = load_custom()
    d[name] = sorted(ticked)
    PROFIL_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFIL_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False),
                           encoding="utf-8")


def delete_custom(name: str) -> None:
    d = load_custom()
    if name in d:
        del d[name]
        PROFIL_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False),
                               encoding="utf-8")


def list_profiles() -> list[tuple[str, str]]:
    """[(name, kind)] kind: builtin/custom."""
    return [(n, "builtin") for n in BUILTINS] + \
        [(n, "custom") for n in sorted(load_custom())]


def resolve(name: str, fields: list[dict]) -> set:
    """Ticked field ids for a profile name."""
    if name == "Semua":
        return {_key(f) for f in fields}
    if name == "Teras IO":
        have = {_key(f) for f in fields}
        return set(TERAS_IO) & have
    if name in BUILTIN_SECTIONS:
        secs = BUILTIN_SECTIONS[name]
        return {_key(f) for f in fields if f.get("section") in secs}
    custom = load_custom()
    if name in custom:
        have = {_key(f) for f in fields}
        return set(custom[name]) & have
    return set()


def describe(name: str, fields: list[dict]) -> str:
    ticked = resolve(name, fields)
    from collections import Counter
    by_id = {_key(f): f for f in fields}
    secs = Counter(by_id[i]["section"] for i in ticked if i in by_id)
    parts = [f"{s}: {n}" for s, n in sorted(secs.items())]
    return f"{len(ticked)} ditanda — " + (", ".join(parts) if parts else "—")
