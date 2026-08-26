"""Orchestration: discover -> extract -> classify -> decide -> route -> report."""

from __future__ import annotations

import csv
import json
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
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
from .decision import Decision, decide, rejection_for_broken_file, screening_failure
from .extract import extract
from .router import prepare_tree, route
from .schema import Verdict

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
    model_used: str = ""
    error: str = ""
    elapsed_seconds: float = 0.0

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    @property
    def errored(self) -> bool:
        return self.status == "error"


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


def screen_one(
    path: Path, settings: Settings, abort: Abort | None = None
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
) -> list[ScreenResult]:
    """Screen files concurrently, reporting each completion through `on_progress`."""
    paths = list(paths)
    prepare_tree(settings)
    results: list[ScreenResult] = []
    total = len(paths)

    if total == 0:
        return results

    abort = Abort()
    workers = max(1, min(settings.max_workers, total))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(screen_one, p, settings, abort): p for p in paths}
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if on_progress:
                on_progress(result, done, total)

    results.sort(key=lambda r: (r.status, r.role_folder, r.filename))
    return results


CSV_COLUMNS = [
    "filename",
    "status",
    "reason",
    "role_label",
    "role_folder",
    "specialization",
    "candidate_name",
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
    for result in results:
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
        "rejected_by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
    }
