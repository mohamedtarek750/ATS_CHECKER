"""The five stages, wired together. One entry point for both the CLI and the UI.

    intake(paths)          stages 1-2: read files, store what they contain
    shortlist(job)         stages 4-5: rank the whole stored pool against a vacancy

They are separate on purpose. Intake is slow and costs money, and is done once per
CV ever. Shortlisting is free and instant, and is re-run for every vacancy, so a
pool of thousands can be screened against a new job in under a second.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import store
from .config import Settings
from .job_profile import JobProfile
from .stages import match as match_stage
from .stages import normalize, parse, rank


@dataclass
class IntakeReport:
    added: int = 0
    already_known: int = 0
    unreadable: int = 0
    failed: int = 0
    not_cvs: int = 0
    errors: list[tuple[str, str]] = None  # (filename, why)

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    @property
    def total(self) -> int:
        return self.added + self.already_known + self.unreadable + self.failed


def intake(
    paths: list[Path],
    settings: Settings,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> IntakeReport:
    """Stages 1-2. Read every file and store what it contains.

    Anything already stored is skipped without an API call, so re-running an
    interrupted batch costs only what is genuinely left.
    """
    # Only files that still need reading are extracted; the rest are recognised
    # from the index without being opened.
    known = store.known_hashes(settings)
    keys = parse.index_keys(paths, settings)
    to_read = [p for p in paths if keys.get(p) not in known]

    docs = parse.parse_many(to_read, settings)
    report = IntakeReport()
    # Files skipped before any reading. The loop below only sees `to_read`, so
    # these are counted here once and never again.
    report.already_known = len(paths) - len(to_read)

    for doc in docs:
        if not doc.ok:
            report.unreadable += 1
            report.errors.append((doc.path.name, doc.error))

    def progress(result: normalize.NormalizeResult, done: int, total: int) -> None:
        if on_progress:
            who = result.profile.full_name if result.profile else result.doc.path.name
            on_progress(who or result.doc.path.name, done, total)

    results = normalize.normalize_many(docs, settings, on_progress=progress)

    for result in results:
        if not result.doc.ok:
            continue                      # already counted as unreadable
        if result.error:
            report.failed += 1
            report.errors.append((result.doc.path.name, result.error))
        elif result.from_cache:
            pass          # already counted in the pre-count above
        else:
            report.added += 1
        if result.profile is not None and not result.profile.is_cv:
            report.not_cvs += 1

    return report


def pending_count(paths: list[Path], settings: Settings) -> int:
    """How many of these still need a model call.

    Deliberately does not read the files. Answering this question by re-extracting
    every PDF made every interaction in the UI cost about 50 ms per file - a second
    per click at 20 CVs, a minute at a thousand.
    """
    known = store.known_hashes(settings)
    keys = parse.index_keys(paths, settings)
    return sum(1 for key in keys.values() if key not in known)


def shortlist(job: JobProfile, settings: Settings) -> list[rank.RankedCandidate]:
    """Stages 4-5 over every stored candidate. No API calls, no configuration."""
    pool = [
        (source, profile)
        for _hash, source, profile in store.all_candidates(settings, cvs_only=False)
    ]
    matches = match_stage.match_all(pool, job)
    return rank.rank(matches)
