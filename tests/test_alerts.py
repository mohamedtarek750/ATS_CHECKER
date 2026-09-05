"""The alert engine, the digest that carries it, and the data behind both.

What is being tested is judgement, not arithmetic. An alerts feed earns its
place by being right about when to stay QUIET - one that always has something
in it is one people learn to scroll past, and then the one that mattered
scrolls past with it. So most of these check that nothing is said.

The rest are about the two ways this can lie to somebody who is not looking at
it: a digest that silently goes nowhere, and a number that came from the frozen
forecast being read as though it were current.

Run: python tests/test_alerts.py
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import alerts, notify  # noqa: E402
from ats.alerts import Alert, VacancyState, build, level_for, match_role  # noqa: E402
from ats.workforce import ROLES, Role  # noqa: E402


@contextlib.contextmanager
def environment(**values):
    saved = {k: os.environ.get(k) for k in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


MAIL_ON = dict(
    RESEND_API_KEY="re_test",
    ATS_MAIL_FROM="ACUD Careers <careers@example.com>",
    ATS_ALERT_EMAILS="one@example.com,two@example.com",
)


@contextlib.contextmanager
def fake_provider(status=200, raises=None):
    """Stand in for Resend, and keep what would have been sent."""
    sent: list[dict] = []
    original = urllib.request.urlopen

    class Response:
        def __init__(self, code):
            self.status = code

        def read(self):
            return b'{"id":"test"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(request, timeout=None):
        if raises:
            raise raises
        sent.append(json.loads(request.data.decode("utf-8")))
        return Response(status)

    urllib.request.urlopen = fake
    try:
        yield sent
    finally:
        urllib.request.urlopen = original


# -- fixtures ---------------------------------------------------------------
def role(**over) -> Role:
    base = dict(
        department="Information Technology",
        role="Data Analyst",
        current=12,
        demand=14,
        gap=2,
        turnover=0.0,
        turnover_risk="",
        people_lost=0,
        level="Junior",
    )
    base.update(over)
    return Role(**base)


def job(**over) -> VacancyState:
    base = dict(
        slug="data-analyst",
        title="Data Analyst",
        status="open",
        applications=0,
        accepted=0,
        unread=0,
    )
    base.update(over)
    return VacancyState(**base)


# -- matching ---------------------------------------------------------------
def test_a_vacancy_titled_the_way_people_title_vacancies_still_matches():
    roles = [role(), role(role="Software Engineer")]
    for title in (
        "Data Analyst",
        "Senior Data Analyst",
        "data analyst",
        "Data Analyst (Reporting)",
        "Lead Data Analyst II",
    ):
        found = match_role(title, roles)
        assert found is not None and found.role == "Data Analyst", title


def test_a_longer_role_wins_the_overlap_it_actually_belongs_to():
    roles = [role(role="Data Analyst"), role(role="Digital Marketing Analyst")]
    assert match_role("Digital Marketing Analyst", roles).role == (
        "Digital Marketing Analyst"
    )


def test_a_vacancy_the_forecast_knows_nothing_about_matches_nothing():
    """Guessing would attach real headcount numbers to the wrong role."""
    assert match_role("Falconry Instructor", [role()]) is None
    assert match_role("", [role()]) is None


def test_how_loud_the_alert_is_scales_with_the_size_of_the_team():
    """Two missing from four is an emergency. Two from a hundred is not."""
    assert level_for(3, 10) == "critical"
    assert level_for(3, 20) == "warning"
    assert level_for(3, 100) == "info"


# -- staying quiet ----------------------------------------------------------
def test_a_fully_staffed_role_with_a_job_open_says_nothing():
    assert build([job()], [role(demand=12, gap=0)]) == []


def test_a_closed_vacancy_is_not_chased():
    found = build([job(status="closed")], [role()])
    # The role is short and now unclaimed, so "nothing is open" is the right
    # finding - but nothing is said about the closed vacancy itself.
    assert len(found) == 1
    assert "No vacancy is open" in found[0].title


def test_a_shortfall_of_one_is_not_worth_interrupting_anybody_for():
    assert build([], [role(gap=1)]) == []


def test_a_vacancy_matching_no_role_produces_no_guess():
    found = build([job(slug="falconry", title="Falconry Instructor")], [role()])
    assert all(a.job_slug != "falconry" for a in found)


# -- the findings themselves ------------------------------------------------
def test_a_role_that_is_short_with_a_vacancy_open_is_reported_against_it():
    found = build([job(applications=4)], [role()])
    gap = next(a for a in found if a.id.startswith("gap:"))

    assert gap.job_slug == "data-analyst"
    assert gap.department == "Information Technology"
    assert "needs 2 data analysts" in gap.title
    assert "demand at 14 against 12" in gap.detail
    assert "Nobody on this vacancy has cleared the bar" in gap.detail


def test_the_shortfall_counts_who_has_already_been_accepted():
    found = build([job(applications=9, accepted=1)], [role()])
    gap = next(a for a in found if a.id.startswith("gap:"))
    assert "1 of the 2 could be filled" in gap.detail
    assert "1 place would still be open" in gap.detail


def test_enough_accepted_turns_the_alert_into_a_suggestion_to_close_the_job():
    found = build([job(applications=20, accepted=2)], [role()])
    assert not [a for a in found if a.id.startswith("gap:")]
    filled = next(a for a in found if a.id.startswith("filled:"))
    assert filled.level == "info"
    assert "2 candidates accepted against a forecast gap of 2" in filled.detail


def test_a_shortfall_with_no_vacancy_against_it_is_the_loudest_thing_here():
    """Neither system can see this alone.

    The forecast does not know what is advertised; the ATS does not know what
    is missing.
    """
    found = build([], [role(gap=3)])
    assert len(found) == 1
    assert found[0].id == "unopened:Information Technology"
    assert "No vacancy is open for Data Analyst" in found[0].title
    assert "forecast 3 people short in this role" in found[0].detail
    assert found[0].action_label == "Add a job"


def test_a_department_short_in_several_roles_is_one_alert_not_one_per_role():
    """The forecast is short somewhere in most roles most of the time.

    A row each reproduces the forecast inside the alerts feed, which is the
    same as having no alerts feed.
    """
    found = build(
        [],
        [
            role(role="Compliance Officer", department="Legal", current=9),
            role(role="Contract Specialist", department="Legal", current=5),
            role(role="Legal Counsel", department="Legal", current=4),
        ],
    )

    assert len(found) == 1
    assert found[0].id == "unopened:Legal"
    assert "Legal has 3 roles short with no vacancy open" in found[0].title
    for named in ("Compliance Officer", "Contract Specialist", "Legal Counsel"):
        assert f"{named} (2 short)" in found[0].detail
    assert "6 people in total" in found[0].detail
    # Loudest of the three wins: 2 of 4 is critical even though 2 of 9 is not.
    assert found[0].level == "critical"


def test_opening_the_vacancy_silences_the_no_vacancy_alert():
    assert not [a for a in build([job()], [role()]) if a.id.startswith("unopened:")]


def test_a_role_that_bleeds_people_says_so_separately_from_the_shortfall():
    churning = role(turnover=20.0, turnover_risk="high", people_lost=2)
    leaving = next(
        a for a in build([job()], [churning]) if a.id.startswith("turnover:")
    )
    assert "loses 20.0% of its people a year" in leaving.title
    assert "leaves the team where it started" in leaving.detail

    settled = role(turnover=3.0, turnover_risk="low", people_lost=1)
    assert not [
        a for a in build([job()], [settled]) if a.id.startswith("turnover:")
    ]


def test_unread_applications_are_reported_only_once_they_are_a_backlog():
    assert build([job(unread=4)], []) == []

    piling = build([job(unread=30, applications=30)], [])
    assert len(piling) == 1
    assert piling[0].level == "warning"
    assert piling[0].source == "live"
    assert "30 applications on Data Analyst" in piling[0].title


# -- the rule about which numbers are which ---------------------------------
def test_anything_resting_on_the_forecast_is_labelled_as_resting_on_it():
    found = build(
        [job(unread=30, applications=30)],
        [role(turnover=20.0, turnover_risk="high", people_lost=2)],
    )
    for alert in found:
        assert alert.source in {"forecast", "live", "payroll"}, alert.id

    # The shortfall reads the live accepted count too and is still marked
    # "forecast" - the weaker claim has to win, or a stale number gets read as
    # a current one.
    assert next(a for a in found if a.id.startswith("gap:")).source == "forecast"
    assert next(a for a in found if a.id.startswith("unread:")).source == "live"


def test_the_most_serious_finding_is_the_one_at_the_top():
    found = build(
        [
            job(unread=6, applications=6),
            job(slug="auditor", title="Auditor", accepted=3, applications=8),
        ],
        [
            role(gap=4, current=12),
            role(
                department="Finance", role="Auditor", current=17, demand=20, gap=3,
                level="Expert",
            ),
        ],
    )
    order = {"critical": 0, "warning": 1, "info": 2}
    levels = [order[a.level] for a in found]
    assert levels == sorted(levels), [a.level for a in found]


def test_findings_about_an_open_vacancy_come_before_ones_about_a_missing_vacancy():
    """Same severity, and the open jobs are the ones actionable today."""
    found = build(
        [job(applications=2)],
        [role(gap=3), role(role="Legal Counsel", department="Legal", current=4, gap=3)],
    )
    critical = [a for a in found if a.level == "critical"]
    assert len(critical) >= 2
    assert critical[0].job_slug, f"{critical[0].id} has no vacancy behind it"


def test_every_alert_carries_what_the_panel_and_the_email_both_read():
    found = build(
        [job(unread=30, applications=30), job(slug="b", title="Auditor")],
        [
            role(turnover=20.0, turnover_risk="high", people_lost=2),
            role(role="Auditor", department="Finance", level="Expert"),
        ],
    )
    assert len(found) >= 3
    seen = set()
    for alert in found:
        assert alert.id and alert.id not in seen, f"duplicate id {alert.id}"
        seen.add(alert.id)
        assert alert.title and alert.detail, alert.id
        assert alert.level in {"critical", "warning", "info"}, alert.id
        assert set(alert.as_dict()) == {
            "id", "level", "title", "detail", "source",
            "department", "job_slug", "action_label", "action_href",
        }


# -- against the real dataset -----------------------------------------------
def test_the_shipped_forecast_produces_findings_a_person_could_act_on():
    """If this ever comes back empty the feed is dead and nothing else says so."""
    found = build([], ROLES)
    assert len(found) > 5, f"only {len(found)} findings"
    assert all(a.id.startswith("unopened:") for a in found), (
        "with no vacancies open, every finding should be that nothing is open"
    )
    assert any(a.department == "Information Technology" for a in found)


def test_the_python_forecast_still_matches_the_typescript_one():
    """The two are separate files and drift is silent.

    lib/workforce.ts is where the rows are authored and ats/workforce.py is a
    generated copy, because the deployed Python function cannot rely on a data
    file outside its own bundle. Nothing but this notices when they part ways.
    """
    source = (ROOT / "lib" / "workforce.ts").read_text(encoding="utf-8")
    block = source.split("export const ROLES: RoleForecast[] = [")[1].split("];")[0]

    authored = []
    for line in block.splitlines():
        line = line.strip().rstrip(",")
        if line.startswith("{"):
            authored.append(json.loads(re.sub(r"(\w+):", r'"\1":', line)))

    assert len(authored) == len(ROLES), (
        f"{len(authored)} roles in TypeScript, {len(ROLES)} in Python - run "
        f"python scripts/sync_workforce_data.py"
    )
    for ts, py in zip(authored, ROLES):
        assert ts["Job_Role"] == py.role, f"{ts['Job_Role']} != {py.role}"
        assert ts["Department"] == py.department, py.role
        assert ts["Current_Employees"] == py.current, py.role
        assert ts["Predicted_Workforce_Demand"] == py.demand, py.role
        assert ts["Predicted_Workforce_Gap"] == py.gap, py.role


# -- the digest --------------------------------------------------------------
def test_nothing_is_sent_when_nothing_is_wrong():
    """An alert mail that arrives whether or not anything is wrong teaches its
    readers that nothing ever is."""
    with environment(**MAIL_ON), fake_provider() as sent:
        assert notify.alert_digest([]) == []
        assert sent == []


def test_the_digest_is_one_email_per_person_not_one_per_finding():
    found = build([], ROLES)
    assert len(found) > 3

    with environment(**MAIL_ON), fake_provider() as sent:
        results = notify.alert_digest(found)

    assert len(results) == 2, "two addresses, two messages"
    assert len(sent) == 2
    assert all(r.ok for r in results)
    assert {m["to"][0] for m in sent} == {"one@example.com", "two@example.com"}


def test_every_finding_reaches_the_message_body():
    found = build([], ROLES)
    with environment(**MAIL_ON), fake_provider() as sent:
        notify.alert_digest(found)

    text = sent[0]["text"]
    for alert in found:
        assert alert.title in text, f"{alert.id} was left out of the email"


def test_the_email_carries_the_same_caveat_the_dashboard_does():
    """A number in an inbox travels further than the page it came from, and
    arrives without the page's context."""
    with environment(**MAIL_ON), fake_provider() as sent:
        notify.alert_digest(build([], ROLES))

    for message in sent:
        assert "frozen workforce model" in message["text"]
        assert "frozen workforce model" in message["html"]


