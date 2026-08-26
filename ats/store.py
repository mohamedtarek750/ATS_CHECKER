"""Where parsed candidates live, so a CV is never parsed twice.

SQLite rather than files: at a few thousand candidates a directory scan and a JSON
parse per lookup becomes the slow part, and this is the table every later stage
reads. It is stdlib, single-file, and needs no server.

Keyed by a hash of the extracted text, not the filename: the same CV re-uploaded
under a different name, or sent again for a second vacancy, is recognised as
already parsed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import CandidateProfile

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    doc_hash      TEXT PRIMARY KEY,
    source_name   TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    parsed_at     TEXT NOT NULL,
    model_used    TEXT NOT NULL DEFAULT '',
    is_cv         INTEGER NOT NULL DEFAULT 1,
    full_name     TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',
    headline      TEXT NOT NULL DEFAULT '',
    profile_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidates_email ON candidates(email);
CREATE INDEX IF NOT EXISTS idx_candidates_name  ON candidates(source_name);
"""


def db_path(settings) -> Path:
    path = settings.output_dir / "candidates.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def doc_hash(text: str) -> str:
    """Identify a CV by its content, so re-uploads and renames are recognised."""
    return hashlib.sha256(text.strip().encode("utf-8", "replace")).hexdigest()[:32]


@contextmanager
def connect(settings):
    conn = sqlite3.connect(db_path(settings), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def get(settings, key: str) -> CandidateProfile | None:
    with connect(settings) as conn:
        row = conn.execute(
            "SELECT profile_json FROM candidates WHERE doc_hash = ?", (key,)
        ).fetchone()
    if row is None:
        return None
    try:
        return CandidateProfile.model_validate_json(row["profile_json"])
    except Exception:      # a row written by an older schema
        return None


def known_hashes(settings) -> set[str]:
    """Every CV already parsed. Used to skip work before any API call is made."""
    with connect(settings) as conn:
        return {r["doc_hash"] for r in conn.execute("SELECT doc_hash FROM candidates")}


def put(
    settings,
    key: str,
    profile: CandidateProfile,
    source: Path,
    model_used: str = "",
) -> None:
    with _lock, connect(settings) as conn:
        conn.execute(
            """
            INSERT INTO candidates
                (doc_hash, source_name, source_path, parsed_at, model_used,
                 is_cv, full_name, email, headline, profile_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_hash) DO UPDATE SET
                source_name  = excluded.source_name,
                source_path  = excluded.source_path,
                parsed_at    = excluded.parsed_at,
                model_used   = excluded.model_used,
                profile_json = excluded.profile_json
            """,
            (
                key,
                source.name,
                str(source),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                model_used,
                int(profile.is_cv),
                profile.full_name,
                profile.email.lower(),
                profile.headline,
                profile.model_dump_json(),
            ),
        )


def all_candidates(settings, cvs_only: bool = True) -> list[tuple[str, str, CandidateProfile]]:
    """Every stored candidate as (hash, source filename, profile)."""
    query = "SELECT doc_hash, source_name, profile_json FROM candidates"
    if cvs_only:
        query += " WHERE is_cv = 1"
    out: list[tuple[str, str, CandidateProfile]] = []
    with connect(settings) as conn:
        for row in conn.execute(query):
            try:
                out.append(
                    (
                        row["doc_hash"],
                        row["source_name"],
                        CandidateProfile.model_validate_json(row["profile_json"]),
                    )
                )
            except Exception:
                continue
    return out


def stats(settings) -> dict:
    with connect(settings) as conn:
        total = conn.execute("SELECT COUNT(*) c FROM candidates").fetchone()["c"]
        cvs = conn.execute(
            "SELECT COUNT(*) c FROM candidates WHERE is_cv = 1"
        ).fetchone()["c"]
    return {"total": total, "cvs": cvs, "not_cvs": total - cvs}


def forget_all(settings) -> int:
    with _lock, connect(settings) as conn:
        count = conn.execute("SELECT COUNT(*) c FROM candidates").fetchone()["c"]
        conn.execute("DELETE FROM candidates")
    return count
