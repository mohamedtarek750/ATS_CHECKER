"""Stage 5 - order the pool and cut it into tiers. No model call, no configuration.

The weights below are fixed in code deliberately. They are not a dial for a
recruiter to turn: nudging a weight silently reorders real people, and nobody
reviews who moved down. What HR sees is a tier and the requirements behind it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .match import MatchResult

Tier = Literal["accepted", "waiting_list", "rejected", "not_a_cv"]

TIER_LABEL = {
    "accepted": "Accepted",
    "waiting_list": "Waiting list",
    "rejected": "Rejected",
    "not_a_cv": "Not a CV",
    # Never produced by ranking. Set by intake for a CV that arrived with no
    # vacancy behind it, so that "no verdict yet" cannot be read as a verdict.
    "unscored": "Not scored yet",
}

TIER_FOLDER = {
    "accepted": "1_accepted",
    "waiting_list": "2_waiting_list",
    "rejected": "3_rejected",
    "not_a_cv": "0_not_a_cv",
}

# The cut-offs, in percent, fixed in code rather than exposed as a slider. A
# recruiter nudging a threshold silently moves real people across the line
# between an interview and a rejection, and nobody reviews who moved.
ACCEPTED_AT = 80
WAITING_LIST_AT = 70

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
        a person's name - and it is the number the tier is cut from, so what the
        recruiter reads is what decided the outcome.
        """
        return percent_of(self.match)

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


def percent_of(result: MatchResult) -> int:
    """The headline match percentage. The tier is cut straight off this."""
    earned, possible = _weighted(result.results)
    return int(round(earned / possible * 100)) if possible else 0


def _tier(result: MatchResult, percent: int) -> tuple[Tier, str]:
    """Which band this candidate falls in, and the sentence explaining it.

    The band is the percentage and nothing else, so that the number shown next
    to somebody's name is the number that decided their outcome. Where the
    must-haves stand is always said in the reason, because a percentage alone
    cannot tell a recruiter that an otherwise strong candidate is missing
    something the advert called essential.
    """
    if not result.candidate.is_cv:
        kind = result.candidate.document_type.replace("_", " ")
        return "not_a_cv", f"This is a {kind}, not a CV."

    met, total = result.must_met, result.must_total
    missing = result.missing_labels
    borderline = [r for r in result.must_results if r.status in {"partial", "unclear"}]

    if total == 0:
        standing = "The vacancy lists no must-have requirements"
    elif met == total:
        standing = f"Meets all {total} must-have requirements"
    else:
        standing = f"Meets {met} of {total} must-haves"

    if percent >= ACCEPTED_AT:
        # Above the bar on the total, but short of something called essential.
        # Saying so is the difference between a recruiter trusting this list and
        # discovering the gap in the interview.
        if missing:
            return "accepted", (
                f"{percent}% overall, above the {ACCEPTED_AT}% bar. {standing} - "
                f"check {missing[0]} before inviting them."
            )
        return "accepted", f"{percent}% overall. {standing}."

    if percent >= WAITING_LIST_AT:
        if borderline:
            return "waiting_list", (
                f"{percent}%, just under the {ACCEPTED_AT}% bar. {standing}, and "
                f"close on: " + "; ".join(r.requirement for r in borderline[:2])
            )
        if missing:
            return "waiting_list", (
                f"{percent}%, just under the {ACCEPTED_AT}% bar. {standing}. "
                f"Short on: " + "; ".join(missing[:2])
            )
        return "waiting_list", (
            f"{percent}%, just under the {ACCEPTED_AT}% bar. {standing}."
        )

    # The one floor under the percentage. Meeting everything the employer called
    # essential cannot be a rejection: an advert with six "preferred" extras drags
    # a fully qualified candidate to 48% on arithmetic alone, and rejecting them
    # would be this system telling an employer that the person who meets their
    # every stated requirement is not worth a look. A human decides that one.
    if total and met == total:
        return "waiting_list", (
            f"{percent}% overall, which is below the {WAITING_LIST_AT}% bar, but "
            f"{standing.lower()} - the percentage is held down by preferred extras "
            f"rather than by anything the advert called essential."
        )

    if missing:
        return "rejected", (
            f"{percent}%, below the {WAITING_LIST_AT}% bar. {standing}. "
            f"Missing: " + "; ".join(missing[:3])
        )
    return "rejected", (
        f"{percent}%, below the {WAITING_LIST_AT}% bar. {standing}, but too little "
        f"of what the advert asked for is evidenced."
    )


def rank(results: list[MatchResult]) -> list[RankedCandidate]:
    """Order the pool: best fit first, non-CVs last."""
    ranked = []
    for result in results:
        tier, reason = _tier(result, percent_of(result))
        ranked.append(
            RankedCandidate(match=result, tier=tier, score=_score(result), reason=reason)
        )

    order = {"accepted": 0, "waiting_list": 1, "rejected": 2, "not_a_cv": 3}
    ranked.sort(key=lambda r: (order[r.tier], -r.score, r.name.lower()))
    return ranked


def summarize(ranked: list[RankedCandidate]) -> dict:
    counts: dict[str, int] = {}
    for entry in ranked:
        counts[entry.tier] = counts.get(entry.tier, 0) + 1
    return {
        "total": len(ranked),
        "accepted": counts.get("accepted", 0),
        "waiting_list": counts.get("waiting_list", 0),
        "rejected": counts.get("rejected", 0),
        "not_a_cv": counts.get("not_a_cv", 0),
        "flagged_ai": sum(1 for e in ranked if e.flagged_ai),
    }