def test_the_subject_leads_with_what_is_worst():
    critical = [
        Alert(id="a", level="critical", title="Legal is three short",
              detail="x", source="forecast")
    ]
    quiet = [
        Alert(id="b", level="info", title="Something to note",
              detail="x", source="live")
    ]

    with environment(**MAIL_ON), fake_provider() as sent:
        notify.alert_digest(critical)
        notify.alert_digest(quiet)

    assert "1 critical workforce alert" in sent[0]["subject"]
    assert "critical" not in sent[2]["subject"]


def test_a_test_send_is_marked_but_otherwise_identical():
    """A test that sends something different proves nothing about the system."""
    found = build([], ROLES)
    with environment(**MAIL_ON), fake_provider() as sent:
        notify.alert_digest(found, subject_prefix="[test] ")
        notify.alert_digest(found)

    trial, real = sent[0], sent[2]
    assert trial["subject"] == "[test] " + real["subject"]
    assert trial["text"] == real["text"]
    assert trial["html"] == real["html"]


def test_links_are_absolute_or_absent_never_broken():
    """A relative path in an email is a dead link in every mail client."""
    found = build([job(applications=3)], [role()])

    with environment(**MAIL_ON), fake_provider() as sent:
        notify.alert_digest(found, base_url="https://acud.example.com")
    assert "https://acud.example.com/admin/jobs/data-analyst" in sent[0]["text"]

    with environment(**MAIL_ON), fake_provider() as bare:
        notify.alert_digest(found)
    assert "/admin/jobs/" not in bare[0]["text"], "a bare path reached the email"


