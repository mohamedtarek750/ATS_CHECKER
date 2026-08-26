"""Stage 4 - one candidate against one vacancy. No model call.

Stage 2 already did the semantic work: it read prose and produced normalized
skills, dated roles, and structured education. Matching that record against a
checklist is then a lookup, which is what lets a stored candidate be screened
against a new vacancy instantly and for free - the property the whole design
exists for.

Every result carries the evidence it was decided on. A candidate who asks why they
were not shortlisted gets an answer that points at their own CV.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ..job_profile import JobProfile, Requirement
from ..models import CandidateProfile
from ..skills import ALIASES, canonical, mentions

Status = Literal["met", "partial", "not_met", "unclear"]

DEGREE_RANK = {
    "unknown": 0, "high_school": 1, "diploma": 2,
    "bachelor": 3, "master": 4, "phd": 5,
}


@dataclass
class RequirementResult:
    requirement: str
    kind: str
    importance: str
    status: Status
    evidence: str = ""

    @property
    def is_must(self) -> bool:
        return self.importance == "must_have"

    @property
    def counts_as_met(self) -> bool:
        return self.status == "met"


@dataclass
class MatchResult:
    """Everything stage 5 needs, and everything HR is shown."""

    candidate: CandidateProfile
    job_title: str
    source_name: str = ""
    results: list[RequirementResult] = field(default_factory=list)

    @property
    def must_results(self) -> list[RequirementResult]:
        return [r for r in self.results if r.is_must]

    @property
    def must_met(self) -> int:
        return sum(1 for r in self.must_results if r.counts_as_met)

    @property
    def must_total(self) -> int:
        return len(self.must_results)

    @property
    def nice_met(self) -> int:
        return sum(1 for r in self.results if not r.is_must and r.counts_as_met)

    @property
    def nice_total(self) -> int:
        return sum(1 for r in self.results if not r.is_must)

    @property
    def met_labels(self) -> list[str]:
        return [r.requirement for r in self.results if r.counts_as_met]

    @property
    def missing_labels(self) -> list[str]:
        """Must-haves only. A missing nice-to-have is not a shortfall."""
        return [r.requirement for r in self.must_results if r.status != "met"]


# --------------------------------------------------------------------------
# Per-kind checks
# --------------------------------------------------------------------------
_YEARS = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years|year|yrs|yr)")

_FIELD_HINTS = (
    "computer science", "computer engineering", "information systems",
    "software", "engineering", "statistics", "mathematics", "data science",
    "information technology", "business", "commerce", "economics", "accounting",
    "architecture", "civil", "mechanical", "electrical", "design",
)


#: Words an advert wraps around a skill. They describe the level asked for, not
#: the thing itself, and matching on the whole phrase fails every time.
_QUALIFIERS = {
    "strong", "solid", "good", "excellent", "advanced", "basic", "working",
    "knowledge", "of", "in", "with", "experience", "hands-on", "hands", "on",
    "proven", "demonstrable", "familiarity", "exposure", "to", "understanding",
    "proficiency", "proficient", "skills", "skill", "ability", "and", "or",
    "a", "an", "the", "such", "as", "using", "use", "building", "maintaining",
    "for", "data", "work", "is", "required", "essential", "plus", "preferred",
}


def _requirement_terms(text: str) -> list[str]:
    """The candidate skill names inside a requirement phrase.

    "Strong SQL (joins, window functions)" -> ["Strong SQL (joins, window
    functions)", "SQL", "joins", "window functions", ...]. The full phrase is
    tried first so an exact hit still wins; the rest catch the common case where
    the advert wrapped the skill in words describing the level.
    """
    terms: list[str] = [text.strip()]

    # Alternatives, and the parenthetical detail, are all worth trying.
    for chunk in _DETAIL.split(text):
        chunk = chunk.strip()
        if chunk and chunk.lower() != text.strip().lower():
            terms.append(chunk)

    # Then the phrase with the level-words removed.
    words = [w for w in _WORD.findall(text) if w.lower() not in _QUALIFIERS]
    if words:
        terms.append(" ".join(words))
        # Single words only when they are a skill name we recognise. Without that
        # guard "Power BI" would be satisfied by "Power Query", and a candidate
        # would be credited with a tool they never used.
        terms.extend(w for w in words if canonical(w) != w.strip() or w in ALIASES)

    seen: dict[str, None] = {}
    for term in terms:
        term = term.strip(" .,-")
        if len(term) > 1:
            seen.setdefault(term, None)
    return list(seen)


def _check_skill(req: Requirement, profile: CandidateProfile) -> RequirementResult:
    haystack = profile.all_text()
    terms = _requirement_terms(req.text)

    # The skills list is the strongest signal.
    for term in terms:
        for skill in profile.skills:
            if mentions(skill, term) or mentions(term, skill):
                return RequirementResult(
                    req.text, req.kind, req.importance, "met", f"skills: {skill}"
                )

    # Then anything the CV actually demonstrates - a tool used in a project counts
    # as much as one listed in a skills section.
    for term in terms:
        if mentions(haystack, term):
            return RequirementResult(
                req.text, req.kind, req.importance, "met",
                f"'{term}' appears in the CV",
            )

    return RequirementResult(req.text, req.kind, req.importance, "not_met")


def _check_experience(req: Requirement, profile: CandidateProfile) -> RequirementResult:
    asked = _YEARS.search(req.text.lower())
    if asked:
        needed = float(asked.group(1))
        held = profile.total_years_experience
        evidence = f"{held:g} years of professional experience"
        if held >= needed:
            return RequirementResult(req.text, req.kind, req.importance, "met", evidence)
        # Close enough that a human should look rather than the system deciding.
        if held >= needed - 1:
            return RequirementResult(
                req.text, req.kind, req.importance, "partial",
                f"{evidence}, {needed:g} asked for",
            )
        return RequirementResult(
            req.text, req.kind, req.importance, "not_met", evidence
        )

    # Domain experience: "reporting in retail or public sector".
    return _check_skill(req, profile)


def _check_education(req: Requirement, profile: CandidateProfile) -> RequirementResult:
    text = req.text.lower()
    wanted_rank = 3 if "bachelor" in text or "degree" in text else 0
    for level, rank in DEGREE_RANK.items():
        if level.replace("_", " ") in text:
            wanted_rank = max(wanted_rank, rank)

    held_rank = DEGREE_RANK.get(profile.highest_degree, 0)
    if held_rank == 0:
        return RequirementResult(
            req.text, req.kind, req.importance, "not_met", "no degree found on the CV"
        )

    degree = next(
        (e for e in profile.education if DEGREE_RANK.get(e.degree, 0) == held_rank),
        None,
    )
    evidence = (
        f"{degree.degree.replace('_', ' ')} in {degree.field_of_study}".strip()
        if degree
        else profile.highest_degree
    )

    if held_rank < wanted_rank:
        return RequirementResult(
            req.text, req.kind, req.importance, "not_met", evidence
        )

    # Is the field one the advert asked for? Adverts usually say "or a related
    # field", so an unlisted field is unclear rather than a failure.
    wanted_fields = [h for h in _FIELD_HINTS if h in text]
    if wanted_fields and degree:
        field_text = f"{degree.field_of_study} {degree.institution}".lower()
        if any(h in field_text for h in wanted_fields):
            return RequirementResult(
                req.text, req.kind, req.importance, "met", evidence
            )
        if "related" in text:
            return RequirementResult(
                req.text, req.kind, req.importance, "unclear",
                f"{evidence} - related field is a judgement call",
            )
        return RequirementResult(
            req.text, req.kind, req.importance, "partial", evidence
        )

    return RequirementResult(req.text, req.kind, req.importance, "met", evidence)


def _check_language(req: Requirement, profile: CandidateProfile) -> RequirementResult:
    spoken = " ".join(profile.languages).lower()
    for language in ("english", "arabic", "french", "german", "spanish"):
        if language in req.text.lower():
            if language in spoken:
                match = next(
                    (l for l in profile.languages if language in l.lower()), language
                )
                return RequirementResult(
                    req.text, req.kind, req.importance, "met", match
                )
            # A CV written in English evidences English without a languages
            # section. Requiring one would fail people for an omission, not a gap.
            if language == "english" and (profile.skills or profile.experience):
                return RequirementResult(
                    req.text, req.kind, req.importance, "met",
                    "the CV itself is written in English",
                )
            return RequirementResult(req.text, req.kind, req.importance, "not_met")
    return _check_skill(req, profile)


#: Splits a requirement into its alternatives and its parenthetical detail.
_DETAIL = re.compile(r"\bor\b|\band\b|[,/()]")
#: A word, keeping the punctuation that lives inside names like C++ or CI/CD.
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#.\-]*")

#: An advert lists alternatives with 'or', a comma, or a slash.
_SPLIT = re.compile(r"\bor\b|,|/")
#: A word or a code like 'pl-300'. Keeps hyphens and dots inside the token.
_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-.]+")
#: A certification code identifies the credential on its own.
_CODE = re.compile(r"[a-z]{2,4}-?\d{2,4}")

# Words that describe the wrapper rather than the credential itself.
_CERT_NOISE = {
    "certification", "certifications", "certificate", "certified", "cert",
    "associate", "professional", "exam", "or", "and", "a", "an", "the",
}


def _check_certification(req: Requirement, profile: CandidateProfile) -> RequirementResult:
    """Match on the credential's identifying words, not the whole phrase.

    "PL-300 certification" must match a CV listing "Microsoft PL-300 Power BI Data
    Analyst". Matching the full phrase fails every real certification line.
    """
    held = " ".join(profile.certifications)
    if not held.strip():
        return RequirementResult(
            req.text, req.kind, req.importance, "not_met", "no certifications listed"
        )
    held_lower = held.lower()

    for option in re.split(_SPLIT, req.text):
        tokens = [
            t for t in re.findall(_TOKEN, option.lower())
            if t not in _CERT_NOISE
        ]
        if not tokens:
            continue
        # A code like "pl-300" or "dp-203" identifies the credential on its own.
        codes = [t for t in tokens if re.fullmatch(_CODE, t)]
        needles = codes or tokens
        if all(n in held_lower for n in needles):
            source = next(
                (c for c in profile.certifications
                 if all(n in c.lower() for n in needles)),
                held,
            )
            return RequirementResult(
                req.text, req.kind, req.importance, "met", source
            )

    return RequirementResult(
        req.text, req.kind, req.importance, "not_met", f"holds: {held[:60]}"
    )


_CHECKS = {
    "skill": _check_skill,
    "experience": _check_experience,
    "education": _check_education,
    "language": _check_language,
    "certification": _check_certification,
}


def match(
    profile: CandidateProfile, job: JobProfile, source_name: str = ""
) -> MatchResult:
    """Check one candidate against one vacancy. Pure computation, no network."""
    result = MatchResult(
        candidate=profile, job_title=job.title, source_name=source_name
    )
    for req in job.requirements:
        check = _CHECKS.get(req.kind, _check_skill)
        result.results.append(check(req, profile))
    return result


def match_all(
    candidates: list[tuple[str, CandidateProfile]], job: JobProfile
) -> list[MatchResult]:
    """Match a whole pool. Runs over thousands of stored candidates in under a second."""
    return [match(profile, job, source) for source, profile in candidates]
