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

# Fixed weights. Must-haves dominate; nice-to-haves only separate people who
# already clear the bar, which is what "preferred" means.
_MUST_WEIGHT = 100.0
_PARTIAL_CREDIT = 0.5      # a near miss is worth something, not nothing
_NICE_WEIGHT = 10.0


@dataclass
class RankedCandidate:
    match: MatchResult
    tier: Tier
    score: float
    reason: str

    @property
    def percent(self) -> int:
        """How much of what the job asked for this candidate meets, 0-100.

        A plain weighted ratio of requirements, not an opinion: must-haves carry
        most of it, nice-to-haves the rest, and a partial or unclear result counts
        half. Every point is traceable to a named requirement, which is the only
        kind of percentage worth showing next to a person's name.
        """
        return int(round(self.score / (_MUST_WEIGHT + _NICE_WEIGHT) * 100))

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
    """Weighted requirements met. Drives the ordering and the percentage."""
    must_total = result.must_total or 1
    credit = sum(
        1.0 if r.status == "met" else _PARTIAL_CREDIT if r.status in {"partial", "unclear"} else 0.0
        for r in result.must_results
    )
    must = (credit / must_total) * _MUST_WEIGHT
    # With no nice-to-haves listed, meeting every must-have is 100% - otherwise a
    # candidate who met everything the advert asked for would be shown as 91%.
    if result.nice_total:
        nice = result.nice_met / result.nice_total * _NICE_WEIGHT
    else:
        nice = must / _MUST_WEIGHT * _NICE_WEIGHT
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
