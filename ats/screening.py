"""The five stages, wired together. One entry point for both the CLI and the UI.

    intake(paths)          stages 1-2: read files, store what they contain
    shortlist(job)         stages 4-5: rank the whole stored pool against a vacancy

They are separate on purpose. Intake is slow and costs money, and is done once per
CV ever. Shortlisting is free and instant, and is re-run for every vacancy, so a
pool of thousands can be screened against a new job in under a second.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import store
from .config import Settings
from .job_profile import JobProfile
from .stages import match as match_stage
from .stages import normalize, parse, rank


@dataclass
class IntakeEvent:
    """One file, finished. Enough for a caller to show a live status line.

    Reporting only the extracted name hid the two things worth watching: which
    file each result came from, and which files failed.
    """

    filename: str
    status: str          # "added" | "known" | "not_a_cv" | "unreadable" | "failed"
    name: str = ""       # the candidate, once known
    headline: str = ""
    detail: str = ""     # why, when something went wrong

    #: For a terminal or a log line.
    LABELS = {
        "added": "OK  ",
        "known": "SKIP",
        "not_a_cv": "DROP",
        "unreadable": "BAD ",
        "failed": "FAIL",
    }

    @property
    def label(self) -> str:
        return self.LABELS.get(self.status, self.status)

    @property
    def summary(self) -> str:
        if self.status == "added":
            who = self.name or "(no name found)"
            return f"{who} - {self.headline}" if self.headline else who
        if self.status == "known":
            return "already in the pool"
        if self.status == "not_a_cv":
            return f"not a CV ({self.detail})" if self.detail else "not a CV"
        return self.detail or self.status

    def line(self) -> str:
        return f"{self.label}  {self.filename[:40]:<42} {self.summary[:60]}"


@dataclass
class IntakeReport:
    added: int = 0
    already_known: int = 0
    unreadable: int = 0
    failed: int = 0
    not_cvs: int = 0
    errors: list[tuple[str, str]] = None  # (filename, why)
    events: list = field(default_factory=list)   # every file, with its outcome

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    @property
    def total(self) -> int:
        return self.added + self.already_known + self.unreadable + self.failed


def intake(
    paths: list[Path],
    settings: Settings,
    on_progress: Callable[[IntakeEvent, int, int], None] | None = None,
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

    def event_for(result: normalize.NormalizeResult) -> IntakeEvent:
        filename = result.doc.path.name
        if not result.doc.ok:
            return IntakeEvent(filename, "unreadable", detail=result.doc.error)
        if result.error:
            return IntakeEvent(filename, "failed", detail=result.error)
        profile = result.profile
        if profile is None:
            return IntakeEvent(filename, "failed", detail="no record produced")
        if not profile.is_cv:
            return IntakeEvent(
                filename, "not_a_cv",
                detail=profile.document_type.replace("_", " "),
            )
        return IntakeEvent(
            filename,
            "known" if result.from_cache else "added",
            name=profile.full_name,
            headline=profile.headline,
        )

    def progress(result: normalize.NormalizeResult, done: int, total: int) -> None:
        if on_progress:
            on_progress(event_for(result), done, total)

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
        report.events.append(event_for(result))

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
