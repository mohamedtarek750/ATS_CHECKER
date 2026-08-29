"""The ideal CV for one vacancy: what a strong application for *this* job looks like.

This answers a different question from the matcher. The matcher asks whether a
candidate is qualified. This asks whether their CV presents those qualifications
effectively for this particular role — two things an ATS routinely conflates, to
the cost of good candidates who write badly and the benefit of weak ones who write
well.

The blueprint is derived from the job deterministically. A vacancy that asks for
eight technologies needs a skills section near the top; a senior vacancy needs the
work before the education; a graduate vacancy needs projects, because there is no
work yet. None of that requires a model, and deriving it in code means it is the
same every time and can be explained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .job_profile import JobProfile

Weight = Literal["required", "recommended", "optional", "low_value"]

#: Every section a CV can have, with the heading a recruiter would expect.
SECTION_LABELS: dict[str, str] = {
    "contact": "Contact information",
    "summary": "Professional summary",
    "skills": "Core skills",
    "experience": "Professional experience",
    "projects": "Projects",
    "education": "Education",
    "certifications": "Certifications",
    "languages": "Languages",
}


@dataclass
class SectionSpec:
    """One section of the ideal CV, and why it is there."""

    key: str
    weight: Weight
    why: str
    #: What a strong version of this section contains for this job.
    should_contain: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return SECTION_LABELS.get(self.key, self.key.title())


@dataclass
class CVBlueprint:
    """The target CV for one vacancy."""

    job_title: str
    seniority: str
    sections: list[SectionSpec]
    #: The skills a strong CV for this job leads with, most important first.
    priority_skills: list[str]
    #: The shape of a good summary, as a formula rather than invented prose.
    summary_formula: str
    summary_should_mention: list[str]
    #: The shape of a good experience bullet.
    bullet_pattern: str
    wants_metrics: bool
    notes: list[str] = field(default_factory=list)

    @property
    def order(self) -> list[str]:
        return [s.key for s in self.sections]

    @property
    def required(self) -> list[SectionSpec]:
        return [s for s in self.sections if s.weight == "required"]

    def spec(self, key: str) -> SectionSpec | None:
        return next((s for s in self.sections if s.key == key), None)

    def rank_of(self, key: str) -> int | None:
        order = self.order
        return order.index(key) if key in order else None


# --------------------------------------------------------------------------
# Deriving it
# --------------------------------------------------------------------------
_SENIOR_WORDS = ("senior", "lead", "principal", "head", "manager", "director", "staff")
_JUNIOR_WORDS = ("junior", "graduate", "entry", "intern", "trainee", "fresh")

#: Roles where what was achieved matters more than which tools were used, so the
#: CV should lead with outcomes rather than a technology list.
_OUTCOME_LED = ("sales", "marketing", "account", "business development", "recruit",
                "hr ", "human resources", "manager", "consultant")


def _is_senior(job: JobProfile) -> bool:
    text = f"{job.title} {job.seniority}".lower()
    if any(word in text for word in _JUNIOR_WORDS):
        return False
    return any(word in text for word in _SENIOR_WORDS) or job.min_years_experience >= 5


def _is_junior(job: JobProfile) -> bool:
    text = f"{job.title} {job.seniority}".lower()
    return any(word in text for word in _JUNIOR_WORDS) or job.min_years_experience <= 1


def _is_outcome_led(job: JobProfile) -> bool:
    return any(word in job.title.lower() for word in _OUTCOME_LED)


def priority_skills(job: JobProfile) -> list[str]:
    """The technologies a CV for this job should lead with, must-haves first."""
    ordered: list[str] = []
    for requirement in job.requirements:
        if requirement.kind != "skill":
            continue
        if requirement.importance == "must_have":
            ordered.append(requirement.text)
    for requirement in job.requirements:
        if requirement.kind == "skill" and requirement.importance == "nice_to_have":
            ordered.append(requirement.text)
    return ordered[:12]


def blueprint_for(job: JobProfile) -> CVBlueprint:
    """Build the ideal CV for this vacancy. Deterministic - no model call."""
    senior = _is_senior(job)
    junior = _is_junior(job)
    outcome_led = _is_outcome_led(job)

    skills = priority_skills(job)
    certifications = [r.text for r in job.requirements if r.kind == "certification"]
    languages = [r.text for r in job.requirements if r.kind == "language"]
    education = [r.text for r in job.requirements if r.kind == "education"]

    # Whether a role is technical is about what it asks for, not how much. A
    # graduate advert naming two technologies is still a technical job, and a
    # bare count would file it with sales roles and bury the stack.
    skill_requirements = [r for r in job.requirements if r.kind == "skill"]
    technical = bool(skills) and (
        len(skills) >= 3
        or len(skill_requirements) >= max(1, len(job.requirements) // 2)
    )

    sections: list[SectionSpec] = [
        SectionSpec(
            "contact", "required",
            "A CV nobody can reply to cannot be actioned, whatever else it says.",
            ["Full name", "Phone", "Email", "City"]
            + (["LinkedIn or GitHub"] if technical else []),
        ),
        SectionSpec(
            "summary",
            "required" if (senior or outcome_led) else "recommended",
            "A senior application is read for positioning first."
            if senior
            else "Three lines telling the reader what this candidate is for.",
            [
                f"Target role: {job.title}",
                "Years of experience",
                *(skills[:3]),
            ],
        ),
    ]

    # A technical vacancy is scanned for its stack; an outcome-led one is read for
    # what the person delivered. That difference decides what comes next.
    if technical and not outcome_led:
        sections.append(
            SectionSpec(
                "skills", "required",
                f"This job names {len(skills)} technologies. A recruiter should find "
                f"them without reading the whole CV.",
                skills[:8],
            )
        )

    sections.append(
        SectionSpec(
            "experience",
            "recommended" if junior else "required",
            "Graduates are not expected to have much - projects carry the weight."
            if junior
            else "The strongest evidence a CV can carry for this role.",
            [
                "Job title, employer and dates for every role",
                "What was actually done, not a list of duties",
                *(["Measurable outcomes where they are true"] if senior or outcome_led else []),
                *(["The technologies used in each role"] if technical else []),
            ],
        )
    )

    sections.append(
        SectionSpec(
            "projects",
            "required" if junior and technical else "recommended" if technical else "optional",
            "With little work history, projects are where the evidence has to come from."
            if junior
            else "Projects show the tools in use rather than merely listed.",
            [f"Something using {s}" for s in skills[:3]] or ["Relevant work"],
        )
    )

    if not (technical and not outcome_led):
        sections.append(
            SectionSpec(
                "skills", "recommended",
                "Useful, but this role is judged on outcomes before tools.",
                skills[:8] or ["The tools the advert names"],
            )
        )

    sections.append(
        SectionSpec(
            "education",
            "required" if education else "recommended",
            education[0] if education
            else "Expected on a CV, but not what this role turns on.",
            education or ["Degree, institution and year"],
        )
    )

    if certifications:
        sections.append(
            SectionSpec("certifications", "recommended",
                        "The advert names certifications, so they are worth their own section.",
                        certifications))
    if languages:
        sections.append(
            SectionSpec("languages", "recommended",
                        "The advert states a language requirement.", languages))

    notes: list[str] = []
    if senior:
        notes.append(
            "Senior application: experience belongs above education. A reader "
            "deciding in twenty seconds should meet the work first."
        )
    if junior:
        notes.append(
            "Graduate application: no work history is expected. Projects and "
            "coursework carry the evidence, and should be specific about what was built."
        )
    if technical:
        notes.append(
            "Name each technology where it was used, not only in the skills list. "
            "A tool shown in a role is evidence; the same word in a list is a claim."
        )

    return CVBlueprint(
        job_title=job.title,
        seniority=job.seniority,
        sections=sections,
        priority_skills=skills,
        summary_formula=(
            "[Seniority] + [Role] + [Years] + [Core skills] + [Domain] + [What you deliver]"
        ),
        summary_should_mention=[job.title] + skills[:3],
        bullet_pattern="Action + what + technology + result",
        wants_metrics=senior or outcome_led,
        notes=notes,
    )


def render(blueprint: CVBlueprint, width: int = 56) -> str:
    """A text preview of the target layout.

    Deliberately a blueprint and not a specimen CV: it shows what each section is
    for, and never invents a candidate to fill it in.
    """
    line = "-" * width
    out = [f"+{line}+"]

    def row(text: str = "", indent: int = 1) -> None:
        out.append("|" + " " * indent + text[: width - indent].ljust(width - indent) + "|")

    row(f"IDEAL CV - {blueprint.job_title.upper()}")
    row(f"{blueprint.seniority}")
    out.append(f"+{line}+")

    for index, section in enumerate(blueprint.sections, start=1):
        tag = {
            "required": "[required]",
            "recommended": "[recommended]",
            "optional": "[optional]",
            "low_value": "[low value]",
        }[section.weight]
        row(f"{index}. {section.label.upper()}  {tag}")
        for item in section.should_contain[:4]:
            row(f"   - {item}", indent=1)
        out.append(f"+{line}+")

    return "\n".join(out)
