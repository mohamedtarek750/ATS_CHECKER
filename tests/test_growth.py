"""What the system offers somebody it turned down.

A percentage on its own tells a candidate they were not good enough and nothing
else. This turns the requirements they missed into something they can act on -
and the whole value of it rests on two claims that have to keep being true:

  * Nothing is recommended that they did not actually miss. Advice that does
    not trace to a requirement in the advert is a horoscope.
  * The arithmetic is the scoring engine's own, so "this would take you to 79%"
    is a promise the system can keep.

The rest is about restraint: no invented URLs, no course sold as a fix for a
gap that is really time, no score in the email, and nothing sent without a
person pressing send.

Run: python tests/test_growth.py
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import growth, notify  # noqa: E402
from ats.job_profile import JobProfile, Requirement  # noqa: E402
from ats.postings import Application, JobPosting  # noqa: E402
from ats.stages import match as match_stage  # noqa: E402
from ats.stages import offline, parse, rank  # noqa: E402


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
    ATS_SMTP_HOST=None,
    ATS_SCRIPT_URL=None,
)


@contextlib.contextmanager
def fake_provider():
    sent: list[dict] = []
    original = urllib.request.urlopen

    class Response:
        status = 200

        def read(self):
            return b'{"id":"test"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(request, timeout=None):
        sent.append(json.loads(request.data.decode("utf-8")))
        return Response()

    urllib.request.urlopen = fake
    try:
        yield sent
    finally:
        urllib.request.urlopen = original


def make_job(**over) -> JobProfile:
    base = dict(
        title="Data Analyst",
        seniority="Mid-level",
        summary="Owns commercial reporting.",
        min_years_experience=5,
        requirements=[
            Requirement(text="Strong SQL", kind="skill", importance="must_have"),
            Requirement(text="Kubernetes", kind="skill", importance="must_have"),
            Requirement(text="5 years of professional experience",
                        kind="experience", importance="must_have"),
            Requirement(text="Cloud platforms (AWS or Azure)",
                        kind="skill", importance="nice_to_have"),
        ],
    )
    base.update(over)
    return JobProfile(**base)


def plan_for(job: JobProfile):
    doc = parse.parse_one(ROOT / "samples" / "01_data_analyst_omar.pdf")
    result = match_stage.match(offline.extract_profile(doc), job, "omar.pdf")
    return growth.build(result, rank.percent_of(result)), result


# -- nothing is recommended that was not missed -------------------------------
def test_every_step_is_a_requirement_the_advert_really_asked_for():
    """Advice that does not trace to a requirement is a horoscope."""
    job = make_job()
    plan, _result = plan_for(job)

    asked = {r.text for r in job.requirements}
    assert plan.steps, "a CV that misses several requirements produced no steps"
    for step in plan.steps:
        assert step.requirement in asked, step.requirement


def test_a_requirement_the_cv_met_is_never_suggested():
    plan, result = plan_for(make_job())
    met = {r.requirement for r in result.results
           if r.counts_as_met and r.strength in {"strong", "valid"}}
    for step in plan.steps:
        assert step.requirement not in met, f"{step.requirement} was already met"


def test_a_cv_that_meets_everything_is_told_nothing():
    """The panel and the email both stay silent rather than inventing advice."""
    job = make_job(
        min_years_experience=0,
        requirements=[Requirement(text="SQL", kind="skill", importance="must_have")],
    )
    plan, _result = plan_for(job)
    assert plan.steps == []
    assert not plan.has_anything_to_say


# -- the arithmetic is the engine's own ---------------------------------------
def test_the_projected_score_is_the_scoring_engine_run_again():
    """"This would take you to 79%" has to be a number the system can keep."""
    plan, result = plan_for(make_job())

    # Every unmet requirement met at full strength IS the projection.
    for one in result.results:
        if not (one.counts_as_met and one.strength in {"strong", "valid"}):
            one.strength = "strong"
    assert rank.percent_of(result) == plan.percent_after


def test_the_points_add_up_to_the_gain():
    plan, _result = plan_for(make_job())
    assert round(sum(s.worth for s in plan.steps)) == plan.gain


def test_a_must_have_is_worth_more_than_a_nice_to_have():
    """Otherwise the list sends somebody after the wrong thing first."""
    plan, _result = plan_for(make_job())
    musts = [s for s in plan.steps if s.is_must]
    nices = [s for s in plan.steps if not s.is_must]
    assert musts and nices
    assert min(s.worth for s in musts) > max(s.worth for s in nices)

    # And they are listed in that order.
    assert [s.is_must for s in plan.steps] == sorted(
        [s.is_must for s in plan.steps], reverse=True
    )


def test_reaching_the_bar_is_reported_honestly_either_way():
    short = make_job(requirements=[
        Requirement(text="Kubernetes", kind="skill", importance="must_have"),
        Requirement(text="Strong SQL", kind="skill", importance="must_have"),
    ])
    plan, _result = plan_for(short)
    assert plan.reaches_bar is (plan.percent_after >= rank.WAITING_LIST_AT)


# -- what it will not do ------------------------------------------------------
def test_no_url_is_ever_invented():
    """A dead link in an email to somebody just turned down is worse than none.

    Every URL is a search on a platform that will still exist, or a root page -
    never a deep link into a syllabus that gets retired and renamed.
    """
    plan, _result = plan_for(make_job())
    allowed = (
        "coursera.org/search", "edx.org/search",
        "learn.microsoft.com/en-us/training/browse/",
        "youtube.com/results", "google.com/search",
        "freecodecamp.org/learn", "kaggle.com/learn",
        "kaggle.com/competitions", "github.com/new", "goodfirstissue.dev/",
    )
    seen = 0
    for step in plan.steps:
        for resource in step.resources:
            seen += 1
            assert resource.url.startswith("https://"), resource.url
            assert any(good in resource.url for good in allowed), resource.url
    assert seen > 0, "no resources were offered at all"


def test_a_course_is_never_offered_for_a_gap_that_is_time():
    """Buying a certificate does not fix "five years of experience", and
    implying it does is how somebody spends money on the wrong thing."""
    plan, _result = plan_for(make_job())
    experience = [s for s in plan.steps if s.kind == "experience"]
    assert experience, "the experience gap was not reported at all"

    for step in experience:
        assert all(r.kind == "practice" for r in step.resources), step.resources
        assert "cannot be studied for" in step.advice
    assert "not knowledge of it" in plan.experience_note


def test_the_search_keeps_what_is_inside_the_brackets():
    """In "Cloud platforms (AWS or Azure)" the searchable half is in brackets."""
    resources = growth.resources_for("Cloud platforms (AWS or Azure)", "skill")
    assert any("AWS" in r.url and "Azure" in r.url for r in resources)

    # And the padding an advert is written with does not reach the search.
    assert "strong" not in growth._query("Strong SQL including window functions").lower()
    assert "SQL" in growth._query("Strong SQL including window functions")


def test_microsoft_learn_is_only_offered_for_microsoft_things():
    """It is the right first stop for Power BI and noise for Kubernetes."""
    for requirement in ("Power BI", "Azure Data Factory", "Advanced Excel"):
        assert any(
            "microsoft" in r.url for r in growth.resources_for(requirement, "skill")
        ), requirement
    for requirement in ("Kubernetes", "PostgreSQL", "Figma"):
        assert not any(
            "microsoft" in r.url for r in growth.resources_for(requirement, "skill")
        ), requirement


# -- the email ----------------------------------------------------------------
def test_the_email_carries_the_gaps_and_never_the_score():
    """The percentage is the engine's working against one advert. Sending it
    turns an internal figure into a grade somebody carries around."""
    job = make_job()
    posting = JobPosting(slug="data-analyst", title="Data Analyst",
                         summary="", profile=job)
    plan, _result = plan_for(job)
    row = Application(job_slug="data-analyst", full_name="Omar Hassan",
                      email="omar@example.com")

    with environment(**MAIL_ON), fake_provider() as sent:
        assert notify.development_plan(row, posting, plan).ok

    message = sent[0]
    assert message["to"] == ["omar@example.com"]
    assert "Data Analyst" in message["subject"]

    body = message["text"]
    for step in plan.steps:
        assert step.requirement in body, step.requirement
    for number in (f"{plan.percent_now}%", f"{plan.percent_after}%", "score", "rank"):
        assert number not in body, f"{number!r} reached the candidate"


def test_the_email_says_a_person_sent_it_because_a_person_did():
    job = make_job()
    posting = JobPosting(slug="x", title="Data Analyst", summary="", profile=job)
    plan, _result = plan_for(job)
    row = Application(job_slug="x", full_name="Omar", email="omar@example.com")

    with environment(**MAIL_ON), fake_provider() as sent:
        notify.development_plan(row, posting, plan)

    assert "not automatically" in sent[0]["text"]


def test_a_name_from_a_public_form_cannot_inject_markup_into_the_plan():
    job = make_job()
    posting = JobPosting(slug="x", title="Data Analyst", summary="", profile=job)
    plan, _result = plan_for(job)
    row = Application(
        job_slug="x",
        full_name="Omar<script>alert(1)</script>",
        email="omar@example.com",
    )

    with environment(**MAIL_ON), fake_provider() as sent:
        notify.development_plan(row, posting, plan)

    assert "<script>" not in sent[0]["html"]
    assert "&lt;script&gt;" in sent[0]["html"]


def test_nothing_is_sent_when_there_is_nothing_to_say():
    job = make_job(
        min_years_experience=0,
        requirements=[Requirement(text="SQL", kind="skill", importance="must_have")],
    )
    posting = JobPosting(slug="x", title="Data Analyst", summary="", profile=job)
    plan, _result = plan_for(job)
    row = Application(job_slug="x", full_name="Omar", email="omar@example.com")

    with environment(**MAIL_ON), fake_provider() as sent:
        result = notify.development_plan(row, posting, plan)
    assert result.skipped and sent == []


def test_no_schedule_and_no_loop_can_send_one():
    """The rule this whole feature had to be built around.

    A plan that arrives unasked tells somebody they were rejected, by a
    machine. It goes out because a recruiter pressed send, having read it - so
    nothing that runs on its own may call it.
    """
    for module in ("api/index.py", "ats/notify.py", "ats/intake.py"):
        source = (ROOT / module).read_text(encoding="utf-8")
        for line_number, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            # Only CALLS matter. A definition, a route, or a comment naming it
            # is not something that sends anything.
            if "development_plan(" not in stripped or stripped.startswith(("#", "def ", "@")):
                continue
            assert stripped.startswith("result = notify.development_plan("), (
                f"{module}:{line_number} calls it: {stripped}"
            )

    cron = (ROOT / "api" / "index.py").read_text(encoding="utf-8")
    after_cron = cron.split("def cron_intake")[1]
    assert "development_plan" not in after_cron, "the scheduled run sends plans"


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
