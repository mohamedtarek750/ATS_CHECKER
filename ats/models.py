"""The normalized candidate record — stage 2's output, and the system's core asset.

Every later stage reads this and never the original file. Parsing a CV is the only
expensive step, so it happens once per document, ever: matching a stored candidate
against a new vacancy costs nothing.

Everything here is normalized, meaning "MS SQL Server", "T-SQL" and "SQL" all end up
as the same token. Without that, matching degenerates into string comparison and
quietly fails candidates who spelled a skill differently.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DegreeLevel = Literal[
    "high_school", "diploma", "bachelor", "master", "phd", "unknown"
]

Seniority = Literal[
    "student", "intern", "junior", "mid", "senior", "lead", "manager", "unknown"
]


class Education(BaseModel):
    degree: DegreeLevel
    field_of_study: str = Field(description="e.g. 'Computer Science'. '' if unclear.")
    institution: str = Field(description="University or school name. '' if absent.")
    graduation_year: int = Field(description="Year, or 0 if not stated.")


class Experience(BaseModel):
    title: str = Field(description="Job title as written on the CV.")
    company: str = Field(description="Employer name. '' if absent.")
    start: str = Field(description="YYYY-MM, or YYYY, or '' if not stated.")
    end: str = Field(description="YYYY-MM, YYYY, 'present', or '' if not stated.")
    years: float = Field(description="Duration in years. 0 if it cannot be worked out.")
    is_internship: bool
    highlights: list[str] = Field(
        description="Up to 4 things they actually did, in their own words, trimmed."
    )


class CandidateProfile(BaseModel):
    """One person, normalized. Stage 2 fills this in; nothing else writes to it."""

    # --- identity ---
    full_name: str = Field(description="Full name, or '' if not found.")
    email: str = Field(description="Primary email, lowercased. '' if not found.")
    phone: str = Field(description="Primary phone. '' if not found.")
    location: str = Field(description="City, country. '' if not stated.")
    links: list[str] = Field(description="LinkedIn/GitHub/portfolio URLs found.")

    # --- what they are ---
    headline: str = Field(
        description="Their current or target role in a few words, e.g. 'Data Engineer'."
    )
    seniority: Seniority
    total_years_experience: float = Field(
        description=(
            "Professional years excluding internships and study. Count real overlap "
            "only - do not add up concurrent roles twice. 0 for a student."
        )
    )

    # --- the evidence ---
    education: list[Education]
    experience: list[Experience] = Field(description="Most recent first.")
    skills: list[str] = Field(
        description=(
            "Every concrete skill, tool, language or framework the CV demonstrates - "
            "from the skills section AND from the projects and jobs. Use the common "
            "canonical name: 'SQL' not 'MS SQL Server', 'Power BI' not 'PowerBI', "
            "'JavaScript' not 'JS'. Lowercase is not required. No soft skills."
        )
    )
    certifications: list[str] = Field(description="Name and issuer where given.")
    languages: list[str] = Field(description="Spoken languages, e.g. 'Arabic (native)'.")
    projects: list[str] = Field(
        description="Project name plus the stack, one line each. Empty list if none."
    )

    # --- document-level facts, not judgements ---
    document_type: Literal[
        "cv_resume",
        "cover_letter",
        "certificate_or_transcript",
        "academic_paper",
        "job_description",
        "portfolio_or_project_doc",
        "invoice_or_form",
        "other_document",
    ]
    is_cv: bool
    ai_generated_score: int = Field(
        ge=0,
        le=100,
        description=(
            "Probability the CV's substance was LLM-generated. A flag for a human, "
            "never a rejection. Never raise it for a polished template, non-native "
            "English, or a CV merely tidied up with AI help."
        ),
    )
    ai_signals: list[str] = Field(description="Concrete evidence, quoted from the CV.")

    def skills_lower(self) -> set[str]:
        return {s.strip().lower() for s in self.skills if s.strip()}

    @property
    def highest_degree(self) -> DegreeLevel:
        order: list[DegreeLevel] = [
            "unknown", "high_school", "diploma", "bachelor", "master", "phd",
        ]
        best = "unknown"
        for entry in self.education:
            if order.index(entry.degree) > order.index(best):
                best = entry.degree
        return best  # type: ignore[return-value]

    def evidence_text(self) -> str:
        """Only what the candidate has actually SHOWN doing.

        Deliberately excludes the skills list. A skill named in a job, a project or
        a certification is evidence; the same word in a skills wall is a claim.
        Without this separation an ATS cannot tell a keyword-stuffer from an
        engineer, because to a string search they look identical.
        """
        parts: list[str] = [self.headline]
        for job in self.experience:
            parts.append(f"{job.title} {job.company} " + " ".join(job.highlights))
        parts.extend(self.projects)
        parts.extend(self.certifications)
        for edu in self.education:
            parts.append(f"{edu.field_of_study} {edu.institution}")
        return " ".join(parts).lower()

    @property
    def has_real_experience(self) -> bool:
        """Any non-internship role at all. A claim from someone with none is thin."""
        return any(not job.is_internship for job in self.experience)

    def all_text(self) -> str:
        """Everything the candidate mentions, claims included."""
        parts = [self.headline, " ".join(self.skills), " ".join(self.certifications)]
        for job in self.experience:
            parts.append(f"{job.title} {job.company} " + " ".join(job.highlights))
        for edu in self.education:
            parts.append(f"{edu.field_of_study} {edu.institution}")
        parts.extend(self.projects)
        parts.extend(self.languages)
        return " ".join(parts).lower()
