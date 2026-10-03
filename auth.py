"""Local login gate for the desktop apps (admin/7717 by default).

Users live in config/auth.json as {username: sha256(password)} — never
plaintext. First run creates the default admin account automatically.
Both entry points (kp205_viewer.py, app.py) call ensure_default() +
ask_login() before opening the main window.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

AUTH_FILE = Path(__file__).resolve().parent / "config" / "auth.json"

DEFAULT_USER = "admin"
DEFAULT_PASS = "7717"
MAX_ATTEMPTS = 3


def _sha(pw: str) -> str:
    return hashlib.sha256((pw or "").encode("utf-8")).hexdigest()


def _read() -> dict:
    try:
        if AUTH_FILE.exists():
            d = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return {str(k): str(v) for k, v in d.items()}
    except Exception:
        pass
    return {}


def ensure_default() -> dict:
    """Create config/auth.json with the default admin if missing."""
    users = _read()
    if DEFAULT_USER not in users:
        users[DEFAULT_USER] = _sha(DEFAULT_PASS)
        try:
            AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            AUTH_FILE.write_text(json.dumps(users, indent=2),
                                 encoding="utf-8")
        except Exception:
            pass
    return users


def verify(username: str, password: str) -> bool:
    """True if the pair matches (timing-safe compare)."""
    import hmac
    users = _read()
    want = users.get((username or "").strip(), "")
    if not want:
        return False
    return hmac.compare_digest(want, _sha(password or ""))


def set_password(username: str, new_password: str) -> bool:
    """Change (or add) a user. Returns False on empty input/write error."""
    if not (username or "").strip() or not (new_password or ""):
        return False
    try:
        users = _read()
        users[username.strip()] = _sha(new_password)
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def ask_login(parent=None) -> bool:
    """Modal login dialog. Returns True on success, False on cancel/fail."""
    import tkinter as tk
    from tkinter import ttk

    ensure_default()
    result = {"ok": False, "tries": 0}

    dlg = tk.Toplevel(parent)
    dlg.title("Log Masuk / Login")
    dlg.geometry("320x190")
    dlg.resizable(False, False)
    dlg.transient(parent)
    dlg.grab_set()
    try:
        dlg.focus_force()
    except Exception:
        pass

    ttk.Label(dlg, text="Nama pengguna:").pack(anchor="w", padx=16, pady=(14, 0))
    ent_u = ttk.Entry(dlg, width=30)
    ent_u.pack(padx=16, pady=2)
    ent_u.insert(0, DEFAULT_USER)
    ttk.Label(dlg, text="Kata laluan:").pack(anchor="w", padx=16, pady=(6, 0))
    ent_p = ttk.Entry(dlg, width=30, show="*")
    ent_p.pack(padx=16, pady=2)
    lbl = ttk.Label(dlg, text="", foreground="#b3261e")
    lbl.pack(padx=16)

    def _submit(_e=None):
        if verify(ent_u.get(), ent_p.get()):
            result["ok"] = True
            dlg.destroy()
            return
        result["tries"] += 1
        left = MAX_ATTEMPTS - result["tries"]
        if left <= 0:
            dlg.destroy()
            return
        lbl.configure(text=f"Salah — tinggal {left} cubaan.")
        ent_p.delete(0, "end")
        ent_p.focus()

    def _cancel():
        dlg.destroy()

    bar = ttk.Frame(dlg)
    bar.pack(fill="x", padx=16, pady=8)
    ttk.Button(bar, text="Masuk", command=_submit).pack(side="left")
    ttk.Button(bar, text="Batal", command=_cancel).pack(side="right")
    ent_p.focus()
    dlg.bind("<Return>", _submit)
    dlg.bind("<Escape>", lambda e: _cancel())
    dlg.protocol("WM_DELETE_WINDOW", _cancel)
    dlg.wait_window()
    return bool(result["ok"])
