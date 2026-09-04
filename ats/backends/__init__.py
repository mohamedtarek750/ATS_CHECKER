"""Choosing where applications are kept.

Local files by default, so the app runs with no accounts and no credentials.
Two ways to reach a Google Sheet instead, and the difference is only in how the
door is opened:

  ATS_BACKEND=script   through an Apps Script the sheet runs itself. No cloud
                       project, no service account, no API key - the script
                       already has the owner's access. Two settings, and the
                       right choice for a prototype.
  ATS_BACKEND=sheets   through the Google Sheets API, which needs a service
                       account and a key file. More setup, and the one to use
                       once real applicants are in it, because the endpoint is
                       not open to whoever holds a URL.
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
    if name in {"script", "apps_script", "gs"}:
        from .script import ScriptBackend

        return ScriptBackend()
    if name in {"sheets", "google"}:
        from .sheets import SheetsBackend

        return SheetsBackend()
    from .local import LocalBackend

    return LocalBackend()
