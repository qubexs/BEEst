"""In-app updater: compare local version.py against GitHub master.

Feed = raw version.py on master (__version__ + CHANGELOG parsed by regex),
so release notes written in version.py ARE the update preview text.

Safety contract for do_update():
- `git pull --ff-only` ONLY. NEVER reset --hard / checkout . / clean.
- User files (untracked work, gitignored settings/auth, own xlsx/txt)
  are never touched or deleted. If fast-forward is impossible, abort
  with a message and change nothing.
All network use is fail-soft (offline -> "unknown", never an error popup).
"""
from __future__ import annotations
import re
import subprocess
from pathlib import Path

import version as _local

FEED_URL = ("https://raw.githubusercontent.com/qubexs/BEEst/"
            "master/version.py")
TIMEOUT = 15
ROOT = Path(__file__).resolve().parent


def local_version() -> str:
    return getattr(_local, "__version__", "0.0.0")


def _parse_feed(text: str) -> tuple[str, list[str]]:
    m = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", text or "")
    ver = m.group(1).strip() if m else ""
    notes: list[str] = []
    m2 = re.search(r"CHANGELOG\s*=\s*\[(.*?)\]", text or "", re.S)
    if m2:
        notes = re.findall(r"\"([^\"]+)\"|'([^']+)'", m2.group(1))
        notes = [(a or b).strip() for a, b in notes if (a or b).strip()]
    return ver, notes


def _newer(remote: str, local: str) -> bool:
    def parts(v: str) -> list:
        return [(int(p) if p.isdigit() else p)
                for p in re.split(r"[.\-]", (v or "").strip()) if p != ""]

    try:
        return parts(remote) > parts(local)
    except Exception:
        return False


def check_remote() -> tuple[bool | None, str, list[str], str]:
    """Returns (has_update|None offline, remote_ver, changelog, msg)."""
    try:
        import requests
        r = requests.get(FEED_URL, timeout=TIMEOUT)
        r.raise_for_status()
        ver, notes = _parse_feed(r.text)
        if not ver:
            return None, "", [], "suapan versi tidak dapat dibaca"
        if _newer(ver, local_version()):
            return True, ver, notes, f"kemas kini tersedia: {ver}"
        return False, ver, [], f"sudah terkini ({local_version()})"
    except Exception as e:
        return None, "", [], f"semakan dilangkau: {e}"


def can_git_pull() -> bool:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-dir"],
                           capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def do_update() -> tuple[bool, str]:
    """Background-safe pull. Returns (ok, msg). Never destructive."""
    if not can_git_pull():
        return (False,
                "Bukan pemasangan git — jalankan semula arahan setup "
                "satu-baris dalam README untuk kemas kini, atau muat turun "
                "ZIP dari https://github.com/qubexs/BEEst.")
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), "pull", "--ff-only"],
            capture_output=True, text=True, timeout=180)
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if r.returncode == 0:
            if "Already up to date" in out or "Sudah" in out:
                return True, "Sudah terkini — tiada yang dimuat turun."
            return True, ("Kemas kini dimuat turun (fail anda tidak "
                          "disentuh). Sila tutup dan buka semula aplikasi.\n"
                          + out[-400:])
        return (False,
                "Update dibatalkan dengan selamat (tiada fail diubah) — "
                "ada perubahan setempat yang menghalang fast-forward. "
                "Commit/stash dahulu, atau muat turun ZIP.\n" + out[-400:])
    except Exception as e:
        return False, f"Update gagal tanpa sebarang perubahan: {e}"
