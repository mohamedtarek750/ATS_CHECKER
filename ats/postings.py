"""Job postings and the applications sent to them.

Everything before this file was stateless: a recruiter held CVs in their browser
for the length of one session and nothing survived it. A public application link
breaks that - somebody applies on Tuesday and a recruiter looks on Friday - so
these are the records that have to outlive a session, and the storage backends
behind them are the only part of the system that keeps personal data.

Deliberately small. A stored application carries the DECISION and enough to find
the CV again; it does not carry the reasoning behind the decision, which is
recomputed on demand in milliseconds. Storing seven kilobytes of per-requirement
evidence per applicant would make the recruiter's own spreadsheet unopenable.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol

from .job_profile import JobProfile
from .models import CandidateProfile

#: Bumped whenever a change to matching would move scores. Stored on every
#: decision so a recruiter can see that an old verdict was reached under older
#: rules, rather than having it silently restated as if it were current.
ENGINE_VERSION = "2026.09.1"

ApplicationStatus = Literal["pending", "read", "failed", "not_a_cv"]

#: What a human decided, which is separate from what the engine scored. The
#: engine never writes to this.
Decision = Literal["new", "shortlisted", "interviewing", "offered", "hired", "rejected"]

DECISION_LABEL: dict[str, str] = {
    "new": "New",
    "shortlisted": "Shortlisted",
    "interviewing": "Interviewing",
    "offered": "Offered",
    "hired": "Hired",
    "rejected": "Rejected",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


#: Where a CV goes when it was sent in without a vacancy behind it. Somebody
#: applying speculatively is not an error, and a CV with nowhere to sit is how
#: an application quietly disappears.
UNASSIGNED_SLUG = "unassigned"
UNASSIGNED_TITLE = "Applicants without a job description"


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = cleaned[:60] or "role"
    # A real vacancy must never land on the reserved one and inherit the pile
    # of speculative CVs sitting in it.
    return f"{slug}-role" if slug == UNASSIGNED_SLUG else slug


def unassigned_posting() -> "JobPosting":
    """The holding pen. A posting with no requirements, so nothing is scored."""
    return JobPosting(
        slug=UNASSIGNED_SLUG,
        title=UNASSIGNED_TITLE,
        summary=(
            "CVs sent in without a vacancy. They are read so you can see who "
            "applied, and deliberately not scored - there is nothing yet to "
            "measure them against."
        ),
        profile=JobProfile(
            title=UNASSIGNED_TITLE, seniority="", summary="",
            min_years_experience=0, requirements=[],
        ),
        created_by="system",
    )


@dataclass
class JobPosting:
    """One vacancy, and the public link people apply through."""

    slug: str
    title: str
    summary: str
    #: The reviewed checklist. This is what every applicant is measured against,
    #: frozen at the moment the posting opened.
    profile: JobProfile
    status: Literal["open", "closed"] = "open"
    created: str = field(default_factory=now)
    created_by: str = ""

    @property
    def is_open(self) -> bool:
        return self.status == "open"


@dataclass
class Application:
    """One person's application to one posting."""

    job_slug: str
    full_name: str
    email: str
    phone: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    applied_at: str = field(default_factory=now)

    #: Where the CV itself lives, in whichever backend is configured.
    cv_filename: str = ""
    cv_ref: str = ""
    cv_url: str = ""

    #: How far the intake got. "pending" means the file is safely stored and the
    #: CV has not been read yet - never that the application was lost.
    status: ApplicationStatus = "pending"
    detail: str = ""
    read_at: str = ""

    # --- the decision, as it stood when the CV was read ------------------
    percent: int = 0
    required_percent: int = 0
    preferred_percent: int = 0
    tier: str = ""
    reason: str = ""
    engine_version: str = ""

    # --- what a human did about it ---------------------------------------
    decision: Decision = "new"
    note: str = ""
    #: Who last moved this person, and when. Somebody has to be answerable for
    #: a rejection; an unattributed one is worse than none.
    decided_by: str = ""
    decided_at: str = ""

    #: What the CV tried on the reader, if anything. Never a rejection on its
    #: own - the patterns can appear innocently, and a system that binned people
    #: on a regex would throw away real applicants and tell nobody. A person
    #: looks, which is why it has to reach the screen.
    security_flags: list[str] = field(default_factory=list)

    @property
    def is_suspicious(self) -> bool:
        return bool(self.security_flags)

    @property
    def is_read(self) -> bool:
        return self.status == "read"

    @property
    def is_stale(self) -> bool:
        """Scored under an older engine, so the number may not be reproducible."""
        return bool(self.engine_version) and self.engine_version != ENGINE_VERSION


class Backend(Protocol):
    """What a storage backend has to do. Two exist: local files, and Google.

    Narrow on purpose. Everything above this line is ordinary Python objects, so
    the matching engine never learns where anything is kept, and a third backend
    is a file rather than a refactor.
    """

    def postings(self) -> list[JobPosting]: ...

    def posting(self, slug: str) -> JobPosting | None: ...

    def save_posting(self, posting: JobPosting) -> JobPosting: ...

    def applications(self, job_slug: str) -> list[Application]: ...

    def application(self, application_id: str) -> Application | None: ...

    def add_application(
        self, application: Application, cv_bytes: bytes, filename: str
    ) -> Application: ...

    def update_application(self, application: Application) -> None: ...

    def profile(self, application_id: str) -> CandidateProfile | None: ...

    def save_profile(self, application_id: str, profile: CandidateProfile) -> None: ...

    def cv_bytes(self, application_id: str) -> bytes | None: ...
