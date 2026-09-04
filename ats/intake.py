"""Taking an application in, and reading it. Backend-agnostic.

Two steps on purpose, and the order matters:

  1. `receive` stores the file and writes a `pending` row, then returns. It does
     no reading, so it is fast and cannot fail on a slow parse.
  2. `read` picks up a pending row later and runs stages 1-6 over it.

An applicant gets their receipt from step 1. If step 2 never runs - a timeout, a
crash, a bad PDF - the application is already stored and still shows up in the
recruiter's list marked "not read yet". Nothing a person submitted is ever lost
because the machine that was supposed to read it fell over.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from .blueprint import blueprint_for
from .config import Settings
from .models import CandidateProfile
from .postings import ENGINE_VERSION, Application, JobPosting, now
from . import injection
from .stages import offline, parse, rank
from .stages import match as match_stage
from .stages import template_match as template

#: Larger than any real CV, and a cap on what a stranger can push at us.
MAX_CV_BYTES = 8 * 1024 * 1024

ALLOWED_SUFFIXES = {".pdf", ".docx", ".doc", ".txt", ".md", ".rtf"}


class IntakeError(Exception):
    """Something the applicant can fix, and should be told about plainly."""


def receive(
    backend,
    posting: JobPosting,
    full_name: str,
    email: str,
    phone: str,
    filename: str,
    data: bytes,
) -> Application:
    """Store an application. Does not read the CV - that is `read`'s job."""
    if not posting.is_open:
        raise IntakeError("This vacancy is no longer accepting applications.")
    if not full_name.strip():
        raise IntakeError("Please give your name.")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise IntakeError("Please give an email address we can reach you on.")
    if not data:
        raise IntakeError("The CV file is empty.")
    if len(data) > MAX_CV_BYTES:
        raise IntakeError("That file is larger than 8 MB.")

    suffix = Path(filename or "cv.pdf").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(s.lstrip(".").upper() for s in ALLOWED_SUFFIXES))
        raise IntakeError(f"Please upload one of: {allowed}.")

    application = Application(
        job_slug=posting.slug,
        full_name=full_name.strip()[:120],
        email=email.strip().lower()[:160],
        phone=phone.strip()[:40],
    )
    return backend.add_application(application, data, filename or f"cv{suffix}")


def read(backend, posting: JobPosting, application: Application) -> Application:
    """Stages 1-5 over one stored application. Records the decision, not the essay.

    The per-requirement reasoning is deliberately not stored: it is recomputed
    from the profile in about fifteen milliseconds whenever somebody opens the
    candidate, and keeping it would put seven kilobytes of prose per applicant
    into the recruiter's spreadsheet.
    """
    data = backend.cv_bytes(application.id)
    if data is None:
        application.status = "failed"
        application.detail = "The stored CV file could not be found."
        backend.update_application(application)
        return application

    suffix = Path(application.cv_filename or "cv.pdf").suffix.lower() or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(data)
        temp = Path(handle.name)
    try:
        doc = parse.parse_one(temp)
        doc.path = Path(application.cv_filename or temp.name)
        if not doc.ok:
            application.status = "failed"
            application.detail = doc.error
            application.read_at = now()
            backend.update_application(application)
            return application

        profile = offline.extract_profile(doc)
        # Rules cannot be argued with, so nothing here needs striking off. But
        # the document may still be carrying an instruction aimed at a model,
        # and the recruiter is entitled to know before they read it.
        security = injection.verify(profile, doc.text)
    finally:
        temp.unlink(missing_ok=True)

    backend.save_profile(application.id, profile)
    application.security_flags = security.warnings

    if not profile.is_cv:
        application.status = "not_a_cv"
        application.detail = profile.document_type.replace("_", " ")
        application.read_at = now()
        backend.update_application(application)
        return application

    entry = rank.rank([match_stage.match(profile, posting.profile, application.cv_filename)])[0]
    application.status = "read"
    application.detail = ""
    application.read_at = now()
    application.percent = entry.percent
    application.required_percent = entry.required_percent
    application.preferred_percent = entry.preferred_percent
    application.tier = entry.tier
    application.reason = entry.reason
    application.engine_version = ENGINE_VERSION
    backend.update_application(application)
    return application


def read_pending(backend, posting: JobPosting, limit: int = 25) -> list[Application]:
    """Drain the queue for one posting. Bounded so a request cannot run away."""
    pending = [a for a in backend.applications(posting.slug) if a.status == "pending"]
    return [read(backend, posting, a) for a in pending[:limit]]


def detail_for(
    backend, posting: JobPosting, application: Application
) -> tuple[CandidateProfile, object, object] | None:
    """The full reasoning for one candidate, recomputed rather than stored."""
    profile = backend.profile(application.id)
    if profile is None:
        return None
    result = match_stage.match(profile, posting.profile, application.cv_filename)
    entry = rank.rank([result])[0]
    report = template.evaluate(profile, blueprint_for(posting.profile), result)
    return (profile, entry, report)
