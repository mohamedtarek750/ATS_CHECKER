"""The workforce forecast, as the alert engine sees it.

GENERATED. Do not edit by hand - lib/workforce.ts is where these rows are
authored, and scripts/sync_workforce_data.py copies them here. A test
parses both files and fails if they have drifted apart.

Why a copy rather than one shared JSON file: the Python function is
bundled for deployment on its own, and a data file outside it is a file
that works on a laptop and is missing in production.

Like everything derived from it, these numbers are a FROZEN FORECAST -
produced once by a Lasso regression trained on quarterly staffing records
for 2020-2026, and unchanged since. Nothing in the running system updates
them and no applicant affects them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Role:
    """One role's headcount today and what the model says it needs."""

    department: str
    role: str
    current: int
    demand: int
    gap: int
    #: Measured annual turnover as a percentage. 0.0 where none was recorded,
    #: which is not the same as a role nobody leaves - it is a role nobody
    #: measured, and inventing a rate for it would put a made-up number into
    #: every total downstream.
    turnover: float = 0.0
    #: high / medium / low, or "" where turnover was never measured.
    turnover_risk: str = ""
    people_lost: int = 0
    level: str = "Mid"


ROLES: list[Role] = [
    Role(department="Engineering", role="Civil Engineer", current=34, demand=37, gap=3, turnover=8.8, turnover_risk="medium", people_lost=3, level="Mid"),
    Role(department="Engineering", role="Project Engineer", current=30, demand=33, gap=3, turnover=6.7, turnover_risk="low", people_lost=2, level="Junior"),
    Role(department="Finance", role="Auditor", current=17, demand=20, gap=3, turnover=17.6, turnover_risk="high", people_lost=3, level="Expert"),
    Role(department="Finance", role="Financial Analyst", current=13, demand=16, gap=3, turnover=7.7, turnover_risk="low", people_lost=1, level="Mid"),
    Role(department="Operations", role="Maintenance Technician", current=22, demand=25, gap=3, turnover=9.1, turnover_risk="medium", people_lost=2, level="Mid"),
    Role(department="Engineering", role="Quality Engineer", current=19, demand=21, gap=2, turnover=5.3, turnover_risk="low", people_lost=1, level="Junior"),
    Role(department="Engineering", role="Mechanical Engineer", current=20, demand=22, gap=2, turnover=5.0, turnover_risk="low", people_lost=1, level="Mid"),
    Role(department="Finance", role="Accountant", current=11, demand=13, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Expert"),
    Role(department="Engineering", role="Electrical Engineer", current=22, demand=24, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Junior"),
    Role(department="Human Resources", role="Compensation Analyst", current=11, demand=13, gap=2, turnover=9.1, turnover_risk="medium", people_lost=1, level="Senior"),
    Role(department="Human Resources", role="Talent Acquisition", current=3, demand=5, gap=2, turnover=33.3, turnover_risk="high", people_lost=1, level="Senior"),
    Role(department="Human Resources", role="Training Coordinator", current=8, demand=10, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Senior"),
    Role(department="Information Technology", role="Cybersecurity Specialist", current=16, demand=18, gap=2, turnover=6.2, turnover_risk="low", people_lost=1, level="Mid"),
    Role(department="Information Technology", role="Data Scientist", current=7, demand=9, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Mid"),
    Role(department="Information Technology", role="Data Analyst", current=12, demand=14, gap=2, turnover=8.3, turnover_risk="medium", people_lost=1, level="Junior"),
    Role(department="Information Technology", role="Devops Engineer", current=11, demand=13, gap=2, turnover=9.1, turnover_risk="medium", people_lost=1, level="Junior"),
    Role(department="Finance", role="Budget Analyst", current=13, demand=15, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Junior"),
    Role(department="Project Management", role="PMO Analyst", current=12, demand=14, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Mid"),
    Role(department="Information Technology", role="IT Support", current=9, demand=11, gap=2, turnover=11.1, turnover_risk="medium", people_lost=1, level="Senior"),
    Role(department="Legal", role="Compliance Officer", current=9, demand=11, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Mid"),
    Role(department="Information Technology", role="Software Engineer", current=22, demand=24, gap=2, turnover=4.5, turnover_risk="low", people_lost=1, level="Expert"),
    Role(department="Legal", role="Legal Counsel", current=4, demand=6, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Mid"),
    Role(department="Sales & Marketing", role="Content Creator", current=17, demand=19, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Mid"),
    Role(department="Operations", role="Facility Manager", current=21, demand=23, gap=2, turnover=9.5, turnover_risk="medium", people_lost=2, level="Mid"),
    Role(department="Legal", role="Contract Specialist", current=5, demand=7, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Mid"),
    Role(department="Project Management", role="Project Manager", current=22, demand=24, gap=2, turnover=9.1, turnover_risk="medium", people_lost=2, level="Expert"),
    Role(department="Project Management", role="Project Coordinator", current=17, demand=19, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Junior"),
    Role(department="Operations", role="Logistics Coordinator", current=23, demand=25, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Senior"),
    Role(department="Operations", role="Operations Manager", current=15, demand=17, gap=2, turnover=6.7, turnover_risk="low", people_lost=1, level="Senior"),
    Role(department="Project Management", role="Scrum Master", current=14, demand=16, gap=2, turnover=0.0, turnover_risk="low", people_lost=0, level="Senior"),
    Role(department="Human Resources", role="Hr Specialist", current=7, demand=8, gap=1, turnover=0.0, turnover_risk="low", people_lost=0, level="Junior"),
    Role(department="Sales & Marketing", role="Marketing Specialist", current=6, demand=7, gap=1, turnover=16.7, turnover_risk="high", people_lost=1, level="Junior"),
    Role(department="Sales & Marketing", role="Digital Marketing Analyst", current=10, demand=11, gap=1, turnover=10.0, turnover_risk="medium", people_lost=1, level="Mid"),
]


def by_role(name: str) -> Role | None:
    """Exact lookup. Fuzzy matching against a job advert lives in alerts.py."""
    return next((r for r in ROLES if r.role == name), None)
