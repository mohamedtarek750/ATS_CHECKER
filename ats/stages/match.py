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
from ..skills import (
    ALIASES,
    canonical,
    category_members,
    concept_evidence,
    concept_for,
    implied_by,
    mentions,
)

Status = Literal["met", "partial", "not_met", "unclear"]

#: How firmly the CV supports a requirement. Separate from status on purpose: a
#: skill named in the skills section IS met - the candidate says they have it -
#: but it is not the same evidence as a skill used in a shipped project, and
#: collapsing the two either fails honest candidates or rewards padding.
EvidenceStrength = Literal["strong", "valid", "partial", "none"]

#: Where evidence was found. Searched in this order, strongest first.
EvidenceSource = Literal[
    "experience", "projects", "skills", "certifications", "education",
    "summary", "none",
]

#: Sections, in the order a recruiter would weigh them.
SOURCE_ORDER: tuple[EvidenceSource, ...] = (
    "experience", "projects", "skills", "certifications", "education", "summary",
)

#: What each source is worth. Experience and projects show the skill in use;
#: the rest show it asserted.
SOURCE_STRENGTH: dict[str, EvidenceStrength] = {
    "experience": "strong",
    "projects": "strong",
    "skills": "valid",
    "certifications": "valid",
    "education": "valid",
    "summary": "valid",
}

#: Share of a requirement's weight each level earns.
STRENGTH_CREDIT: dict[str, float] = {
    "strong": 1.0, "valid": 0.8, "partial": 0.5, "none": 0.0,
}

SOURCE_LABEL = {
    "experience": "Professional experience",
    "projects": "Projects",
    "skills": "Technical skills",
    "certifications": "Certifications",
    "education": "Education",
    "summary": "Summary",
    "none": "Not found",
}

DEGREE_RANK = {
    "unknown": 0, "high_school": 1, "diploma": 2,
    "bachelor": 3, "master": 4, "phd": 5,
}


#: How a requirement was satisfied. Recorded because "the CV proves it" and
#: "the CV claims it" are different facts, and an ATS that conflates them cannot
#: tell an engineer from a keyword-stuffer.
MatchKind = Literal[
    "demonstrated",   # used in a job, project or certification
    "claimed",        # present only in the skills list, nothing behind it
    "equivalent",     # a different name for the same thing
    "substitute",     # a comparable tool where the advert allowed one
    "derived",        # computed, e.g. years from dated roles
    "absent",
]


@dataclass
class RequirementResult:
    requirement: str
    kind: str
    importance: str
    status: Status
    evidence: str = ""
    match_kind: MatchKind = "absent"
    #: 0-100. Low confidence is a prompt for a human, not a quiet decision.
    confidence: int = 0
    strength: EvidenceStrength = "none"
    source: EvidenceSource = "none"
    #: Why this verdict, in a sentence a recruiter or candidate can act on.
    explanation: str = ""

    @property
    def credit(self) -> float:
        """Share of this requirement's weight the candidate has earned."""
        return STRENGTH_CREDIT[self.strength]

    @property
    def source_label(self) -> str:
        return SOURCE_LABEL[self.source]

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


def section_texts(profile: CandidateProfile) -> dict[str, str]:
    """The CV split by section, so evidence can be attributed to where it sits.

    Attribution is the whole point. "Scikit-learn" in a project and the same word
    in a skills list are both true and are not the same claim, and a matcher that
    cannot say which one it found cannot explain itself.
    """
    experience_parts: list[str] = []
    for job in profile.experience:
        experience_parts.append(f"{job.title} {job.company}")
        experience_parts.extend(job.highlights)

    return {
        "experience": " \n".join(experience_parts),
        "projects": " \n".join(profile.projects),
        "skills": " \n".join(profile.skills),
        "certifications": " \n".join(profile.certifications),
        "education": " \n".join(
            f"{e.field_of_study} {e.institution}" for e in profile.education
        ),
        "summary": profile.summary_text,
    }


def _skill_hit(text: str, terms: list[str]) -> str | None:
    """The first term this text demonstrates, or None."""
    for term in terms:
        if mentions(text, term):
            return term
    return None


