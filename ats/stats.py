"""What a vacancy's applications add up to.

Most of this is counting, and comes straight off the stored rows: how many
applied, where they landed, how many are waiting to be read. That is cheap and
always computed.

One figure is not counting, and is the reason this file exists. `hardest` asks
which of the advert's requirements the fewest applicants actually meet. A
must-have that nobody in two hundred applications satisfies is usually not a
shortage of talent - it is an advert asking for the wrong thing, or asking for a
tool by a name nobody writes on a CV. Nothing else in this system can tell a
recruiter that, and it is the difference between "we got no good candidates" and
"we asked the wrong question".

That one needs every applicant re-matched, so it is bounded and says when it
sampled rather than quietly measuring a fraction and presenting it as the whole.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field

from .job_profile import JobProfile
from .postings import DECISION_LABEL, Application, JobPosting
from .stages import match as match_stage

#: How many applications the requirement analysis reads before it stops.
#: Matching is about fifteen milliseconds each, so this keeps the panel inside a
#: few seconds on a vacancy that attracted thousands.
SAMPLE_LIMIT = 400


@dataclass
class RequirementDemand:
    """How many applicants met one requirement."""

    requirement: str
    kind: str
    importance: str
    met: int
    partial: int
    total: int

    @property
    def percent(self) -> int:
        return int(round(self.met / self.total * 100)) if self.total else 0

    @property
    def is_must(self) -> bool:
        return self.importance == "must_have"


@dataclass
class VacancyStats:
    total: int = 0
    read: int = 0
    pending: int = 0
    unreadable: int = 0
    by_tier: dict[str, int] = field(default_factory=dict)
    by_decision: dict[str, int] = field(default_factory=dict)
    average_percent: int = 0
    median_percent: int = 0
    #: (YYYY-MM-DD, count), oldest first, only days that had applications.
    per_day: list[tuple[str, int]] = field(default_factory=list)
    #: Fewest-met first. The top of this list is what to question in the advert.
    hardest: list[RequirementDemand] = field(default_factory=list)
    #: How many applications the requirement analysis actually read.
    sampled: int = 0
    sample_capped: bool = False


def summarize(
    posting: JobPosting, rows: list[Application], backend=None
) -> VacancyStats:
    """Everything the statistics panel shows, for one vacancy."""
    stats = VacancyStats(total=len(rows))

    scored: list[int] = []
    days: Counter[str] = Counter()
    for row in rows:
        if row.status == "read":
            stats.read += 1
            stats.by_tier[row.tier] = stats.by_tier.get(row.tier, 0) + 1
            scored.append(row.percent)
        elif row.status == "pending":
            stats.pending += 1
        else:
            stats.unreadable += 1

        stats.by_decision[row.decision] = stats.by_decision.get(row.decision, 0) + 1
        if row.applied_at:
            days[row.applied_at[:10]] += 1

    if scored:
        stats.average_percent = int(round(statistics.mean(scored)))
        stats.median_percent = int(round(statistics.median(scored)))

    stats.per_day = sorted(days.items())

    if backend is not None:
        stats.hardest, stats.sampled, stats.sample_capped = _requirement_demand(
            posting.profile, rows, backend
        )
    return stats


def _requirement_demand(
    job: JobProfile, rows: list[Application], backend
) -> tuple[list[RequirementDemand], int, bool]:
    """Re-match the applicants to see which requirements they actually meet.

    Read from the stored profiles rather than the stored percentages, because a
    percentage cannot say WHICH requirement was missed, and that is the whole
    question here.
    """
    readable = [r for r in rows if r.status == "read"]
    capped = len(readable) > SAMPLE_LIMIT
    sample = readable[:SAMPLE_LIMIT]

    met: Counter[str] = Counter()
    partial: Counter[str] = Counter()
    counted = 0

    for row in sample:
        profile = backend.profile(row.id)
        if profile is None:
            continue
        counted += 1
        for result in match_stage.match(profile, job, row.cv_filename).results:
            if result.status == "met":
                met[result.requirement] += 1
            elif result.status in {"partial", "unclear"}:
                partial[result.requirement] += 1

    demand = [
        RequirementDemand(
            requirement=req.text,
            kind=req.kind,
            importance=req.importance,
            met=met.get(req.text, 0),
            partial=partial.get(req.text, 0),
            total=counted,
        )
        for req in job.requirements
    ]
    # Must-haves first: a preferred extra nobody has is a footnote, a mandatory
    # one nobody has is the reason the shortlist is empty.
    demand.sort(key=lambda d: (not d.is_must, d.percent))
    return (demand, counted, capped)


def decision_rows(stats: VacancyStats) -> list[tuple[str, str, int]]:
    """(key, label, count) for every stage, including the empty ones."""
    return [
        (key, label, stats.by_decision.get(key, 0))
        for key, label in DECISION_LABEL.items()
    ]
