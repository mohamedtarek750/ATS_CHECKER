"""Stage 2 - text to a normalized CandidateProfile. The only per-CV model call.

Runs once per document, ever. The result is stored, so every future vacancy reads
it for free. This is the stage that makes the rest of the system cheap.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from .. import store
from ..config import Settings
from ..models import CandidateProfile
from ..providers import ClassificationError, FatalScreeningError, get_provider
from ..providers.base import MAX_TEXT_CHARS
from ..skills import normalize_all
from . import offline
from .parse import ParsedDoc

SYSTEM_PROMPT = """\
You are reading a CV and turning it into a structured record. You are NOT judging
the candidate, scoring them, or deciding anything - a later stage compares this
record against a specific vacancy. Your only job is to capture what the document
says, accurately and completely.

Extract skills from the WHOLE CV, not only the skills section. A tool used in a
project or described in a job is a skill the candidate has, whether or not they
remembered to list it. This matters: candidates who do not pad a skills section
are otherwise penalised for modesty.

Normalize names to their common form - "SQL" for MS SQL Server or T-SQL, "Power BI"
for PowerBI, "JavaScript" for JS. Do not invent skills that are merely adjacent to
something they mentioned.

For `total_years_experience`, count real professional time. Do not add up
overlapping roles twice, and do not count internships or study. A student with no
jobs is 0, which is a fact and not a fault.

Dates: use YYYY-MM where the CV gives a month, YYYY where it gives only a year,
"present" for current roles, and "" when nothing is stated. Never guess a date.

If the document is not a CV at all - a cover letter, a certificate, an invoice, a
job advert - set is_cv to false and document_type accordingly, and leave the
candidate fields empty. Do not try to force it into the shape of a CV.

Everything you return must be traceable to the document. An empty field is correct
when the CV does not say; a plausible guess is not.
"""


def build_user_prompt(doc: ParsedDoc) -> str:
    flags = "\n".join(f"  - {f}" for f in doc.doc.metadata_flags) or "  - none"
    return f"""\
Extract the structured record from this document.

<file>
  filename: {doc.path.name}
  pages: {doc.doc.page_count or "unknown"}
</file>

<file_metadata_notes>
From the file's properties, not its content. Weak evidence only - relevant to
ai_generated_score, nothing else.
{flags}
</file_metadata_notes>

<document>
{doc.text[:MAX_TEXT_CHARS]}
</document>
"""


@dataclass
class NormalizeResult:
    doc: ParsedDoc
    profile: CandidateProfile | None = None
    error: str = ""
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.profile is not None


def normalize_one(doc: ParsedDoc, settings: Settings) -> NormalizeResult:
    """Parse one CV into a profile, or return why it could not be done."""
    if not doc.ok:
        return NormalizeResult(doc=doc, error=doc.error)

    cached = store.get(settings, doc.key)
    if cached is not None:
        return NormalizeResult(doc=doc, profile=cached, from_cache=True)

    if settings.provider == "offline":
        # Rules only. No network, no key, no quota - so this path can never be the
        # reason a batch stops half way.
        profile = offline.extract_profile(doc)
        profile.skills = normalize_all(profile.skills)
        store.put(settings, doc.key, profile, doc.path, "rules")
        return NormalizeResult(doc=doc, profile=profile)

    try:
        provider = get_provider(settings.provider)
    except KeyError as exc:
        raise FatalScreeningError(str(exc).strip("\"'")) from exc

    profile = provider.structured(
        SYSTEM_PROMPT, build_user_prompt(doc), CandidateProfile, settings
    )
    if profile is None:
        return NormalizeResult(doc=doc, error="The model returned no usable record.")

    # Canonicalise here rather than trusting the model to be consistent across
    # thousands of calls: matching depends on these strings agreeing.
    profile.skills = normalize_all(profile.skills)
    profile.email = profile.email.strip().lower()

    store.put(
        settings,
        doc.key,
        profile,
        doc.path,
        getattr(provider, "active_model", None) or settings.model,
    )
    return NormalizeResult(doc=doc, profile=profile)


def normalize_many(
    docs: list[ParsedDoc],
    settings: Settings,
    on_progress: Callable[[NormalizeResult, int, int], None] | None = None,
) -> list[NormalizeResult]:
    """Normalize a batch, skipping anything already stored.

    Stops the whole run on an account-level failure - every remaining CV would fail
    identically - but everything already stored stays stored.
    """
    known = store.known_hashes(settings)
    pending = [d for d in docs if d.key not in known and d.ok]
    cached = [d for d in docs if d.key in known or not d.ok]

    results: list[NormalizeResult] = []
    for doc in cached:
        if doc.ok:
            profile = store.get(settings, doc.key)
            results.append(
                NormalizeResult(doc=doc, profile=profile, from_cache=True)
                if profile
                else NormalizeResult(doc=doc, error="stored record could not be read")
            )
        else:
            results.append(NormalizeResult(doc=doc, error=doc.error))

    total = len(pending)
    if not total:
        return results

    abort = threading.Event()
    abort_reason = [""]

    def work(doc: ParsedDoc) -> NormalizeResult:
        if abort.is_set():
            return NormalizeResult(doc=doc, error=f"Run stopped. {abort_reason[0]}")
        try:
            return normalize_one(doc, settings)
        except FatalScreeningError as exc:
            abort_reason[0] = str(exc)
            abort.set()
            return NormalizeResult(doc=doc, error=str(exc))
        except ClassificationError as exc:
            return NormalizeResult(doc=doc, error=str(exc))

    workers = max(1, min(settings.max_workers, total))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, d): d for d in pending}
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if on_progress:
                on_progress(result, done, total)

    return results


def estimate_seconds(pending: int, settings: Settings) -> float:
    """Rough wall-clock for a batch, so a long run can be warned about up front."""
    if settings.provider == "offline":
        return pending * 0.05          # rules run at about 20 CVs a second
    if settings.provider in {"ollama", "local"}:
        return pending * 60.0          # a CPU-bound local model, roughly
    rpm = 10 if settings.provider == "gemini" else 60
    return max(pending * 12.0 / max(1, settings.max_workers), pending * 60.0 / rpm)