def _quote_from(text: str, term: str, source: str) -> str:
    """The line that carries the evidence, so a verdict can be checked."""
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Concept members arrive with the version stripped ("densenet" for
        # "DenseNet169"), which the alias matcher will not find. Fall back to a
        # plain substring so the quote is the candidate's own sentence rather
        # than the token we happened to search for.
        if mentions(line, term) or term.lower() in line.lower():
            if source == "skills":
                return f"Technical Skills: {term}"
            return f'"{line[:130]}"'
    return f"{SOURCE_LABEL[source]}: {term}"


def _find_in_sections(
    sections: dict[str, str], terms: list[str]
) -> tuple[str, str, str] | None:
    """Search the CV in priority order. Returns (source, term, quote)."""
    for source in SOURCE_ORDER:
        text = sections.get(source, "")
        if not text.strip():
            continue
        hit = _skill_hit(text, terms)
        if hit:
            return (source, hit, _quote_from(text, hit, source))
    return None


def _concept_in_sections(
    sections: dict[str, str], concept: str
) -> tuple[str, list[str], str] | None:
    """Where a concept is evidenced, and by which specific members."""
    for source in SOURCE_ORDER:
        text = sections.get(source, "")
        if not text.strip():
            continue
        members = concept_evidence(concept, text)
        if members:
            quote = _quote_from(text, members[0], source)
            return (source, members, quote)
    return None


#: How many skills a CV may claim per line of work it actually describes before
#: the list stops being a summary of the CV and starts being the whole of it.
_CLAIMS_PER_DEMONSTRATION = 4


def _uncorroborated(profile: CandidateProfile) -> bool:
    """True when the skills list makes far more claims than the CV can support.

    A CV that names thirty tools and describes one internship bullet has given
    the reader one place to check thirty assertions. That is not a lie and it is
    not scored as one - the skills still count as met, because the candidate does
    claim them - but it cannot count the same as a CV where the work is on the
    page. A genuine engineer's skills list is a summary of their CV; a stuffed one
    IS the CV.

    Written as a ratio rather than a threshold on either number so that a short,
    honest CV is not caught: three skills and one project passes, thirty skills
    and one project does not.
    """
    demonstrations = sum(len(job.highlights) for job in profile.experience)
    demonstrations += len(profile.projects)
    return len(profile.skills) > _CLAIMS_PER_DEMONSTRATION * max(demonstrations, 1)


def _strength_for(source: str, profile: CandidateProfile) -> EvidenceStrength:
    """How firmly this source supports a claim, given the rest of the CV."""
    declared = SOURCE_STRENGTH[source]
    if declared == "valid" and source == "skills" and _uncorroborated(profile):
        return "partial"
    return declared


def _part(req: Requirement, text: str) -> Requirement:
    """One alternative or component of a compound requirement, on its own."""
    return req.model_copy(update={"text": text, "any_of": [], "all_of": []})


def _check_skill(req: Requirement, profile: CandidateProfile) -> RequirementResult:
    """Resolve the requirement's logic, then check what it actually asks for.

    "Docker or Kubernetes" is one requirement, not two. Scoring it as two is how a
    candidate who runs everything on Kubernetes ends up marked 50% on a line they
    fully satisfy - which is the single most common way an ATS rejects someone the
    employer wanted to interview.
    """
    if len(req.all_of) > 1:
        return _combine_all(req, [
            _check_atom(_part(req, text), profile) for text in req.all_of
        ])
    if len(req.any_of) > 1:
        return _combine_any(req, [
            _check_atom(_part(req, text), profile) for text in req.any_of
        ])
    return _check_atom(req, profile)


def _combine_any(req: Requirement, parts: list[RequirementResult]) -> RequirementResult:
    """The advert offered a choice, so the best answer is the answer."""
    best = max(parts, key=lambda r: (r.credit, r.confidence))
    offered = ", ".join(p.requirement for p in parts)
    if best.status == "not_met":
        return RequirementResult(
            req.text, req.kind, req.importance, "not_met", "None found",
            match_kind="absent", confidence=best.confidence,
            strength="none", source="none",
            explanation=(
                "None of the alternatives the advert allows "
                f"({', '.join(p.requirement for p in parts)}) appear on the CV."
            ),
        )
    return RequirementResult(
        req.text, req.kind, req.importance, best.status, best.evidence,
        match_kind=best.match_kind, confidence=best.confidence,
        strength=best.strength, source=best.source,
        explanation=(
            f"{best.explanation} The advert accepts any of {offered}, and "
            f"{best.requirement} satisfies it."
        ),
    )


def _combine_all(req: Requirement, parts: list[RequirementResult]) -> RequirementResult:
    """Every component was asked for, so the weakest one is the verdict."""
    weakest = min(parts, key=lambda r: (r.credit, r.confidence))
    missing = [p.requirement for p in parts if p.status == "not_met"]
    if missing:
        # Quote the half that IS evidenced. Showing "none found" next to a
        # requirement the candidate half-meets hides the work they did do.
        held = max(parts, key=lambda r: (r.credit, r.confidence))
        partial = len(missing) < len(parts)
        return RequirementResult(
            req.text, req.kind, req.importance,
            "partial" if partial else "not_met",
            held.evidence if partial else "None found",
            match_kind="absent", confidence=weakest.confidence,
            strength="partial" if partial else "none",
            source=held.source if partial else "none",
            explanation=(
                f"This requirement needs all of "
                f"{', '.join(p.requirement for p in parts)}; "
                f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} "
                f"not evidenced."
            ),
        )
    return RequirementResult(
        req.text, req.kind, req.importance, weakest.status, weakest.evidence,
        match_kind=weakest.match_kind, confidence=weakest.confidence,
        strength=weakest.strength, source=weakest.source,
        explanation=(
            f"All parts are evidenced; the weakest is {weakest.requirement}. "
            f"{weakest.explanation}"
        ),
    )


