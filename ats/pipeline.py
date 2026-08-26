"""Orchestration: discover -> extract -> classify -> decide -> route -> report."""

from __future__ import annotations

import csv
import json
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import datetime
from pathlib import Path

from .classifier import (
    ClassificationError,
    FatalScreeningError,
    active_model,
    classify,
    credentials_message,
    has_credentials,
)
from .config import SUPPORTED_EXTENSIONS, Settings
from .decision import (
    Decision,
    decide,
    decide_match,
    rejection_for_broken_file,
    screening_failure,
)
from .job_profile import JobProfile
from . import ledger
from .matcher import match
from .extract import extract
from .router import prepare_tree, route
from .schema import MatchVerdict, Verdict

_route_lock = threading.Lock()


@dataclass
class Abort:
    """Shared stop signal for one run.

    Set by the first worker that hits an account-level failure. Every other CV in
    the batch would fail identically, so they are marked unscreened without
    spending another API call.
    """

    event: threading.Event = field(default_factory=threading.Event)
    reason: str = ""

    def trip(self, reason: str) -> None:
        self.reason = reason
        self.event.set()

    @property
    def tripped(self) -> bool:
        return self.event.is_set()


@dataclass
class ScreenResult:
    source: str
    filename: str
    status: str
    reason: str
    role_label: str
    role_folder: str
    destination: str = ""
    candidate_name: str = ""
    email: str = ""
    phone: str = ""
    specialization: str = ""
    major: str = ""
    seniority: str = ""
    years_experience: float = 0.0
    role_confidence: int = 0
    ai_generated_score: int = 0
    format_score: int = 0
    professionalism_score: int = 0
    quality_score: int = 0
    top_skills: list[str] = field(default_factory=list)
    ai_signals: list[str] = field(default_factory=list)
    human_signals: list[str] = field(default_factory=list)
    explanation: str = ""
    # --- job-description mode ---
    job_title: str = ""
    overall: str = ""
    must_haves_met: int = 0
    must_haves_total: int = 0
    met: list[str] = field(default_factory=list)
    # Must-haves only. A missing nice-to-have is not a shortfall and must not
    # be shown as one - it reads as a reason for rejection when it is not.
    missing: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    model_used: str = ""
    error: str = ""
    elapsed_seconds: float = 0.0

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    @property
    def errored(self) -> bool:
        return self.status == "error"

    def summary_line(self) -> str:
        """Short, plain-language line for a terminal shortlist."""
        if self.missing:
            return "short on " + ", ".join(self.missing[:2])
        if self.strengths:
            return self.strengths[0][:60]
        return "meets every must-have"


def _result_from(
    source: Path,
    decision: Decision,
    verdict: Verdict | None,
    elapsed: float,
    error: str = "",
) -> ScreenResult:
    result = ScreenResult(
        source=str(source),
        filename=source.name,
        status=decision.status,
        reason=decision.reason,
        role_label=decision.role_label,
        role_folder=decision.role_folder,
        explanation=decision.explanation,
        error=error,
        elapsed_seconds=round(elapsed, 2),
    )
    if verdict is not None:
        result.candidate_name = verdict.candidate_name
        result.email = verdict.email
        result.phone = verdict.phone
        result.specialization = verdict.specialization
        result.major = verdict.major
        result.seniority = verdict.seniority
        result.years_experience = verdict.years_experience
        result.role_confidence = verdict.role_confidence
        result.ai_generated_score = verdict.ai_generated_score
        result.format_score = verdict.format_score
        result.professionalism_score = verdict.professionalism_score
        result.quality_score = verdict.quality_score
        result.top_skills = verdict.top_skills
        result.ai_signals = verdict.ai_signals
        result.human_signals = verdict.human_signals
    return result


def _result_from_row(row: dict) -> ScreenResult:
    """Rebuild a result recorded by an earlier run."""
    fields = {f.name for f in dataclass_fields(ScreenResult)}
    return ScreenResult(**{k: v for k, v in row.items() if k in fields})


def preflight(settings: Settings) -> str:
    """Return an error message if a run cannot possibly succeed, else ''.

    Checked before screening so a missing key fails once, loudly, instead of
    turning every CV in the batch into a failure record.
    """
    if not has_credentials(settings):
        return credentials_message(settings)
    return ""


