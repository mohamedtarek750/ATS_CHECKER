"""Alerts: where the workforce forecast and the live ATS disagree with each other.

Each side is useless alone. The forecast says Information Technology will be
five roles short and has said so since it was exported; the ATS knows which
vacancies are open and who has cleared the bar on them. Neither notices that a
shortfall has no vacancy against it, because neither can see the other. That is
what this produces.

WHY THIS IS PYTHON AND NOT TYPESCRIPT ANY MORE
----------------------------------------------
It was TypeScript, computed in the browser, which was fine while alerts only
ever appeared on a page somebody was looking at. Emailing them needs the same
findings with nobody looking, and a second implementation of the same rules in
a second language is a guarantee that the email and the dashboard will one day
disagree. There is one engine. The pages read it over the API.

THREE KINDS OF NUMBER, AND THE RULE ABOUT SAYING WHICH
------------------------------------------------------
Every alert carries a source: "forecast" is the frozen model, "live" is the ATS
as of this request, "payroll" is pay data. A finding that reads more than one
is labelled with the weakest, because a reader who trusts a stale number as
though it were current is worse off than one who distrusts a fresh one.

WHEN TO SAY NOTHING
-------------------
A vacancy whose title matches no forecast row produces nothing rather than a
guess. A fully staffed role produces nothing rather than congratulation. A
department short by one produces nothing. An alerts feed that always has
something in it is one people learn to scroll past, and then the one that
mattered scrolls past with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from .postings import UNASSIGNED_SLUG
from .workforce import ROLES, Role

#: Loudest first. The order alerts are sorted in and emails are led with.
LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}

#: A shortfall smaller than this in a role nobody is hiring for is not worth
#: interrupting anybody about.
UNOPENED_FLOOR = 2

#: Unread applications below this are a normal morning, not a backlog.
BACKLOG = 5
LOUD_BACKLOG = 20

_SENIORITY = re.compile(
    r"\b(senior|junior|lead|principal|staff|mid|midlevel|level|i|ii|iii|sr|jr)\b"
)
_BRACKETS = re.compile(r"\(.*?\)")
_NOT_WORD = re.compile(r"[^a-z0-9 ]")


@dataclass
class Alert:
    id: str
    level: str
    title: str
    detail: str
    source: str
    department: str = ""
    job_slug: str = ""
    action_label: str = ""
    action_href: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def normalise(title: str) -> str:
    """A job title reduced to something comparable.

    A vacancy is called "Senior Data Analyst (Reporting)" and the forecast row
    is called "Data Analyst". Neither spelling is wrong, and a rule that fired
    only on an exact match would never fire at all.
    """
    text = _BRACKETS.sub(" ", title.lower())
    text = _NOT_WORD.sub(" ", text)
    text = _SENIORITY.sub(" ", text)
    return " ".join(text.split())


def match_role(title: str, roles: list[Role] | None = None) -> Role | None:
    """The forecast row a vacancy is hiring for, or None if none fits."""
    roles = ROLES if roles is None else roles
    wanted = normalise(title)
    if not wanted:
        return None

    for role in roles:
        if normalise(role.role) == wanted:
            return role

    # Containment either way, longest first: "Data Analyst" should lose to
    # "Digital Marketing Analyst" when the vacancy says the latter.
    near = [
        role
        for role in roles
        if normalise(role.role) in wanted or wanted in normalise(role.role)
    ]
    near.sort(key=lambda r: len(normalise(r.role)), reverse=True)
    return near[0] if near else None


def level_for(gap: int, current: int) -> str:
    """How loudly a shortfall is said, relative to the size of the team.

    Two missing from a team of four is an emergency. Two from a hundred is a
    rounding error. The absolute number cannot tell them apart.
    """
    share = (gap / current) if current > 0 else 1.0
    if share >= 0.2:
        return "critical"
    if share >= 0.12:
        return "warning"
    return "info"


_IRREGULAR = {"person": "people"}


def plural(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    return f"{n} {_IRREGULAR.get(word, word + 's')}"


@dataclass
class VacancyState:
    """What a vacancy looks like to this module."""

    slug: str
    title: str
    status: str
    applications: int = 0
    accepted: int = 0
    unread: int = 0


def vacancy_states(backend) -> list[VacancyState]:
    """Read the live side out of storage.

    The holding pen is excluded: it is not a vacancy anybody opened, it matches
    no forecast role, and counting its unread CVs as a backlog against a job
    would be counting them against a job that does not exist.
    """
    states = []
    for posting in backend.postings():
        if posting.slug == UNASSIGNED_SLUG:
            continue
        rows = backend.applications(posting.slug)
        states.append(
            VacancyState(
                slug=posting.slug,
                title=posting.title,
                status=posting.status,
                applications=len(rows),
                accepted=sum(1 for r in rows if r.tier == "accepted"),
                unread=sum(1 for r in rows if not r.is_read),
            )
        )
    return states


def build(
    vacancies: list[VacancyState],
    roles: list[Role] | None = None,
) -> list[Alert]:
    """Every finding worth somebody's attention, most serious first."""
    roles = ROLES if roles is None else roles
    found: list[Alert] = []
    open_jobs = [v for v in vacancies if v.status == "open"]
    claimed: set[str] = set()

    for job in open_jobs:
        role = match_role(job.title, roles)
        if role is None:
            continue
        claimed.add(role.role)

        short = role.gap - job.accepted

        if role.gap > 0 and short > 0:
            if job.accepted > 0:
                standing = (
                    f"{job.accepted} of the {role.gap} could be filled from this "
                    f"vacancy's shortlist; {plural(short, 'place')} would still "
                    f"be open."
                )
            elif job.applications > 0:
                standing = (
                    f"Nobody on this vacancy has cleared the bar yet, out of "
                    f"{plural(job.applications, 'applicant')}."
                )
            else:
                standing = "Nobody has applied to this vacancy yet."

            found.append(
                Alert(
                    id=f"gap:{job.slug}",
                    level=level_for(short, role.current),
                    department=role.department,
                    job_slug=job.slug,
                    title=(
                        f"{role.department} needs "
                        f"{plural(role.gap, role.role.lower())} it does not have"
                    ),
                    detail=(
                        f"The forecast puts demand at {role.demand} against "
                        f"{role.current} in post. {standing}"
                    ),
                    source="forecast",
                    action_label="Open the job",
                    action_href=f"/admin/jobs/{job.slug}",
                )
            )

        if role.gap > 0 and short <= 0:
            found.append(
                Alert(
                    id=f"filled:{job.slug}",
                    level="info",
                    department=role.department,
                    job_slug=job.slug,
                    title=f"{job.title} has enough people to close its shortfall",
                    detail=(
                        f"{plural(job.accepted, 'candidate')} accepted against a "
                        f"forecast gap of {role.gap}. Closing the vacancy would "
                        f"stop new applications arriving for a place that is "
                        f"spoken for."
                    ),
                    source="forecast",
                    action_label="Open the job",
                    action_href=f"/admin/jobs/{job.slug}",
                )
            )

        if role.turnover_risk == "high":
            found.append(
                Alert(
                    id=f"turnover:{job.slug}",
                    level="warning",
                    department=role.department,
                    job_slug=job.slug,
                    title=(
                        f"{role.role} loses {role.turnover}% of its people a year"
                    ),
                    detail=(
                        f"{plural(role.people_lost, 'person')} left in the last "
                        f"year against {role.current} in post. Hiring to the "
                        f"forecast gap alone leaves the team where it started."
                    ),
                    source="forecast",
                    action_label="See turnover",
                    action_href="/workforce/turnover",
                )
            )

    # The finding neither system can reach on its own: a shortfall with no
    # vacancy against it. Nobody is looking, and nothing says so.
    #
    # Grouped by department. The forecast is short in most roles most of the
    # time, so a row each turns the feed into a copy of the forecast - which is
    # the same as no feed at all.
    unopened: dict[str, list[Role]] = {}
    for role in roles:
        if role.gap < UNOPENED_FLOOR or role.role in claimed:
            continue
        unopened.setdefault(role.department, []).append(role)

    for department, short_roles in unopened.items():
        short_roles.sort(key=lambda r: -r.gap)
        people = sum(r.gap for r in short_roles)
        worst = min(
            (level_for(r.gap, r.current) for r in short_roles),
            key=lambda lvl: LEVEL_ORDER[lvl],
        )

        if len(short_roles) == 1:
            title = f"No vacancy is open for {short_roles[0].role}"
            detail = (
                f"{department} is forecast {plural(people, 'person')} short in "
                f"this role and nothing is advertised, so no applications are "
                f"arriving for it."
            )
        else:
            listed = ", ".join(f"{r.role} ({r.gap} short)" for r in short_roles)
            title = (
                f"{department} has {plural(len(short_roles), 'role')} short "
                f"with no vacancy open"
            )
            detail = (
                f"{listed}. {plural(people, 'person')} in total, and nothing is "
                f"advertised - so no applications are arriving for any of them."
            )

        found.append(
            Alert(
                id=f"unopened:{department}",
                level=worst,
                department=department,
                title=title,
                detail=detail,
                source="forecast",
                action_label="Add a job",
                action_href="/admin",
            )
        )

    # Live, and about the recruiter rather than the forecast.
    for job in open_jobs:
        if job.unread < BACKLOG:
            continue
        found.append(
            Alert(
                id=f"unread:{job.slug}",
                level="warning" if job.unread >= LOUD_BACKLOG else "info",
                job_slug=job.slug,
                title=(
                    f"{plural(job.unread, 'application')} on {job.title} have "
                    f"not been read"
                ),
                detail=(
                    "They are stored and will be read on the next sweep. Until "
                    "then they are not counted in the split on the dashboard."
                ),
                source="live",
                action_label="Open the job",
                action_href=f"/admin/jobs/{job.slug}",
            )
        )

    # Severity first, then anything about a vacancy that is actually open ahead
    # of anything about one that is not - those are the ones somebody can act
    # on today.
    found.sort(key=lambda a: (LEVEL_ORDER[a.level], 0 if a.job_slug else 1, a.title))
    return found
