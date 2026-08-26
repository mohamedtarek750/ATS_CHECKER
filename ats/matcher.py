"""Screening a CV against a specific job, rather than against a generic standard.

Two flows live here:
  * `parse_job_description` turns the advert HR wrote into a reviewable checklist.
  * `match` checks one CV against that checklist, requirement by requirement.

Both go through the provider layer, so they work on whichever backend is configured.
"""

from __future__ import annotations

from .config import Settings
from .extract import ExtractedDoc
from .job_profile import JobProfile
from .prompts import (
    build_jd_parse_prompt,
    build_jd_user_prompt,
    build_match_system_prompt,
    build_match_user_prompt,
)
from .providers import ClassificationError, FatalScreeningError, get_provider
from .providers.base import MAX_TEXT_CHARS
from .schema import MatchVerdict


def _provider(settings: Settings):
    try:
        return get_provider(settings.provider)
    except KeyError as exc:
        raise FatalScreeningError(str(exc).strip("\"'")) from exc


def parse_job_description(text: str, settings: Settings) -> JobProfile:
    """Turn a pasted advert into a structured, reviewable job profile.

    The result is a draft. It is meant to be read and corrected by a human before
    any CV is screened against it: a requirement mis-marked as must-have here is
    applied silently to every applicant.
    """
    if not text.strip():
        raise ClassificationError("The job description is empty.")

    profile = _provider(settings).structured(
        build_jd_parse_prompt(),
        build_jd_user_prompt(text[:MAX_TEXT_CHARS]),
        JobProfile,
        settings,
    )
    if profile is None:
        raise ClassificationError("Could not read a job profile out of that text.")

    profile.source_text = text.strip()
    return profile


def match(doc: ExtractedDoc, profile: JobProfile, settings: Settings) -> MatchVerdict:
    """Check one CV against one job. Raises ClassificationError on failure."""
    verdict = _provider(settings).structured(
        build_match_system_prompt(profile.as_prompt_block()),
        build_match_user_prompt(
            filename=doc.path.name,
            text=doc.text[:MAX_TEXT_CHARS],
            metadata_flags=doc.metadata_flags,
            page_count=doc.page_count,
        ),
        MatchVerdict,
        settings,
    )
    if verdict is None:
        raise ClassificationError("The model returned no parseable verdict.")

    # The model is told to return one entry per requirement. If it dropped some,
    # the counts underneath the decision would be wrong, so say so rather than
    # quietly shortlisting on an incomplete check.
    expected = len(profile.requirements)
    got = len(verdict.requirement_matches)
    if got < expected:
        raise ClassificationError(
            f"Only {got} of {expected} requirements were checked - the verdict is "
            f"incomplete, so this CV has not been screened."
        )
    return verdict
