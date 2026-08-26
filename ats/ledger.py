"""An append-only record of what has already been screened.

A long batch is fragile: a browser tab sleeping, a dropped connection, an exhausted
daily quota, or a laptop lid closing will all end a run part-way. Without a ledger
the completed work is lost and the whole batch has to be paid for and waited on
again.

Each result is appended the moment it is produced, so a killed run keeps everything
it finished, and re-running only screens what is actually left.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

_write_lock = threading.Lock()

LEDGER_NAME = "screened.jsonl"


def ledger_path(settings) -> Path:
    return settings.reports_dir / LEDGER_NAME


def key_for(path: Path) -> str:
    """Identify a CV by name and size.

    Not the full path: the same file arrives at a different absolute path when it
    is re-uploaded through the UI. Not the content hash either - reading every file
    twice to save an API call is the wrong trade when size already separates a
    replaced CV from the one already screened.
    """
    try:
        size = path.stat().st_size
    except OSError:
        size = -1
    return f"{path.name}|{size}"


def load_done(settings, job: str = "") -> dict[str, dict]:
    """Rows from previous runs that reached a real verdict, keyed by `key_for`.

    Entries recorded as errors are deliberately excluded - a CV that failed because
    the quota ran out has not been screened, and must be retried rather than
    treated as finished.
    """
    path = ledger_path(settings)
    if not path.exists():
        return {}

    done: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue          # a half-written line from a killed run
            if row.get("status") == "error":
                continue
            # A CV screened against one job says nothing about another job.
            if job and row.get("job_title", "") != job:
                continue
            key = row.get("_key")
            if key:
                done[key] = row
    return done


def record(settings, result, key: str) -> None:
    """Append one result. Called as each CV finishes, not at the end of the run."""
    path = ledger_path(settings)
    row = asdict(result)
    row["_key"] = key
    line = json.dumps(row, ensure_ascii=False)
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()


def clear(settings) -> bool:
    """Forget the history so the next run screens everything again."""
    path = ledger_path(settings)
    if path.exists():
        path.unlink()
        return True
    return False