def _check_atom(req: Requirement, profile: CandidateProfile) -> RequirementResult:
    """Match one indivisible skill requirement, and say how firmly and from where.

    A skill in the Technical Skills section counts as met - the candidate is
    asserting it, and an ATS that calls that "not found" is simply wrong about the
    document. It earns less than the same skill shown in a role, which is what the
    strength field is for.
    """
    sections = section_texts(profile)
    terms = _requirement_terms(req.text)
    # The advert's own synonyms for the same thing. A CV that says "trained a
    # ResNet" has done deep learning whether or not it uses the phrase.
    terms.extend(k for k in req.keywords if k and k not in terms)

    def result(
        status, strength, source, evidence, explanation, kind, confidence
    ) -> RequirementResult:
        return RequirementResult(
            req.text, req.kind, req.importance, status, evidence,
            match_kind=kind, confidence=confidence, strength=strength,
            source=source, explanation=explanation,
        )

    # 1. The requirement names a concept, and the CV shows the concept's parts.
    #    "Knowledge of CNNs" proven by DenseNet and ResNet is stronger evidence
    #    than the acronym would have been, not weaker.
    concept = concept_for(req.text)
    if concept:
        found = _concept_in_sections(sections, concept)
        if found:
            source, members, quote = found
            named = ", ".join(m.title() for m in members[:3])
            strength = _strength_for(source, profile)
            exact = concept.lower() in " ".join(members)
            return result(
                "met", strength, source, quote,
                f"{named} {'is' if len(members) == 1 else 'are'} "
                f"{concept}-related work, "
                f"{'demonstrated in ' + SOURCE_LABEL[source].lower() if strength == 'strong' else 'declared under ' + SOURCE_LABEL[source].lower()}."
                if not exact
                else f"{concept} appears directly in {SOURCE_LABEL[source].lower()}.",
                "demonstrated" if strength == "strong" else "claimed",
                90 if strength == "strong" else 76,
            )

    # 2. The named skill itself, wherever it appears - strongest section wins.
    found = _find_in_sections(sections, terms)
    if found:
        source, term, quote = found
        strength = _strength_for(source, profile)
        canonical_name = canonical(term)
        renamed = canonical_name.lower() not in req.text.lower()

        if strength == "strong":
            explanation = (
                f"Demonstrated in {SOURCE_LABEL[source].lower()}"
                + (f" as {term}" if renamed else "")
                + "."
            )
        else:
            if source == "skills" and strength == "partial":
                explanation = (
                    f"Listed under {SOURCE_LABEL[source].lower()}. The CV claims "
                    f"{len(profile.skills)} skills but describes very little work, "
                    f"so there is nothing on it that corroborates this one."
                )
            elif source == "skills":
                explanation = (
                    f"Explicitly listed under {SOURCE_LABEL[source].lower()}, though "
                    f"not yet demonstrated in a role or project."
                )
            else:
                explanation = f"Evidenced by {SOURCE_LABEL[source].lower()}."
        return result(
            "met", strength, source, quote, explanation,
            "equivalent" if renamed else
            ("demonstrated" if strength == "strong" else "claimed"),
            90 if strength == "strong" else 78,
        )

    # 3. Implied by something the CV shows: PySpark is Python.
    for implied_source in implied_by(req.text):
        found = _find_in_sections(sections, [implied_source])
        if found:
            source, term, quote = found
            strength = "strong" if _strength_for(source, profile) == "strong" else "partial"
            return result(
                "met" if strength == "strong" else "partial",
                strength, source, quote,
                f"{implied_source} requires {req.text}, so this is indirect but "
                f"reliable evidence from {SOURCE_LABEL[source].lower()}.",
                "equivalent", 74,
            )

    # 4. A comparable tool, where the advert invited one.
    for member in category_members(req.text):
        found = _find_in_sections(sections, [member])
        if found:
            source, term, quote = found
            strength = _strength_for(source, profile)
            return result(
                "met", strength, source, quote,
                f"{member} is a comparable tool and the requirement allows one; "
                f"found in {SOURCE_LABEL[source].lower()}.",
                "substitute", 78 if strength == "strong" else 70,
            )

    # 5. Related concepts only - genuinely partial, and said so.
    related = _related_support(req.text, sections)
    if related:
        source, note, quote = related
        return result(
            "partial", "partial", source, quote, note, "substitute", 55,
        )

    return result(
        "not_met", "none", "none", "None found",
        "No explicit or strongly related evidence was found anywhere in the CV.",
        "absent", 88,
    )


