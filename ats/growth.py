"""What would close the gap, for somebody the engine turned down.

A percentage is a verdict. On its own it tells a candidate they were not good
enough and nothing else, which is the least useful thing a hiring system can
say to the person it just rejected. Everything needed to say more is already
sitting in the match result: every requirement, whether it was met, what
evidence was found, and exactly what each one is worth.

So this reads the requirements that were NOT met and turns them into a plan
that is specific to one person and one advert.

WHAT MAKES IT HONEST
--------------------
Two rules, and they are what separate this from a horoscope.

1. Nothing is recommended that the candidate did not actually miss. Every step
   traces to a requirement the matcher marked unmet, in the advert the
   recruiter wrote. There is no generic "improve your communication skills".

2. The arithmetic is real. "This would take you from 58% to 79%" is the
   scoring engine run again with those requirements met - the same weights,
   the same formula. It is a promise the system can keep, because it is the
   system's own calculation.

WHAT IT WILL NOT DO
-------------------
Invent a URL. A dead link in an email to somebody who has just been turned
down is worse than no link, so the resources here are searches on platforms
that will still exist, built from the requirement's own words. A search cannot
404, and it cannot quietly become a different course next year.

AND WHO SENDS IT
----------------
Not this module, and not a schedule. `ats/notify.py` has never emailed a
rejection and still does not: a plan that arrives unasked tells somebody they
were rejected, by a machine, which is the exact thing that rule exists to
prevent. A person presses send, per candidate, having read it.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field

from .stages import rank

#: Requirement kinds that a course can close, and kinds it cannot. Time in a
#: role is not purchasable, and pretending otherwise is how a candidate ends up
#: buying a certificate for a problem it does not solve.
_TEACHABLE = {"skill", "certification", "language"}


@dataclass
class Resource:
    """Somewhere to go. Always a real destination, never a guessed one."""

    name: str
    url: str
    #: "course" - taught material. "practice" - somewhere to do the thing.
    kind: str = "course"


@dataclass
class Step:
    """One requirement that was missed, and what would close it."""

    requirement: str
    kind: str
    importance: str
    status: str
    #: What the CV did show, when it showed something. Empty when nothing.
    found: str = ""
    #: Percentage points this would recover. The scoring engine's own number.
    worth: float = 0.0
    advice: str = ""
    resources: list[Resource] = field(default_factory=list)

    @property
    def is_must(self) -> bool:
        return self.importance == "must_have"


@dataclass
class Plan:
    percent_now: int
    #: The percentage if every step below were met, by the same formula.
    percent_after: int
    #: Whether that clears the bar the advert is scored against.
    reaches_bar: bool
    steps: list[Step] = field(default_factory=list)
    #: Set when time in a role is the gap. Courses do not fix this one.
    experience_note: str = ""

    @property
    def gain(self) -> int:
        return max(0, self.percent_after - self.percent_now)

    @property
    def has_anything_to_say(self) -> bool:
        return bool(self.steps or self.experience_note)


# --------------------------------------------------------------------------
# Where to send somebody
# --------------------------------------------------------------------------
def _query(text: str) -> str:
    """A requirement, reduced to something worth searching for.

    Adverts are written in sentences - "Strong SQL including window functions"
    - and a search for the whole sentence finds nothing. The qualifiers go and
    the subject stays.
    """
    # The brackets go, what is inside them stays: in "Cloud platforms (AWS or
    # Azure)" and "... Associate (PL-300)" the searchable part is the part in
    # brackets, and dropping it leaves a query that finds the wrong thing.
    cleaned = text.replace("(", " ").replace(")", " ")
    cleaned = re.sub(
        r"\b(strong|solid|excellent|good|working|proven|hands[- ]on|deep|"
        r"experience (with|in|of)|knowledge of|familiarity with|understanding of|"
        r"ability to|proficiency (in|with)|advanced|basic|and|or|the|a|an)\b",
        " ",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"[^\w+#. ]", " ", cleaned)
    return " ".join(cleaned.split())[:60].strip()


#: Platforms rather than courses.
#:
#: A named course is a URL that rots: it gets retired, renamed, or moved behind
#: a paywall, and the person reading the email is the one who finds out. A
#: search on a platform that will still be there lands on whatever that platform
#: currently teaches, which is what was meant anyway.
_PLATFORMS = [
    ("Coursera", "https://www.coursera.org/search?query={q}", "course"),
    ("edX", "https://www.edx.org/search?q={q}", "course"),
    (
        "Microsoft Learn",
        "https://learn.microsoft.com/en-us/training/browse/?terms={q}",
        "course",
    ),
    ("YouTube", "https://www.youtube.com/results?search_query={q}+full+course", "course"),
]

#: Free and well known, for the kinds of skill they actually cover. Root pages,
#: not deep links into a syllabus.
_HOMES = {
    "freeCodeCamp": (
        "https://www.freecodecamp.org/learn",
        ("javascript", "python", "react", "html", "css", "sql", "node",
         "front end", "back end", "web", "typescript", "data analysis"),
    ),
    "Kaggle Learn": (
        "https://www.kaggle.com/learn",
        ("python", "pandas", "machine learning", "data", "sql", "deep learning",
         "visualization", "statistics"),
    ),
}


def resources_for(requirement: str, kind: str) -> list[Resource]:
    """Two or three places to learn one thing. Never a fabricated URL."""
    query = _query(requirement)
    if not query:
        return []

    encoded = urllib.parse.quote_plus(query)
    found: list[Resource] = []

    lowered = requirement.lower()
    for name, (url, topics) in _HOMES.items():
        if any(topic in lowered for topic in topics):
            found.append(Resource(name=f"{name} - free", url=url, kind="course"))
            break

    # Microsoft Learn is the right first stop for its own products and noise for
    # anything else, so it is only offered when the requirement names one.
    microsoft = any(
        word in lowered
        for word in ("power bi", "azure", "excel", "microsoft", "dax", "power query",
                     ".net", "c#", "sharepoint", "dynamics", "sql server")
    )

    # For a Microsoft product it is the best answer, not the third-best - and
    # with only three slots, third-best means left out.
    platforms = sorted(
        _PLATFORMS, key=lambda p: (p[0] != "Microsoft Learn") if microsoft else 0
    )
    for name, template, resource_kind in platforms:
        if name == "Microsoft Learn" and not microsoft:
            continue
        found.append(
            Resource(name=name, url=template.format(q=encoded), kind=resource_kind)
        )
        if len(found) >= 3:
            break

    if kind == "certification":
        found.insert(
            0,
            Resource(
                name="The certification itself",
                url=f"https://www.google.com/search?q={encoded}+certification+exam",
                kind="course",
            ),
        )
    return found[:3]


#: Somewhere to do the thing, for the gaps a course cannot close.
_PRACTICE = [
    Resource(
        name="Build and publish it on GitHub",
        url="https://github.com/new",
        kind="practice",
    ),
    Resource(
        name="Kaggle - datasets and competitions to work on",
        url="https://www.kaggle.com/competitions",
        kind="practice",
    ),
    Resource(
        name="Open source issues for newcomers",
        url="https://goodfirstissue.dev/",
        kind="practice",
    ),
]


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------
def _advice_for(result) -> str:
    """What to do about one missed requirement, in a sentence."""
    name = result.requirement

    if result.kind == "certification":
        return f"Sit {name}. A certification is the one requirement a document can settle outright."
    if result.kind == "language":
        return f"{name} is a stated requirement, so it belongs on the CV with a level beside it."
    if result.kind == "education":
        return (
            f"{name} is not something to fix quickly. It is here because it is "
            f"what the advert asked for, and it is worth knowing which roles ask "
            f"for it and which do not."
        )
    if result.kind == "experience":
        return (
            "Time in a role is the one thing on this list that cannot be "
            "studied for. What shortens it is work that can be seen."
        )

    if result.status == "partial":
        return (
            f"{name} is on the CV but only as a claim - it is not shown being "
            f"used. A project or a job bullet where it did something is worth "
            f"more than the word on its own."
        )

    weight = (
        "It is a must-have on this advert."
        if result.importance == "must_have"
        else "It is a nice-to-have here, so it is worth less than the ones above it."
    )
    return f"{name} does not appear anywhere in the CV. {weight}"


def _experience_note(review) -> str:
    """Said once, about time rather than about a requirement.

    Separate from the steps because the answer is a different kind of thing: no
    course closes it, and the honest advice is about what to go and do.
    """
    if not review or getattr(review, "relevant_years", None) is None:
        return ""
    return (
        "The gap here is time in the work, not knowledge of it. Two things "
        "shorten it and neither is a course: build something real and publish "
        "it where it can be read - code, a dashboard, a report, an analysis of "
        "public data - and take the junior or freelance work that gets the "
        "first year on the CV. A project somebody can open counts for more here "
        "than a certificate, because what a skill was used FOR carries more "
        "weight than the word on its own."
    )


def build(result, percent: int, bar: int = None) -> Plan:
    """Turn a match result into something the candidate can act on.

    `result` is the MatchResult the score came from, so every step below is a
    requirement that was really written in this advert and really missed in
    this CV.
    """
    if bar is None:
        bar = rank.WAITING_LIST_AT

    _earned, possible = _weighted_total(result.results)
    steps: list[Step] = []

    for one in result.results:
        if one.counts_as_met and one.strength in {"strong", "valid"}:
            continue

        # What closing it would recover: the weight it has not earned, as a
        # share of everything on offer. The scoring engine's own arithmetic.
        weight = rank.weight_of(one)
        worth = (weight * (1 - one.credit) / possible * 100) if possible else 0.0
        if worth <= 0:
            continue

        steps.append(
            Step(
                requirement=one.requirement,
                kind=one.kind,
                importance=one.importance,
                status=one.status,
                found=one.evidence,
                worth=round(worth, 1),
                advice=_advice_for(one),
                resources=(
                    resources_for(one.requirement, one.kind)
                    if one.kind in _TEACHABLE
                    else list(_PRACTICE[:2]) if one.kind == "experience"
                    else []
                ),
            )
        )

    # Must-haves first - they are what a recruiter filters on - and within
    # those, the ones that move the number most.
    steps.sort(key=lambda s: (not s.is_must, -s.worth))

    after = percent + sum(s.worth for s in steps)
    note = ""
    if any(s.kind == "experience" for s in steps):
        note = _experience_note(getattr(result, "experience", None))

    return Plan(
        percent_now=percent,
        percent_after=int(round(min(100.0, after))),
        reaches_bar=int(round(min(100.0, after))) >= bar,
        steps=steps,
        experience_note=note,
    )


def _weighted_total(results) -> tuple[float, float]:
    earned = possible = 0.0
    for one in results:
        weight = rank.weight_of(one)
        possible += weight
        earned += weight * one.credit
    return earned, possible
