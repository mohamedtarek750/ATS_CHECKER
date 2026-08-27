"""Turn one CV into a spec, so a pool can be filtered by "someone like this".

A recruiter often has an easier time pointing at a person than writing a checklist:
"find me more like this one". This derives the requirements from a reference CV and
then reuses the ordinary matching, so the result is still a list of named
requirements with evidence rather than an opaque similarity number.

Two deliberate limits:

  * Only what the reference CV *demonstrates* becomes a requirement - skills,
    degree level, years. Never its university, employer, layout, or the language it
    happens to be written in. Those track where someone came from rather than what
    they can do, and "find me people like this" is exactly where that goes wrong.
  * Everything derived is a nice-to-have except a small core, so the pool is
    ranked by resemblance rather than cut in half by it.
"""

from __future__ import annotations

from ..job_profile import JobProfile, Requirement
from ..models import CandidateProfile
from ..skills import canonical

#: Skills that describe everyone and separate nobody.
_TOO_COMMON = {"Excel", "Git", "Microsoft Office", "Word", "PowerPoint"}

#: How many of the reference CV's skills become must-haves. The rest rank.
_CORE_SKILLS = 3


def requirements_from_cv(
    reference: CandidateProfile,
    strict: bool = False,
) -> JobProfile:
    """Build a JobProfile describing candidates similar to `reference`.

    `strict` promotes every derived skill to a must-have. Off by default: a
    reference CV is an example, not a specification, and treating each of its
    skills as mandatory rejects people who are plainly suitable.
    """
    title = reference.headline or "Similar to the reference CV"
    requirements: list[Requirement] = []

    distinctive = [
        canonical(skill)
        for skill in reference.skills
        if canonical(skill) not in _TOO_COMMON
    ]
    # De-duplicate while keeping the CV's own ordering: the skills a candidate
    # lists first are usually the ones they lead with.
    seen: dict[str, None] = {}
    for skill in distinctive:
        seen.setdefault(skill, None)
    distinctive = list(seen)

    for index, skill in enumerate(distinctive[:20]):
        core = strict or index < _CORE_SKILLS
        requirements.append(
            Requirement(
                text=skill,
                kind="skill",
                importance="must_have" if core else "nice_to_have",
            )
        )

    if reference.highest_degree not in {"unknown", "high_school"}:
        requirements.append(
            Requirement(
                text=f"{reference.highest_degree.replace('_', ' ').title()} degree",
                kind="education",
                importance="must_have" if strict else "nice_to_have",
            )
        )

    years = reference.total_years_experience
    if years >= 1:
        # Ask for meaningfully less than the reference holds. Someone with four
        # years is "like" someone with five; requiring the exact figure would
        # reject the obvious matches.
        wanted = max(1, int(years * 0.6))
        requirements.append(
            Requirement(
                text=f"{wanted}+ years of professional experience",
                kind="experience",
                importance="must_have" if strict else "nice_to_have",
            )
        )

    return JobProfile(
        title=title,
        seniority=reference.seniority.replace("_", " ").title(),
        summary=(
            f"Candidates resembling the reference CV"
            + (f" ({reference.full_name})" if reference.full_name else "")
            + ". Requirements were derived from what that CV demonstrates."
        ),
        min_years_experience=0.0,
        requirements=requirements,
        source_text=(
            "Derived from a reference CV rather than a written advert. "
            "Skills, degree level and years only - never institution, employer, "
            "or the language the CV was written in."
        ),
    )
