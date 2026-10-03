"""Bas peristiwa aktiviti / Activity event bus.

Modul carian/AI memanggil emit() pada setiap langkah penting
(permintaan HTTP, respons, keputusan) dan tab Terminal memaparkannya live.
Semua panggilan segerak (UI thread) — tiada lock diperlukan.
"""
from __future__ import annotations
from datetime import datetime

_subscribers: list = []


def subscribe(fn) -> None:
    if fn not in _subscribers:
        _subscribers.append(fn)


def unsubscribe(fn) -> None:
    try:
        _subscribers.remove(fn)
    except ValueError:
        pass


def emit(tag: str, msg: str) -> None:
    """tag: INFO | OK | WARN | ERR | AI | NET"""
    stamp = datetime.now().strftime("%H:%M:%S")
    for fn in list(_subscribers):
        try:
            fn(stamp, tag, str(msg))
        except Exception:
            pass


class Stopped(Exception):
    """Dibangkit bila pengguna tekan Berhenti semasa kerja latar berjalan."""
    pass