def _related_support(
    requirement: str, sections: dict[str, str]
) -> tuple[str, str, str] | None:
    """Adjacent evidence: real, but not the thing that was asked for.

    Reported as partial with the gap named, rather than as a match. Deployment via
    Streamlit is relevant to MLOps and is not MLOps, and saying so is more useful
    to both sides than either a tick or a cross.
    """
    concept = concept_for(requirement)
    if not concept:
        return None

    #: Concepts that sit next to each other, and what is still missing.
    neighbours: dict[str, tuple[tuple[str, ...], str]] = {
        "MLOps": (
            ("Containerisation", "CI/CD", "Cloud"),
            "core MLOps tooling such as MLflow, model monitoring or pipeline "
            "orchestration is not shown",
        ),
        "Deep Learning": (
            ("Machine Learning", "Machine Learning Algorithms"),
            "no neural-network or deep-learning framework work is shown",
        ),
        "Computer Vision": (
            ("Deep Learning", "CNN"),
            "no image-specific work such as OpenCV, detection or segmentation is shown",
        ),
        "Big Data": (("ETL", "Databases"), "no distributed processing is shown"),
        "CI/CD": (("Version Control", "Containerisation"), "no pipeline automation is shown"),
        "Cloud": (("Containerisation",), "no cloud platform is named"),
    }
    entry = neighbours.get(concept)
    if not entry:
        return None

    adjacent, gap = entry
    for source in SOURCE_ORDER:
        text = sections.get(source, "")
        if not text.strip():
            continue
        for neighbour in adjacent:
            members = concept_evidence(neighbour, text)
            if members:
                quote = _quote_from(text, members[0], source)
                return (
                    source,
                    f"{members[0].title()} is adjacent to {concept}, but {gap}.",
                    quote,
                )
    return None


