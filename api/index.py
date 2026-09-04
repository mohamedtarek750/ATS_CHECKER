"""HTTP API for the web app. Deployed as a Vercel Python function.

Shaped around what serverless can actually do:

  * One CV per request. Reading a hundred in one call would blow the function
    timeout, so the browser sends them one at a time and shows progress.
  * No server-side storage. A serverless filesystem does not survive between
    invocations, and applicants' CVs living in a database nobody asked for is a
    liability rather than a feature. Parsed profiles are returned to the browser
    and kept there; the server holds nothing after the response.
  * Matching and ranking are pure computation, so a whole pool is ranked in one
    fast request with no model call at all.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ats.config import PROVIDER_NAMES, Settings  # noqa: E402
from ats.job_profile import JobProfile  # noqa: E402
from ats.models import CandidateProfile  # noqa: E402
from ats.providers import ClassificationError  # noqa: E402
from ats.skills import normalize_all  # noqa: E402
from ats.blueprint import CVBlueprint, blueprint_for, render  # noqa: E402
from ats.stages import from_cv, jobspec, offline, parse, rank  # noqa: E402
from ats.stages import template_match as template  # noqa: E402
from ats.stages import match as match_stage  # noqa: E402
from ats import intake, postings  # noqa: E402
from ats.backends import get_backend  # noqa: E402
from ats import auth, notify, stats as stats_module  # noqa: E402

MAX_UPLOAD_BYTES = 8 * 1024 * 1024

app = FastAPI(title="ACUD ATS API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def has_model_key() -> bool:
    """Is a key-backed provider available at all?"""
    return bool(
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
    )


def keyed_provider() -> str | None:
    """The provider a key unlocks, if any."""
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude"
    return None


def settings_for(provider: str | None) -> Settings:
    """Resolve the reader. Falls back to `offline`, which needs no key at all."""
    name = (provider or os.getenv("ATS_PROVIDER") or "offline").lower()
    if name not in PROVIDER_NAMES:
        name = "offline"
    os.environ["ATS_PROVIDER"] = name
    settings = Settings()
    settings.provider = name
    return settings


def settings_for_reading_jobs() -> Settings:
    """A job description needs comprehension, so it always uses a model.

    Reading CVs and reading an advert are different problems. Rules handle a CV
    well because most of what matters there is vocabulary, and there may be
    thousands of them. An advert is one document per vacancy and turning its prose
    into must-have and nice-to-have is exactly the judgement rules cannot make - so
    this uses a key whenever one exists, regardless of what CVs are being read with.
    """
    name = keyed_provider()
    if name is None:
        raise HTTPException(
            400,
            "Reading a job description needs a model. Add GEMINI_API_KEY to the "
            "deployment's environment variables, or use a reference CV instead - "
            "that route works with no key.",
        )
    os.environ["ATS_PROVIDER"] = name
    settings = Settings()
    settings.provider = name
    return settings


def read_upload(upload: UploadFile) -> parse.ParsedDoc:
    """Save to a temp file (the extractors work on paths) and parse it."""
    suffix = Path(upload.filename or "cv.pdf").suffix.lower() or ".pdf"
    data = upload.file.read()
    if not data:
        raise HTTPException(400, "The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That file is larger than 8 MB.")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(data)
        temp_path = Path(handle.name)
    try:
        doc = parse.parse_one(temp_path)
        # Report the real filename, not the temporary one.
        doc.path = Path(upload.filename or temp_path.name)
        return doc
    finally:
        temp_path.unlink(missing_ok=True)


def profile_from(doc: parse.ParsedDoc, settings: Settings) -> CandidateProfile:
    if not doc.ok:
        raise HTTPException(422, doc.error)

    if settings.provider == "offline":
        profile = offline.extract_profile(doc)
    else:
        from ats.providers import get_provider
        from ats.stages.normalize import SYSTEM_PROMPT, build_user_prompt

        try:
            profile = get_provider(settings.provider).structured(
                SYSTEM_PROMPT, build_user_prompt(doc), CandidateProfile, settings
            )
        except ClassificationError as exc:
            raise HTTPException(502, str(exc)) from exc
        if profile is None:
            raise HTTPException(502, "The model returned no usable record.")

    profile.skills = normalize_all(profile.skills)
    profile.email = profile.email.strip().lower()
    return profile


# --------------------------------------------------------------------------
# Requests and responses
# --------------------------------------------------------------------------
class ParsedCV(BaseModel):
    filename: str
    key: str = Field(description="Content hash - identifies a re-upload as the same CV.")
    profile: CandidateProfile


class JobText(BaseModel):
    text: str
    provider: str | None = None


class FromCVRequest(BaseModel):
    profile: CandidateProfile
    strict: bool = False


class Candidate(BaseModel):
    filename: str
    profile: CandidateProfile


class MatchRequest(BaseModel):
    job: JobProfile
    candidates: list[Candidate]
    #: Also evaluate how well each CV is written for this job.
    include_template: bool = True


class RequirementOut(BaseModel):
    requirement: str
    kind: str
    importance: str
    status: str
    evidence: str
    #: How firmly the CV supports it: strong, valid, partial, none.
    strength: str = "none"
    #: Which section the evidence came from, already worded for a reader.
    source: str = "Not found"
    #: One sentence saying why this verdict, so nobody has to guess.
    explanation: str = ""


class RoleOut(BaseModel):
    title: str
    company: str
    years: float
    is_internship: bool
    #: core / adjacent / unrelated / unclear
    relevance: str
    #: Requirements this role, on its own, shows the person doing.
    demonstrates: list[str]
    has_outcomes: bool
    note: str


class ExperienceOut(BaseModel):
    """Whether there is experience, and whether it is the experience wanted."""

    has_experience: bool
    total_years: float
    relevant_years: float
    shown_in_work: int
    checkable: int
    verdict: str
    roles: list[RoleOut]


class RankedOut(BaseModel):
    filename: str
    name: str
    headline: str
    email: str
    phone: str
    years: float
    percent: int
    #: Reported separately so a strong candidate missing optional extras is not
    #: read as a weak one. The overall percent alone cannot show that difference.
    required_percent: int = 0
    preferred_percent: int = 0
    tier: str
    tier_label: str
    #: The ordering score. Exposed so a pool sent in several batches can be
    #: merged back into exactly the order one request would have returned.
    score: float = 0.0
    reason: str
    experience: ExperienceOut
    must_met: int
    must_total: int
    nice_met: int
    nice_total: int
    requirements: list[RequirementOut]
    possibly_ai: bool
    #: Reported alongside the job match, never folded into it.
    template: TemplateOut | None = None


class SectionSpecOut(BaseModel):
    key: str
    label: str
    weight: str
    why: str
    should_contain: list[str]


class BlueprintOut(BaseModel):
    """The ideal CV for a vacancy - a blueprint, never an invented candidate."""

    job_title: str
    seniority: str
    sections: list[SectionSpecOut]
    priority_skills: list[str]
    summary_formula: str
    summary_should_mention: list[str]
    bullet_pattern: str
    wants_metrics: bool
    notes: list[str]
    preview: str


class SectionFindingOut(BaseModel):
    key: str
    label: str
    weight: str
    status: str
    detail: str


class RecommendationOut(BaseModel):
    priority: str
    text: str


class TemplateOut(BaseModel):
    """How well one CV is built for one job. Never merged with the job match."""

    percent: int
    band: str
    sections: list[SectionFindingOut]
    strengths: list[str]
    improvements: list[str]
    recommendations: list[RecommendationOut]
    ideal_order: list[str]
    candidate_order: list[str]
    skill_placement: dict


class TemplateRequest(BaseModel):
    job: JobProfile
    profile: CandidateProfile


class MatchResponse(BaseModel):
    job_title: str
    must_total: int
    nice_total: int
    counts: dict
    results: list[RankedOut]


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    settings = settings_for(None)
    return {
        "ok": True,
        "provider": settings.provider,
        "model": settings.model,
        "providers": PROVIDER_NAMES,
        # `offline` needs no key, so the app is usable with nothing configured.
        "needs_key": settings.provider not in {"offline", "ollama"},
        # Reading an advert always needs a model, whatever CVs are read with.
        "can_read_jobs": keyed_provider() is not None,
        "job_model": keyed_provider(),
    }


@app.post("/api/cv", response_model=ParsedCV)
def parse_cv(file: UploadFile = File(...), provider: str | None = None) -> ParsedCV:
    """One CV in, one structured profile out. The browser keeps the result."""
    settings = settings_for(provider)
    doc = read_upload(file)
    return ParsedCV(
        filename=doc.path.name,
        key=doc.key,
        profile=profile_from(doc, settings),
    )


@app.post("/api/job", response_model=JobProfile)
def parse_job(body: JobText) -> JobProfile:
    """A pasted advert becomes a checklist the recruiter can review and edit."""
    if not body.text.strip():
        raise HTTPException(400, "Paste the job description first.")
    settings = settings_for_reading_jobs()
    try:
        return jobspec.from_text(body.text, settings)
    except ClassificationError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/job-from-cv", response_model=JobProfile)
def job_from_cv(body: FromCVRequest) -> JobProfile:
    """Filter the pool by "someone like this" - derived from a reference CV."""
    return from_cv.requirements_from_cv(body.profile, strict=body.strict)


def _template_out(report: template.TemplateReport) -> TemplateOut:
    return TemplateOut(
        percent=report.percent,
        band=report.band,
        sections=[
            SectionFindingOut(
                key=f.key, label=f.label, weight=f.weight,
                status=f.status, detail=f.detail,
            )
            for f in report.sections
        ],
        strengths=report.strengths,
        improvements=report.improvements,
        recommendations=[
            RecommendationOut(priority=r.priority, text=r.text)
            for r in report.recommendations
        ],
        ideal_order=report.ideal_order,
        candidate_order=report.candidate_order,
        skill_placement=report.skill_placement,
    )


def _ranked_out(entry, template_out=None) -> "RankedOut":
    """One ranked candidate in the shape the browser already knows how to render.

    Used by the batch matcher and by the dashboard's per-candidate view, so a
    saved application and a freshly matched one cannot drift apart on screen.
    """
    return RankedOut(
        filename=entry.match.source_name,
        name=entry.name,
        headline=entry.headline,
        email=entry.match.candidate.email,
        phone=entry.match.candidate.phone,
        years=entry.match.candidate.total_years_experience,
        percent=entry.percent,
        required_percent=entry.required_percent,
        preferred_percent=entry.preferred_percent,
        tier=entry.tier,
        tier_label=rank.TIER_LABEL[entry.tier],
        score=entry.score,
        reason=entry.reason,
        must_met=entry.match.must_met,
        must_total=entry.match.must_total,
        experience=ExperienceOut(
            has_experience=entry.match.experience.has_experience,
            total_years=entry.match.experience.total_years,
            relevant_years=entry.match.experience.relevant_years,
            shown_in_work=entry.match.experience.shown_in_work,
            checkable=entry.match.experience.checkable,
            verdict=entry.match.experience.verdict,
            roles=[
                RoleOut(
                    title=role.title,
                    company=role.company,
                    years=role.years,
                    is_internship=role.is_internship,
                    relevance=role.relevance,
                    demonstrates=role.demonstrates,
                    has_outcomes=role.has_outcomes,
                    note=role.note,
                )
                for role in entry.match.experience.roles
            ],
        ),
        nice_met=entry.match.nice_met,
        nice_total=entry.match.nice_total,
        requirements=[
            RequirementOut(
                requirement=r.requirement,
                kind=r.kind,
                importance=r.importance,
                status=r.status,
                evidence=r.evidence,
                strength=r.strength,
                source=r.source_label,
                explanation=r.explanation,
            )
            for r in entry.match.results
        ],
        possibly_ai=entry.flagged_ai,
        template=template_out,
    )


@app.post("/api/match", response_model=MatchResponse)
def match(body: MatchRequest) -> MatchResponse:
    """Rank a whole pool against a job. Pure computation - no model, no waiting."""
    if not body.candidates:
        raise HTTPException(400, "No candidates to match.")

    results = [
        match_stage.match(c.profile, body.job, c.filename) for c in body.candidates
    ]
    ranked = rank.rank(results)

    # The template report is deterministic and cheap, so every candidate gets one
    # in the same request rather than a second round trip per person.
    blueprint = blueprint_for(body.job) if body.include_template else None
    templates: dict[str, TemplateOut] = {}
    if blueprint is not None:
        for entry in ranked:
            templates[entry.match.source_name] = _template_out(
                template.evaluate(entry.match.candidate, blueprint, entry.match)
            )

    return MatchResponse(
        job_title=body.job.title,
        must_total=len(body.job.must_haves),
        nice_total=len(body.job.nice_to_haves),
        counts=rank.summarize(ranked),
        results=[
            _ranked_out(entry, templates.get(entry.match.source_name))
            for entry in ranked
        ],
    )


@app.post("/api/blueprint", response_model=BlueprintOut)
def ideal_cv(job: JobProfile) -> BlueprintOut:
    """The ideal CV for this vacancy. Derived in code - no model call, no wait."""
    return _blueprint_out(blueprint_for(job))


@app.post("/api/template", response_model=TemplateOut)
def template_report(body: TemplateRequest) -> TemplateOut:
    """How well one CV is built for one job, section by section."""
    blueprint = blueprint_for(body.job)
    match_result = match_stage.match(body.profile, body.job)
    return _template_out(template.evaluate(body.profile, blueprint, match_result))


# --------------------------------------------------------------------------
# Postings, applications, and the dashboard over them
#
# Everything above this line is stateless: a CV goes in, a result comes back,
# and the server keeps nothing. Everything below it persists, because a public
# application link means somebody applies on Tuesday and a recruiter looks on
# Friday. That is the whole reason a backend exists.
# --------------------------------------------------------------------------
class PostingOut(BaseModel):
    slug: str
    title: str
    summary: str
    status: str
    created: str
    must_total: int
    nice_total: int
    #: Filled in on the dashboard listing, not on the public page.
    applications: int = 0
    unread: int = 0
    #: The split, so the list answers "how is this vacancy doing" without
    #: having to open every vacancy in turn to find out.
    accepted: int = 0
    waiting_list: int = 0
    rejected: int = 0


class PublicPostingOut(BaseModel):
    """What a stranger is allowed to see. Never the checklist itself.

    Publishing the must-haves would tell every applicant exactly which words to
    paste into their CV, which is the failure mode the whole evidence-weighted
    matcher exists to resist.
    """

    slug: str
    title: str
    summary: str
    is_open: bool


class NewPosting(BaseModel):
    job: JobProfile
    #: Optional: a readable URL. Derived from the title when absent.
    slug: str = ""


class ApplicationOut(BaseModel):
    id: str
    full_name: str
    email: str
    phone: str
    applied_at: str
    cv_filename: str
    cv_url: str
    status: str
    detail: str
    read_at: str
    percent: int
    required_percent: int
    preferred_percent: int
    tier: str
    tier_label: str
    reason: str
    #: Which version of the matching rules produced the score above.
    engine_version: str
    decision: str
    decision_label: str
    decided_by: str
    decided_at: str
    note: str
    #: Scored under an older engine, so the number may not be reproducible.
    stale: bool


class ApplicationsOut(BaseModel):
    posting: PostingOut
    counts: dict
    results: list[ApplicationOut]


class DecisionIn(BaseModel):
    decision: str | None = None
    note: str | None = None


class ReceiptOut(BaseModel):
    id: str
    full_name: str
    status: str


def _posting_out(posting, rows: list | None = None) -> PostingOut:
    return PostingOut(
        slug=posting.slug,
        title=posting.title,
        summary=posting.summary,
        status=posting.status,
        created=posting.created,
        must_total=len(posting.profile.must_haves),
        nice_total=len(posting.profile.nice_to_haves),
        applications=len(rows) if rows is not None else 0,
        unread=sum(1 for r in (rows or []) if r.status == "pending"),
        # Only applications that have actually been read carry a tier. A
        # pending one is not a rejection, and counting it as one would make a
        # vacancy nobody has read yet look like a vacancy nobody passed.
        accepted=sum(1 for r in (rows or []) if r.tier == "accepted"),
        waiting_list=sum(1 for r in (rows or []) if r.tier == "waiting_list"),
        rejected=sum(1 for r in (rows or []) if r.tier == "rejected"),
    )


def _application_out(row) -> ApplicationOut:
    return ApplicationOut(
        id=row.id,
        full_name=row.full_name,
        email=row.email,
        phone=row.phone,
        applied_at=row.applied_at,
        cv_filename=row.cv_filename,
        cv_url=row.cv_url,
        status=row.status,
        detail=row.detail,
        read_at=row.read_at,
        percent=row.percent,
        required_percent=row.required_percent,
        preferred_percent=row.preferred_percent,
        tier=row.tier,
        tier_label=rank.TIER_LABEL.get(row.tier, "Not read yet"),
        reason=row.reason,
        engine_version=row.engine_version,
        decision=row.decision,
        decision_label=postings.DECISION_LABEL.get(row.decision, row.decision),
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        note=row.note,
        stale=row.is_stale,
    )


def _require_posting(slug: str):
    posting = get_backend().posting(slug)
    if posting is None:
        raise HTTPException(404, "No such vacancy.")
    return posting


# --------------------------------------------------------------------------
# Sign-in
#
# Applied to everything that can see an applicant. The public application page
# is deliberately outside it: a candidate cannot be asked to hold an account
# before they are allowed to apply for a job.
# --------------------------------------------------------------------------
class AdminOut(BaseModel):
    email: str
    name: str
    picture: str


class AuthStatusOut(BaseModel):
    #: Whether a sign-in is demanded at all. False only when ATS_AUTH=off.
    required: bool
    #: Whether the environment actually has what sign-in needs.
    configured: bool
    #: Handed to Google's button in the browser. Empty when auth is off.
    client_id: str
    admins: int


def require_admin(authorization: str | None = Header(default=None)) -> auth.AdminUser:
    """The signed-in person, or a refusal.

    A missing configuration is 503 rather than 401 on purpose: it is a
    deployment that was never finished, not somebody failing to log in, and
    telling them to "sign in" would send them round a loop with no way out.
    """
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    try:
        return auth.verify(token)
    except auth.AuthNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc)) from exc


@app.get("/api/auth/status", response_model=AuthStatusOut)
def auth_status() -> AuthStatusOut:
    """What the sign-in page needs before anybody has signed in."""
    return AuthStatusOut(**auth.status())


@app.get("/api/auth/me", response_model=AdminOut)
def who_am_i(admin: auth.AdminUser = Depends(require_admin)) -> AdminOut:
    """Confirms a token is good and says whose it is."""
    return AdminOut(email=admin.email, name=admin.name, picture=admin.picture)


@app.get("/api/postings", response_model=list[PostingOut])
def list_postings(admin: auth.AdminUser = Depends(require_admin)) -> list[PostingOut]:
    """Every vacancy, with how many people have applied to each."""
    backend = get_backend()
    return [
        _posting_out(p, backend.applications(p.slug)) for p in backend.postings()
    ]


@app.post("/api/postings", response_model=PostingOut)
def create_posting(
    body: NewPosting, admin: auth.AdminUser = Depends(require_admin)
) -> PostingOut:
    """Open a vacancy. The reviewed checklist is frozen onto it here."""
    if not body.job.requirements:
        raise HTTPException(400, "Read the advert first - the checklist is empty.")

    backend = get_backend()
    slug = postings.slugify(body.slug or body.job.title)
    # Two vacancies with the same title are ordinary. Silently overwriting the
    # first one, and every application to it, is not.
    if backend.posting(slug) is not None:
        suffix = 2
        while backend.posting(f"{slug}-{suffix}") is not None:
            suffix += 1
        slug = f"{slug}-{suffix}"

    posting = postings.JobPosting(
        slug=slug,
        title=body.job.title,
        summary=body.job.summary,
        profile=body.job,
        created_by=admin.email,
    )
    return _posting_out(backend.save_posting(posting), [])


@app.post("/api/postings/{slug}/status", response_model=PostingOut)
def set_posting_status(
    slug: str, status: str, admin: auth.AdminUser = Depends(require_admin)
) -> PostingOut:
    """Open or close a vacancy. A closed one stops accepting applications."""
    if status not in {"open", "closed"}:
        raise HTTPException(400, "Status must be open or closed.")
    backend = get_backend()
    posting = _require_posting(slug)
    posting.status = status
    backend.save_posting(posting)
    return _posting_out(posting, backend.applications(slug))


@app.get("/api/public/postings/{slug}", response_model=PublicPostingOut)
def public_posting(slug: str) -> PublicPostingOut:
    """What the application page shows. Title and summary, never the criteria."""
    posting = _require_posting(slug)
    return PublicPostingOut(
        slug=posting.slug,
        title=posting.title,
        summary=posting.summary,
        is_open=posting.is_open,
    )


@app.post("/api/public/postings/{slug}/apply", response_model=ReceiptOut)
def apply(
    slug: str,
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    file: UploadFile = File(...),
) -> ReceiptOut:
    """A stranger applies. Stores the file and returns - never reads it here.

    Reading a CV takes long enough that doing it in this request would leave the
    applicant on a spinner and lose their application to a timeout. The row is
    written as `pending` and picked up afterwards.
    """
    posting = _require_posting(slug)
    data = file.file.read()
    try:
        row = intake.receive(
            get_backend(), posting,
            full_name=full_name, email=email, phone=phone,
            filename=file.filename or "cv.pdf", data=data,
        )
    except intake.IntakeError as exc:
        raise HTTPException(400, str(exc)) from exc

    # The CV is stored by this point, so a mail outage costs a receipt and never
    # an application. `send` reports rather than raises, for exactly this.
    notify.application_received(row, posting)

    return ReceiptOut(id=row.id, full_name=row.full_name, status=row.status)


@app.get("/api/postings/{slug}/applications", response_model=ApplicationsOut)
def list_applications(
    slug: str, admin: auth.AdminUser = Depends(require_admin)
) -> ApplicationsOut:
    """The dashboard for one vacancy, best fit first."""
    backend = get_backend()
    posting = _require_posting(slug)
    rows = backend.applications(slug)

    order = {"accepted": 0, "waiting_list": 1, "rejected": 2, "not_a_cv": 3, "": 4}
    rows.sort(key=lambda r: (order.get(r.tier, 4), -r.percent, r.full_name.lower()))

    counts: dict[str, int] = {"total": len(rows)}
    for row in rows:
        key = row.tier if row.status == "read" else row.status
        counts[key] = counts.get(key, 0) + 1
    return ApplicationsOut(
        posting=_posting_out(posting, rows),
        counts=counts,
        results=[_application_out(r) for r in rows],
    )


@app.post("/api/postings/{slug}/read", response_model=ApplicationsOut)
def read_pending(
    slug: str, admin: auth.AdminUser = Depends(require_admin)
) -> ApplicationsOut:
    """Read the CVs that have come in since last time. Bounded per call."""
    posting = _require_posting(slug)
    intake.read_pending(get_backend(), posting)
    return list_applications(slug, admin)


@app.post("/api/applications/{application_id}/decision", response_model=ApplicationOut)
def set_decision(
    application_id: str, body: DecisionIn,
    admin: auth.AdminUser = Depends(require_admin),
) -> ApplicationOut:
    """What a person decided. The engine never writes here."""
    backend = get_backend()
    row = backend.application(application_id)
    if row is None:
        raise HTTPException(404, "No such application.")

    changed = False
    if body.decision is not None:
        if body.decision not in postings.DECISION_LABEL:
            raise HTTPException(400, "Unknown decision.")
        row.decision = body.decision
        changed = True
    if body.note is not None:
        row.note = body.note[:2000]
        changed = True

    # Who moved this person, and when. A shortlist nobody will own is worse
    # than no shortlist: somebody has to be answerable for a rejection.
    if changed:
        row.decided_by = admin.email
        row.decided_at = postings.now()
    backend.update_application(row)
    return _application_out(row)


@app.get("/api/applications/{application_id}", response_model=RankedOut)
def application_detail(
    application_id: str, admin: auth.AdminUser = Depends(require_admin)
) -> RankedOut:
    """Every requirement with its evidence, recomputed rather than stored."""
    backend = get_backend()
    row = backend.application(application_id)
    if row is None:
        raise HTTPException(404, "No such application.")
    posting = _require_posting(row.job_slug)

    detail = intake.detail_for(backend, posting, row)
    if detail is None:
        raise HTTPException(409, "This CV has not been read yet.")
    _profile, entry, report = detail
    return _ranked_out(entry, _template_out(report))


@app.get("/api/cv-file/{application_id}")
def cv_file(application_id: str, admin: auth.AdminUser = Depends(require_admin)):
    """The CV as it was uploaded, so a recruiter can read the actual document."""
    backend = get_backend()
    row = backend.application(application_id)
    if row is None:
        raise HTTPException(404, "No such application.")
    data = backend.cv_bytes(application_id)
    if data is None:
        raise HTTPException(404, "The stored file is missing.")

    suffix = Path(row.cv_filename or "cv.pdf").suffix.lower()
    media = {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/plain",
        ".rtf": "application/rtf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(suffix, "application/octet-stream")
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition":
                f'inline; filename="{row.cv_filename or "cv" + suffix}"'
        },
    )


# --------------------------------------------------------------------------
# Automation: reading what arrived, and saying so
# --------------------------------------------------------------------------
class StatsRequirementOut(BaseModel):
    requirement: str
    kind: str
    importance: str
    met: int
    partial: int
    total: int
    percent: int


class StatsOut(BaseModel):
    total: int
    read: int
    pending: int
    unreadable: int
    by_tier: dict
    by_decision: dict
    average_percent: int
    median_percent: int
    per_day: list[list]
    hardest: list[StatsRequirementOut]
    sampled: int
    sample_capped: bool


class CronOut(BaseModel):
    postings: int
    read: int
    notified: int
    detail: list[str]


@app.get("/api/postings/{slug}/stats", response_model=StatsOut)
def vacancy_stats(
    slug: str, admin: auth.AdminUser = Depends(require_admin)
) -> StatsOut:
    """What this vacancy's applications add up to, including what nobody meets."""
    backend = get_backend()
    posting = _require_posting(slug)
    computed = stats_module.summarize(posting, backend.applications(slug), backend)
    return StatsOut(
        total=computed.total,
        read=computed.read,
        pending=computed.pending,
        unreadable=computed.unreadable,
        by_tier=computed.by_tier,
        by_decision=computed.by_decision,
        average_percent=computed.average_percent,
        median_percent=computed.median_percent,
        per_day=[[day, count] for day, count in computed.per_day],
        hardest=[
            StatsRequirementOut(
                requirement=d.requirement, kind=d.kind, importance=d.importance,
                met=d.met, partial=d.partial, total=d.total, percent=d.percent,
            )
            for d in computed.hardest
        ],
        sampled=computed.sampled,
        sample_capped=computed.sample_capped,
    )


