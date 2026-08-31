"""The job being hired for, and the requirements a CV is screened against.

A profile is created once per vacancy from the job description HR writes, reviewed
by a human, then reused for every CV in that intake. Storing it as JSON means the
exact criteria a decision was made under can be produced months later, which a
score in a model's head cannot.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .config import PROJECT_ROOT

Importance = Literal["must_have", "nice_to_have"]
RequirementKind = Literal[
    "skill",
    "experience",
    "education",
    "certification",
    "language",
    "other",
]


class Requirement(BaseModel):
    """One checkable thing the job asks for."""

    text: str = Field(
        description=(
            "The requirement in a few words, as a hiring manager would say it: "
            "'3+ years of SQL', 'Bachelor in Computer Science', 'Power BI'. One "
            "requirement per entry - never bundle several into one line."
        )
    )
    kind: RequirementKind
    any_of: list[str] = Field(
        default_factory=list,
        description=(
            "Alternatives that each satisfy this requirement on their own, when "
            "the advert says 'or': 'Docker or Kubernetes' is ONE requirement with "
            "any_of ['Docker', 'Kubernetes'], not two requirements the candidate "
            "is then marked down for half-meeting."
        ),
    )
    all_of: list[str] = Field(
        default_factory=list,
        description=(
            "Parts that must ALL be present, when the advert genuinely means and: "
            "'SQL and data modelling for reporting' where neither half is useful "
            "alone. Use sparingly - separate skills belong in separate entries."
        ),
    )
    keywords: list[str] = Field(
        default_factory=list,
        description=(
            "Other words a CV might use for the same thing: tools, libraries, "
            "abbreviations, near-synonyms. 'Deep learning' -> ['neural network', "
            "'CNN', 'TensorFlow', 'PyTorch']. These widen what counts as evidence; "
            "they never add a new requirement of their own."
        ),
    )
    importance: Importance = Field(
        description=(
            "'must_have' only when the job description states it as required, "
            "essential, or a minimum. Anything phrased as preferred, a plus, "
            "desirable, or nice to have is 'nice_to_have'. When the wording is "
            "ambiguous, choose nice_to_have - over-marking must_haves silently "
            "rejects people the employer would have wanted to see."
        )
    )


#: Words that describe how much of a skill is wanted, not which skill it is.
#: "Strong SQL" and "SQL" are the same requirement written twice.
_LEVEL_WORDS = {
    "strong", "solid", "excellent", "good", "advanced", "basic", "deep",
    "proven", "demonstrated", "hands", "on", "hands-on", "experience", "with",
    "of", "in", "the", "a", "an", "and", "or", "working", "knowledge",
    "understanding", "skills", "ability", "to", "familiarity", "familiar",
    "proficiency", "proficient", "expertise", "expert", "competent", "using",
    "use", "practical", "extensive", "significant", "some", "very",
}


def _requirement_key(req: "Requirement") -> str:
    """What this requirement is about, with the adjectives stripped off."""
    from .skills import canonical

    words = re.findall(r"[a-z0-9+#.]+", req.text.lower())
    core = [w for w in words if w not in _LEVEL_WORDS]
    text = " ".join(core or words)
    return canonical(text).lower()


class JobProfile(BaseModel):
    """A vacancy, and everything a CV gets measured against."""

    title: str = Field(description="The job title, e.g. 'Senior Data Analyst'.")
    seniority: str = Field(description="e.g. 'Fresh graduate', 'Mid-level', 'Senior'.")
    summary: str = Field(description="One sentence on what the role does.")
    min_years_experience: float = Field(
        description="Minimum professional years stated. 0 if none is stated."
    )
    requirements: list[Requirement] = Field(
        description="Every checkable requirement, must-haves and nice-to-haves."
    )

    # --- bookkeeping, not filled by the model ---
    created: str = ""
    source_text: str = ""

    def deduplicate(self) -> "JobProfile":
        """Drop requirements that repeat one already on the list.

        Adverts say the same thing twice - once in "Requirements" and again in
        "What you will do" - and an extracted checklist inherits the repetition.
        Left in, a duplicated skill is scored twice, so a candidate missing one
        common tool loses double the weight of a candidate missing a rarer one.
        The must-have wins over its nice-to-have twin, never the other way round.
        """
        kept: list[Requirement] = []
        seen: dict[tuple[str, str], int] = {}
        for req in self.requirements:
            key = (req.kind, _requirement_key(req))
            if key in seen:
                index = seen[key]
                # A thing asked for twice, once as essential, is essential.
                if (
                    req.importance == "must_have"
                    and kept[index].importance == "nice_to_have"
                ):
                    kept[index] = req
                continue
            seen[key] = len(kept)
            kept.append(req)
        self.requirements = kept
        return self

    @property
    def must_haves(self) -> list[Requirement]:
        return [r for r in self.requirements if r.importance == "must_have"]

    @property
    def nice_to_haves(self) -> list[Requirement]:
        return [r for r in self.requirements if r.importance == "nice_to_have"]

    @property
    def slug(self) -> str:
        base = re.sub(r"[^A-Za-z0-9]+", "_", self.title).strip("_") or "Job"
        return base[:60]

    def as_prompt_block(self) -> str:
        """How the profile is shown to the model when screening a CV."""
        lines = [
            f"Job title : {self.title}",
            f"Seniority : {self.seniority}",
            f"Summary   : {self.summary}",
        ]
        if self.min_years_experience:
            lines.append(f"Minimum experience: {self.min_years_experience} years")

        lines.append("\nMUST HAVE - the job states these as required:")
        if self.must_haves:
            lines.extend(f"  - [{r.kind}] {r.text}" for r in self.must_haves)
        else:
            lines.append("  (none stated)")
        lines.append("\nNICE TO HAVE - preferred, but their absence is not a failure:")
        if self.nice_to_haves:
            lines.extend(f"  - [{r.kind}] {r.text}" for r in self.nice_to_haves)
        else:
            lines.append("  (none stated)")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
def profiles_dir() -> Path:
    path = PROJECT_ROOT / "data" / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save(profile: JobProfile, name: str | None = None) -> Path:
    """Persist a profile. The stored file is the record of what was required."""
    if not profile.created:
        profile.created = date.today().isoformat()
    path = profiles_dir() / f"{name or profile.slug}.json"
    path.write_text(
        json.dumps(profile.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


def load(path: str | Path) -> JobProfile:
    path = Path(path)
    if not path.exists() and not path.is_absolute():
        candidate = profiles_dir() / path.name
        if candidate.exists():
            path = candidate
        elif (profiles_dir() / f"{path.name}.json").exists():
            path = profiles_dir() / f"{path.name}.json"
    return JobProfile.model_validate_json(path.read_text(encoding="utf-8"))


def available() -> list[Path]:
    return sorted(profiles_dir().glob("*.json"))