def test_with_no_provider_nothing_is_sent_and_nothing_raises():
    with environment(RESEND_API_KEY=None, ATS_MAIL_FROM=None,
                     ATS_ALERT_EMAILS="one@example.com"):
        results = notify.alert_digest(build([], ROLES))
        assert results and all(r.skipped for r in results)
        assert not any(r.ok for r in results)


def test_a_provider_outage_is_reported_rather_than_raised():
    with environment(**MAIL_ON):
        with fake_provider(raises=OSError("connection refused")):
            results = notify.alert_digest(build([], ROLES))
    assert results and not any(r.ok for r in results)
    assert all("connection refused" in r.detail for r in results)


def test_the_alert_list_falls_back_to_the_hiring_team_rather_than_to_nobody():
    """A deployment that set one list and not the other meant to be told
    something. Silently sending to no one is the failure this exists to stop."""
    with environment(ATS_ALERT_EMAILS=None, ATS_HR_EMAILS="hr@company.com"):
        assert notify.alert_emails() == ["hr@company.com"]

    with environment(ATS_ALERT_EMAILS="a@b.com", ATS_HR_EMAILS="hr@company.com"):
        assert notify.alert_emails() == ["a@b.com"]

    with environment(ATS_ALERT_EMAILS="not-an-email", ATS_HR_EMAILS=None):
        assert notify.alert_emails() == []


def test_a_name_in_an_alert_cannot_break_the_html():
    """Alert text is built here, but a vacancy title is written by a recruiter
    and reaches the subject line and the body."""
    hostile = [
        Alert(
            id="x",
            level="critical",
            title="<script>alert(1)</script> is short",
            detail="Nothing to see",
            source="forecast",
        )
    ]
    with environment(**MAIL_ON), fake_provider() as sent:
        notify.alert_digest(hostile)

    assert "<script>" not in sent[0]["html"]
    assert "&lt;script&gt;" in sent[0]["html"]
    assert "\n" not in sent[0]["subject"] and "\r" not in sent[0]["subject"]


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {name}: {exc}")
    print(f"\n{'FAILED' if failures else 'ALL PASSED'} ({failures} failure(s))")
    sys.exit(1 if failures else 0)