@app.get("/api/mail/status")
def mail_status(admin: auth.AdminUser = Depends(require_admin)) -> dict:
    """Whether email is set up, so the dashboard can say so rather than guess."""
    return notify.status()


def _cron_authorised(header: str | None) -> bool:
    """Vercel's scheduler sends the project's CRON_SECRET as a bearer token."""
    secret = (os.getenv("CRON_SECRET") or "").strip()
    if not secret:
        return False
    return bool(header) and header.strip() == f"Bearer {secret}"


@app.post("/api/cron/intake", response_model=CronOut)
def cron_intake(authorization: str | None = Header(default=None)) -> CronOut:
    """Read whatever has arrived, then tell the hiring team once.

    Runs on a schedule so applications do not sit unread until somebody happens
    to open the dashboard, and so the team hears about them without getting one
    email per applicant - a vacancy that attracts two hundred people would
    otherwise send two hundred, which is how a team learns to ignore them.

    Not behind the Google sign-in: a scheduler has no Google account. It carries
    CRON_SECRET instead, and with that unset the endpoint refuses outright
    rather than standing open.
    """
    if not _cron_authorised(authorization):
        raise HTTPException(
            401,
            "This endpoint is for the scheduler. Set CRON_SECRET in the "
            "deployment and send it as a bearer token.",
        )

    backend = get_backend()
    detail: list[str] = []
    total_read = 0
    notified = 0

    for posting in backend.postings():
        if not posting.is_open:
            continue
        fresh = intake.read_pending(backend, posting)
        if not fresh:
            continue
        total_read += len(fresh)
        detail.append(f"{posting.slug}: read {len(fresh)}")

        results = notify.new_applications_digest(posting, fresh)
        sent = sum(1 for r in results if r.ok)
        notified += sent
        if results:
            detail.append(f"{posting.slug}: digest {sent}/{len(results)}")

    return CronOut(
        postings=len(backend.postings()), read=total_read,
        notified=notified, detail=detail,
    )
