"""Stage 3 - job advert to a reviewable checklist. One model call per vacancy.

Thin wrapper over `ats.matcher` so all five stages are reachable from one place.
"""

from __future__ import annotations

from ..config import Settings
from ..job_profile import JobProfile, available, load, save
from ..matcher import parse_job_description
from ..skills import canonical


def from_text(text: str, settings: Settings) -> JobProfile:
    """Turn an advert into a draft profile. Meant to be reviewed before use."""
    profile = parse_job_description(text, settings)

    # Canonicalise skill requirements to the same vocabulary stage 2 produces.
    # Without this, "PowerBI" in the advert never matches "Power BI" on the CV.
    for req in profile.requirements:
        if req.kind == "skill":
            req.text = _canonicalise_requirement(req.text)
            req.any_of = [_canonicalise_requirement(a) for a in req.any_of]
    return profile.deduplicate()


def _canonicalise_requirement(text: str) -> str:
    """Map a requirement's skill name onto the canonical one, keeping the wording.

    "Strong SQL (joins, window functions)" keeps its detail - only a bare skill
    name is rewritten, because the extra words carry the level being asked for.
    """
    stripped = text.strip()
    mapped = canonical(stripped)
    return mapped if mapped.lower() != stripped.lower() else stripped


__all__ = ["JobProfile", "available", "from_text", "load", "save"]
