"""Choosing where applications are kept.

Local files by default, so the app runs with no accounts and no credentials.
Set ATS_BACKEND=sheets to keep everything in a Google Sheet and Drive folder
instead, which is what a recruiter who wants to open the data themselves gets.
"""

from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_backend = None


def get_backend():
    """The configured backend. Built once and reused."""
    global _backend
    with _lock:
        if _backend is None:
            _backend = _build()
        return _backend


def reset() -> None:
    """Forget the cached backend. For tests, and for a changed configuration."""
    global _backend
    with _lock:
        _backend = None


def backend_name() -> str:
    return (os.getenv("ATS_BACKEND") or "local").strip().lower()


def _build():
    name = backend_name()
    if name in {"sheets", "google"}:
        from .sheets import SheetsBackend

        return SheetsBackend()
    from .local import LocalBackend

    return LocalBackend()
