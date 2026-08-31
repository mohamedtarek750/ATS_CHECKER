"""Stage 5 - order the pool and cut it into tiers. No model call, no configuration.

The weights below are fixed in code deliberately. They are not a dial for a
recruiter to turn: nudging a weight silently reorders real people, and nobody
reviews who moved down. What HR sees is a tier and the requirements behind it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .match import MatchResult

Tier = Literal["shortlist", "review", "not_a_match", "not_a_cv"]

TIER_LABEL = {
    "shortlist": "Shortlist",
    "review": "Worth a look",
    "not_a_match": "Not a match",
    "not_a_cv": "Not a CV",
}

TIER_FOLDER = {
    "shortlist": "1_shortlist",
    "review": "2_worth_a_look",
    "not_a_match": "3_not_a_match",
    "not_a_cv": "0_not_a_cv",
}

# Fixed weights, per requirement, by what it is and whether it is required.
# A missing Docker listed as "preferred" must not cost what a missing mandatory
# skill costs - treating the two alike is why capable candidates score like
# unqualified ones.
_WEIGHTS: dict[tuple[str, str], float] = {
    ("skill", "must_have"): 3.0,
    ("skill", "nice_to_have"): 1.0,
    ("certification", "must_have"): 3.0,
    ("certification", "nice_to_have"): 1.0,
    ("education", "must_have"): 2.0,
    ("education", "nice_to_have"): 1.0,
    ("experience", "must_have"): 3.0,
    ("experience", "nice_to_have"): 1.0,
    ("language", "must_have"): 2.0,
    ("language", "nice_to_have"): 1.0,
    ("other", "must_have"): 2.0,
    ("other", "nice_to_have"): 1.0,
}


def weight_of(result) -> float:
    """What this requirement is worth."""
    return _WEIGHTS.get((result.kind, result.importance), 1.0)


def _weighted(results) -> tuple[float, float]:
    """(earned, possible) over a set of requirement results.

    Credit comes from the evidence strength recorded during matching, so a skill
    shown in a project earns full weight and the same skill listed under Technical
    Skills earns most of it - which is the difference the CV actually contains.
    """
    earned = possible = 0.0
    for result in results:
        weight = weight_of(result)
        possible += weight
        earned += weight * result.credit
    return (earned, possible)


# Kept for the ordering score, which is a separate concern from the percentage.
_MUST_WEIGHT = 100.0
_NICE_WEIGHT = 10.0


@dataclass
class RankedCandidate:
    match: MatchResult
    tier: Tier
    score: float
    reason: str

    @property
    def required_percent(self) -> int:
        """How much of what the job REQUIRES this candidate meets."""
        earned, possible = _weighted(self.match.must_results)
        return int(round(earned / possible * 100)) if possible else 100

    @property
    def preferred_percent(self) -> int:
        """The same for the preferred list, reported separately."""
        preferred = [r for r in self.match.results if not r.is_must]
        earned, possible = _weighted(preferred)
        return int(round(earned / possible * 100)) if possible else 0

    @property
    def percent(self) -> int:
        """How much of what the job asked for this candidate meets, 0-100.

        Weighted by requirement: a required skill is worth three points, a
        preferred one is worth one, and each is earned in proportion to how firmly
        the CV evidences it. Every point is traceable to a named requirement and a
        line of the CV, which is the only kind of percentage worth putting next to
        a person's name.
        """
        earned, possible = _weighted(self.match.results)
        return int(round(earned / possible * 100)) if possible else 0

    @property
    def percent_label(self) -> str:
        return f"{self.percent}%"

    @property
    def name(self) -> str:
        return self.match.candidate.full_name or self.match.source_name

    @property
    def headline(self) -> str:
        return self.match.candidate.headline

    @property
    def flagged_ai(self) -> bool:
        return self.match.candidate.ai_generated_score >= 70


def _score(result: MatchResult) -> float:
    """Ordering score. Required requirements dominate it by construction."""
    must_earned, must_possible = _weighted(result.must_results)
    must = (must_earned / must_possible if must_possible else 1.0) * _MUST_WEIGHT

    preferred = [r for r in result.results if not r.is_must]
    nice_earned, nice_possible = _weighted(preferred)
    nice = (nice_earned / nice_possible if nice_possible else 0.0) * _NICE_WEIGHT

    return round(must + nice, 2)


def _tier(result: MatchResult) -> tuple[Tier, str]:
    if not result.candidate.is_cv:
        kind = result.candidate.document_type.replace("_", " ")
        return "not_a_cv", f"This is a {kind}, not a CV."

    met, total = result.must_met, result.must_total
    if total == 0:
        return "review", "The vacancy lists no must-have requirements."

    missing = result.missing_labels
    if met == total:
        return "shortlist", "Meets every must-have requirement."

    # One short, and it is a near miss rather than an absence: a human should see
    # this rather than the system quietly closing the door.
    borderline = [r for r in result.must_results if r.status in {"partial", "unclear"}]
    if met >= total - 1 and borderline:
        return "review", (
            f"Meets {met} of {total}. Close on: "
            + "; ".join(r.requirement for r in borderline[:2])
        )
    if met >= total - 1:
        return "review", f"Meets {met} of {total}. Short on: {missing[0]}"

    return "not_a_match", (
        f"Meets {met} of {total}. Missing: " + "; ".join(missing[:3])
    )


def rank(results: list[MatchResult]) -> list[RankedCandidate]:
    """Order the pool: best fit first, non-CVs last."""
    ranked = []
    for result in results:
        tier, reason = _tier(result)
        ranked.append(
            RankedCandidate(match=result, tier=tier, score=_score(result), reason=reason)
        )

    order = {"shortlist": 0, "review": 1, "not_a_match": 2, "not_a_cv": 3}
    ranked.sort(key=lambda r: (order[r.tier], -r.score, r.name.lower()))
    return ranked


def summarize(ranked: list[RankedCandidate]) -> dict:
    counts: dict[str, int] = {}
    for entry in ranked:
        counts[entry.tier] = counts.get(entry.tier, 0) + 1
    return {
        "total": len(ranked),
        "shortlist": counts.get("shortlist", 0),
        "review": counts.get("review", 0),
        "not_a_match": counts.get("not_a_match", 0),
        "not_a_cv": counts.get("not_a_cv", 0),
        "flagged_ai": sum(1 for e in ranked if e.flagged_ai),
    }