def discover(inbox: Path) -> list[Path]:
    """Every supported CV file under `inbox`, recursively, sorted by name."""
    if not inbox.exists():
        return []
    if inbox.is_file():
        return [inbox]
    return sorted(
        p
        for p in inbox.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def _fill_match(result: ScreenResult, verdict: MatchVerdict, profile: JobProfile) -> None:
    result.candidate_name = verdict.candidate_name
    result.email = verdict.email
    result.phone = verdict.phone
    result.years_experience = verdict.years_experience
    result.seniority = verdict.current_title
    result.ai_generated_score = verdict.ai_generated_score
    result.ai_signals = verdict.ai_signals
    result.job_title = profile.title
    result.overall = verdict.overall
    result.must_haves_met = verdict.must_haves_met
    result.must_haves_total = verdict.must_haves_total
    result.met = [m.requirement for m in verdict.requirement_matches if m.status == "met"]
    result.missing = [
        m.requirement
        for m in verdict.must_have_matches
        if m.status in {"not_met", "partial"}
    ]
    result.missing_optional = [
        m.requirement
        for m in verdict.requirement_matches
        if m.importance == "nice_to_have" and m.status == "not_met"
    ]
    result.strengths = verdict.strengths
    result.gaps = verdict.gaps


def screen_one(
    path: Path,
    settings: Settings,
    abort: Abort | None = None,
    profile: JobProfile | None = None,
) -> ScreenResult:
    """Full screening of a single file. Never raises."""
    started = time.perf_counter()

    if abort is not None and abort.tripped:
        decision = screening_failure(f"Run stopped before this file. {abort.reason}")
        result = _result_from(path, decision, None, 0.0, abort.reason)
        if not settings.dry_run:
            with _route_lock:
                try:
                    result.destination = str(route(path, decision, settings))
                except OSError:
                    pass
        return result

    doc = extract(path)
    used = ""

    if doc.error:
        decision = rejection_for_broken_file(doc, doc.error)
        verdict: Verdict | None = None
        error = doc.error
    else:
        try:
            if profile is not None:
                verdict = match(doc, profile, settings)
                decision = decide_match(verdict, doc, profile, settings)
            else:
                verdict = classify(doc, settings)
                decision = decide(verdict, doc, settings)
            error = ""
            # Read straight after the call: failover is sticky, so this is the
            # model that actually produced this verdict.
            used = active_model(settings)
        except ClassificationError as exc:
            # The CV was never judged. Do not record it as a rejection.
            verdict = None
            decision = screening_failure(str(exc))
            error = str(exc)
            if isinstance(exc, FatalScreeningError) and abort is not None:
                abort.trip(str(exc))

    if isinstance(verdict, MatchVerdict):
        result = _result_from(path, decision, None, time.perf_counter() - started, error)
        _fill_match(result, verdict, profile)  # type: ignore[arg-type]
    else:
        result = _result_from(path, decision, verdict, time.perf_counter() - started, error)
    result.model_used = used

    if settings.dry_run:
        result.destination = "(dry run - not filed)"
    else:
        with _route_lock:
            try:
                result.destination = str(route(path, decision, settings))
            except OSError as exc:
                result.error = (result.error + f" | Could not file the CV: {exc}").strip(" |")

    if verdict is not None:
        _write_detail(path, result, verdict, settings)
    return result


def _write_detail(
    path: Path, result: ScreenResult, verdict: Verdict, settings: Settings
) -> None:
    details_dir = settings.reports_dir / "details"
    details_dir.mkdir(parents=True, exist_ok=True)
    payload = {"result": asdict(result), "verdict": verdict.model_dump()}
    target = details_dir / f"{path.stem}.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def screen_many(
    paths: Iterable[Path],
    settings: Settings,
    on_progress: Callable[[ScreenResult, int, int], None] | None = None,
    profile: JobProfile | None = None,
    resume: bool = True,
) -> list[ScreenResult]:
    """Screen files concurrently, reporting each completion through `on_progress`.

    Every result is written to the ledger the moment it is produced, and by default
    a CV already recorded there is not screened again. A run that dies half way -
    a dropped browser connection, a spent quota, a closed laptop - therefore keeps
    everything it finished, and re-running costs only what is genuinely left.
    """
    paths = list(paths)
    prepare_tree(settings)
    results: list[ScreenResult] = []

    already: dict[str, dict] = {}
    if resume and not settings.dry_run:
        already = ledger.load_done(settings, profile.title if profile else "")
        if already:
            pending = [p for p in paths if ledger.key_for(p) not in already]
            for path in paths:
                row = already.get(ledger.key_for(path))
                if row is not None:
                    results.append(_result_from_row(row))
            paths = pending

    total = len(paths)
    if total == 0:
        results.sort(key=lambda r: (r.status, r.role_folder, r.filename))
        return results

    abort = Abort()
    workers = max(1, min(settings.max_workers, total))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(screen_one, p, settings, abort, profile): p for p in paths
        }
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if not settings.dry_run:
                ledger.record(settings, result, ledger.key_for(futures[future]))
            if on_progress:
                on_progress(result, done, total)

    results.sort(key=lambda r: (r.status, r.role_folder, r.filename))
    return results


CSV_COLUMNS = [
    "filename",
    "candidate_name",
    "overall",
    "must_haves_met",
    "must_haves_total",
    "missing",
    "status",
    "reason",
    "job_title",
    "role_label",
    "role_folder",
    "specialization",
    "email",
    "phone",
    "major",
    "seniority",
    "years_experience",
    "role_confidence",
    "ai_generated_score",
    "format_score",
    "professionalism_score",
    "quality_score",
    "explanation",
    "model_used",
    "destination",
    "error",
]


def write_reports(results: list[ScreenResult], settings: Settings) -> dict[str, Path]:
    """Write the run's CSV + JSON report. Returns the paths written."""
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    csv_path = settings.reports_dir / f"report_{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))

    json_path = settings.reports_dir / f"report_{stamp}.json"
    json_path.write_text(
        json.dumps(
            {"generated_at": stamp, "summary": summarize(results),
             "results": [asdict(r) for r in results]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"csv": csv_path, "json": json_path}


def summarize(results: list[ScreenResult]) -> dict:
    """Counts for the CLI footer and the Streamlit metrics row."""
    by_reason: dict[str, int] = {}
    by_role: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    for result in results:
        if result.overall:
            by_outcome[result.overall] = by_outcome.get(result.overall, 0) + 1
        if result.accepted:
            by_role[result.role_label] = by_role.get(result.role_label, 0) + 1
        elif not result.errored:
            by_reason[result.reason] = by_reason.get(result.reason, 0) + 1
    return {
        "total": len(results),
        "accepted": sum(1 for r in results if r.accepted),
        "rejected": sum(1 for r in results if r.status == "rejected"),
        "errors": sum(1 for r in results if r.errored),
        "accepted_by_role": dict(sorted(by_role.items(), key=lambda kv: -kv[1])),
        "by_outcome": by_outcome,
        "rejected_by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
    }
