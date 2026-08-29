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

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ats.config import PROVIDER_NAMES, Settings  # noqa: E402
from ats.job_profile import JobProfile  # noqa: E402
from ats.models import CandidateProfile  # noqa: E402
from ats.providers import ClassificationError  # noqa: E402
from ats.skills import normalize_all  # noqa: E402
from ats.stages import from_cv, jobspec, offline, parse, rank  # noqa: E402
from ats.stages import match as match_stage  # noqa: E402

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


class RequirementOut(BaseModel):
    requirement: str
    kind: str
    importance: str
    status: str
    evidence: str


class RankedOut(BaseModel):
    filename: str
    name: str
    headline: str
    email: str
    phone: str
    years: float
    percent: int
    tier: str
    tier_label: str
    reason: str
    must_met: int
    must_total: int
    nice_met: int
    nice_total: int
    requirements: list[RequirementOut]
    possibly_ai: bool


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


@app.post("/api/match", response_model=MatchResponse)
def match(body: MatchRequest) -> MatchResponse:
    """Rank a whole pool against a job. Pure computation - no model, no waiting."""
    if not body.candidates:
        raise HTTPException(400, "No candidates to match.")

    results = [
        match_stage.match(c.profile, body.job, c.filename) for c in body.candidates
    ]
    ranked = rank.rank(results)

    return MatchResponse(
        job_title=body.job.title,
        must_total=len(body.job.must_haves),
        nice_total=len(body.job.nice_to_haves),
        counts=rank.summarize(ranked),
        results=[
            RankedOut(
                filename=entry.match.source_name,
                name=entry.name,
                headline=entry.headline,
                email=entry.match.candidate.email,
                phone=entry.match.candidate.phone,
                years=entry.match.candidate.total_years_experience,
                percent=entry.percent,
                tier=entry.tier,
                tier_label=rank.TIER_LABEL[entry.tier],
                reason=entry.reason,
                must_met=entry.match.must_met,
                must_total=entry.match.must_total,
                nice_met=entry.match.nice_met,
                nice_total=entry.match.nice_total,
                requirements=[
                    RequirementOut(
                        requirement=r.requirement,
                        kind=r.kind,
                        importance=r.importance,
                        status=r.status,
                        evidence=r.evidence,
                    )
                    for r in entry.match.results
                ],
                possibly_ai=entry.flagged_ai,
            )
            for entry in ranked
        ],
    )