def _check_experience(req: Requirement, profile: CandidateProfile) -> RequirementResult:
    asked = _YEARS.search(req.text.lower())
    if asked:
        needed = float(asked.group(1))
        held = profile.total_years_experience
        evidence = f"{held:g} years of professional experience"
        if held >= needed:
            return RequirementResult(
                req.text, req.kind, req.importance, "met", evidence,
                match_kind="derived", confidence=80,
                strength="strong", source="experience",
                explanation=(
                    f"Dated roles on the CV total {held:g} years, meeting the "
                    f"{needed:g} the advert asks for."
                ),
            )
        # A year short is a near miss a person should look at. Three years short
        # of a senior role is not - scoring those the same is how a junior ends up
        # ranked beside somebody with a decade.
        if held >= needed - 1:
            return RequirementResult(
                req.text, req.kind, req.importance, "partial",
                f"{evidence}, {needed:g} asked for", match_kind="derived",
                confidence=75, strength="partial", source="experience",
                explanation=(
                    f"{held:g} years against the {needed:g} asked for - close "
                    f"enough that a person should decide."
                ),
            )
        return RequirementResult(
            req.text, req.kind, req.importance, "not_met",
            f"{evidence}, {needed:g} asked for", match_kind="absent", confidence=85,
            strength="none", source="experience",
            explanation=(
                f"{held:g} years of dated experience against the {needed:g} "
                f"required."
            ),
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
            req.text, req.kind, req.importance, "not_met",
            "no degree found on the CV", match_kind="absent", confidence=80,
            strength="none", source="none",
            explanation="No degree appears anywhere on the CV.",
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
            req.text, req.kind, req.importance, "not_met", evidence,
            match_kind="derived", confidence=85,
            strength="none", source="education",
            explanation=f"The CV shows {evidence}, below the level required.",
        )

    # Is the field one the advert asked for? Adverts usually say "or a related
    # field", so an unlisted field is unclear rather than a failure.
    wanted_fields = [h for h in _FIELD_HINTS if h in text]
    if wanted_fields and degree:
        field_text = f"{degree.field_of_study} {degree.institution}".lower()
        if any(h in field_text for h in wanted_fields):
            return RequirementResult(
                req.text, req.kind, req.importance, "met", evidence,
                match_kind="demonstrated", confidence=92,
                strength="strong", source="education",
                explanation=f"{evidence} - degree and field both match.",
            )

        # "or a related field" is in the advert for a reason. Computer and
        # Systems Engineering is related to Computer Science by any reading, and
        # refusing it on an exact-string test rejects the candidate the clause
        # was written to include.
        if "related" in text or "or equivalent" in text:
            wanted_words = {
                word
                for field in wanted_fields
                for word in field.split()
                if len(word) > 3
            }
            held_words = set(re.findall(r"[a-z]{4,}", field_text))
            if wanted_words & held_words:
                shared = ", ".join(sorted(wanted_words & held_words))
                return RequirementResult(
                    req.text, req.kind, req.importance, "met",
                    f"{evidence} - a related field ({shared})",
                    match_kind="equivalent", confidence=70,
                    strength="valid", source="education",
                    explanation=(
                        f"{evidence}. The advert allows a related field and this "
                        f"one shares its subject matter ({shared})."
                    ),
                )
            return RequirementResult(
                req.text, req.kind, req.importance, "unclear",
                f"{evidence} - whether this counts as related is a human call",
                match_kind="derived", confidence=40,
                strength="partial", source="education",
                explanation=(
                    f"{evidence}. The advert allows a related field; whether this "
                    f"one qualifies is a human decision."
                ),
            )

        return RequirementResult(
            req.text, req.kind, req.importance, "partial", evidence,
            match_kind="derived", confidence=55,
            strength="partial", source="education",
            explanation=f"{evidence}, in a different field from the one named.",
        )

    return RequirementResult(
        req.text, req.kind, req.importance, "met", evidence,
        match_kind="demonstrated", confidence=85,
        strength="strong", source="education",
        explanation=f"{evidence} meets the education requirement.",
    )


def _check_language(req: Requirement, profile: CandidateProfile) -> RequirementResult:
    spoken = " ".join(profile.languages).lower()
    for language in ("english", "arabic", "french", "german", "spanish"):
        if language in req.text.lower():
            if language in spoken:
                match = next(
                    (l for l in profile.languages if language in l.lower()), language
                )
                return RequirementResult(
                    req.text, req.kind, req.importance, "met", match,
                    match_kind="demonstrated", confidence=85,
                    strength="valid", source="skills",
                    explanation=f"Stated on the CV as {match}.",
                )
            # A CV written in English evidences English without a languages
            # section. Requiring one would fail people for an omission, not a gap.
            if language == "english" and (profile.skills or profile.experience):
                return RequirementResult(
                    req.text, req.kind, req.importance, "met",
                    "the CV itself is written in English",
                    match_kind="derived", confidence=78,
                    strength="valid", source="summary",
                    explanation=(
                        "The CV is written in English, which evidences the "
                        "requirement even without a languages section."
                    ),
                )
            return RequirementResult(
                req.text, req.kind, req.importance, "not_met", "None found",
                match_kind="absent", confidence=80,
                strength="none", source="none",
                explanation=f"No evidence of {language.title()} on the CV.",
            )
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
            req.text, req.kind, req.importance, "not_met", "None found",
            match_kind="absent", confidence=88,
            strength="none", source="none",
            explanation="The CV lists no certifications.",
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
                req.text, req.kind, req.importance, "met", source,
                match_kind="demonstrated", confidence=88,
                strength="valid", source="certifications",
                explanation=f"Held: {source}.",
            )

    return RequirementResult(
        req.text, req.kind, req.importance, "not_met", f"Holds: {held[:80]}",
        match_kind="absent", confidence=84,
        strength="none", source="certifications",
        explanation="Certifications are listed, but not the one required.",
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
