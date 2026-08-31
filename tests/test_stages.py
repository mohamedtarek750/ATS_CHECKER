"""Offline tests for the five-stage pipeline. No API key, no network.

Stages 1, 4 and 5 have no model call at all, so they are tested directly. Stage 2
is stubbed; stage 3 reuses the job-profile tests.

Run: python tests/test_stages.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import screening, store  # noqa: E402
from ats.config import Settings  # noqa: E402
from ats.job_profile import JobProfile, Requirement  # noqa: E402
from ats.models import CandidateProfile, Education, Experience  # noqa: E402
from ats.skills import canonical, mentions, normalize_all  # noqa: E402
from ats.stages import match as match_stage  # noqa: E402
from ats.stages import normalize, parse, rank  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def make_candidate(**overrides) -> CandidateProfile:
    base = dict(
        full_name="Omar Abdelrahman", email="omar@example.com", phone="+20 100",
        location="Giza", links=[], headline="Data Analyst", seniority="mid",
        total_years_experience=3.0,
        education=[Education(degree="bachelor", field_of_study="Statistics",
                             institution="Cairo University", graduation_year=2022)],
        experience=[Experience(title="Data Analyst", company="Alameda", start="2024-03",
                               end="present", years=2.5, is_internship=False,
                               highlights=["Rewrote the stock-cover query"])],
        skills=["SQL", "Power BI", "Excel", "Power Query", "Python"],
        certifications=["Microsoft PL-300 Power BI Data Analyst"],
        languages=["Arabic (native)", "English (fluent)"], projects=[],
        document_type="cv_resume", is_cv=True, ai_generated_score=10, ai_signals=[],
    )
    base.update(overrides)
    return CandidateProfile(**base)


def make_job(**overrides) -> JobProfile:
    base = dict(
        title="Data Analyst", seniority="Mid-level", summary="Owns reporting.",
        min_years_experience=2,
        requirements=[
            Requirement(text="Bachelor degree in Statistics, Computer Science or a related field",
                        kind="education", importance="must_have"),
            Requirement(text="2 years of professional experience in a data role",
                        kind="experience", importance="must_have"),
            Requirement(text="Strong SQL", kind="skill", importance="must_have"),
            Requirement(text="Power BI or Tableau", kind="skill", importance="must_have"),
            Requirement(text="Written English", kind="language", importance="must_have"),
            Requirement(text="Azure or Databricks", kind="skill", importance="nice_to_have"),
            Requirement(text="PL-300 certification", kind="certification",
                        importance="nice_to_have"),
        ],
    )
    base.update(overrides)
    return JobProfile(**base)


# --------------------------------------------------------------------------
# Normalization - the thing that stops matching from being string comparison
# --------------------------------------------------------------------------
def test_spellings_collapse_to_one_name():
    assert canonical("MS SQL Server") == "SQL"
    assert canonical("T-SQL") == "SQL"
    assert canonical("PowerBI") == "Power BI"
    assert canonical("Python (advanced)") == "Python"
    assert normalize_all(["T-SQL", "sql server", "SQL"]) == ["SQL"]


def test_short_skill_names_do_not_match_inside_words():
    """The classic failure: 'R' matching 'React', 'Go' matching 'Google'."""
    text = "Built with React on Google Cloud, plus Angular."
    assert not mentions(text, "R")
    assert not mentions(text, "Go")
    assert mentions(text, "React")
    assert mentions(text, "GCP"), "'Google Cloud' is GCP"


# --------------------------------------------------------------------------
# Stage 4 - matching
# --------------------------------------------------------------------------
def test_a_qualified_candidate_meets_every_must_have():
    result = match_stage.match(make_candidate(), make_job(), "omar.pdf")
    assert result.must_met == result.must_total == 5
    assert result.missing_labels == []
    # Every "met" must be able to say why.
    for entry in result.must_results:
        assert entry.evidence, f"{entry.requirement} was met with no evidence"


def test_a_skill_written_differently_still_counts():
    """A candidate is not failed for writing 'MS SQL Server' instead of 'SQL'."""
    candidate = make_candidate(skills=["MS SQL Server", "PowerBI", "Excel"])
    result = match_stage.match(candidate, make_job())
    statuses = {r.requirement: r.status for r in result.results}
    assert statuses["Strong SQL"] == "met"
    assert statuses["Power BI or Tableau"] == "met"


def test_a_skill_only_shown_in_a_project_counts():
    """Candidates who do not pad a skills section must not be penalised."""
    candidate = make_candidate(
        skills=["Excel"],
        experience=[Experience(title="Analyst", company="X", start="2022", end="2025",
                               years=3, is_internship=False,
                               highlights=["Wrote SQL window functions for the weekly pack"])],
    )
    result = match_stage.match(candidate, make_job())
    sql = next(r for r in result.results if r.requirement == "Strong SQL")
    assert sql.status == "met"


def test_alternatives_are_satisfied_by_either():
    """Either side of an "or" satisfies it, and the evidence names which."""
    candidate = make_candidate(
        skills=["SQL", "Tableau", "Excel", "Power Query"], certifications=[]
    )
    result = match_stage.match(candidate, make_job())
    both = next(r for r in result.results if "Power BI or Tableau" in r.requirement)
    # Listed in the skills section and nowhere else. The candidate is asserting
    # the skill, so the requirement is MET - calling it "close" tells a recruiter
    # something the CV does not say. What separates this from a demonstrated
    # skill is the strength, not the status, and the strength is what the score
    # is computed from.
    assert both.status == "met"
    assert both.strength == "valid"
    assert both.source == "skills"
    assert "Tableau" in both.evidence, both.evidence

    # Shown in a role: the same requirement, now genuinely met.
    shown = make_candidate(
        skills=["SQL", "Excel"],
        certifications=[],
        experience=[
            Experience(
                title="Data Analyst", company="Alameda", start="2022", end="present",
                years=3, is_internship=False,
                highlights=["Built the weekly pack in Tableau for 40 users"],
            )
        ],
    )
    demonstrated = next(
        r
        for r in match_stage.match(shown, make_job()).results
        if "Power BI or Tableau" in r.requirement
    )
    assert demonstrated.status == "met"
    assert demonstrated.match_kind == "demonstrated"
    assert demonstrated.strength == "strong"
    assert demonstrated.source == "experience"
    # Both are met; the one shown in a role is worth more, and the score knows it.
    assert demonstrated.credit > both.credit
    assert demonstrated.confidence > both.confidence

    # A certification naming the other side is stronger evidence than a skills
    # entry, and is preferred when present.
    certified = make_candidate(
        skills=["SQL", "Excel"],
        certifications=["Microsoft PL-300 Power BI Data Analyst"],
    )
    via_cert = next(
        r
        for r in match_stage.match(certified, make_job()).results
        if "Power BI or Tableau" in r.requirement
    )
    assert via_cert.status == "met"
    assert "PL-300" in via_cert.evidence


def test_a_near_miss_on_years_is_partial_not_a_failure():
    result = match_stage.match(make_candidate(total_years_experience=1.5), make_job())
    years = next(r for r in result.results if "2 years" in r.requirement)
    assert years.status == "partial", "1.5 against 2 is a near miss, not an absence"

    far = match_stage.match(make_candidate(total_years_experience=0.0), make_job())
    assert next(r for r in far.results if "2 years" in r.requirement).status == "not_met"


def test_an_unlisted_but_related_degree_is_unclear_not_rejected():
    """Adverts say 'or a related field'. A machine should not rule on that alone."""
    candidate = make_candidate(
        education=[Education(degree="bachelor", field_of_study="Physics",
                             institution="Cairo University", graduation_year=2020)]
    )
    result = match_stage.match(candidate, make_job())
    degree = next(r for r in result.results if r.kind == "education")
    assert degree.status == "unclear"


def test_english_is_evidenced_by_the_cv_being_in_english():
    candidate = make_candidate(languages=[])
    result = match_stage.match(candidate, make_job())
    english = next(r for r in result.results if r.kind == "language")
    assert english.status == "met"


def test_a_certification_matches_on_its_code_not_the_whole_phrase():
    result = match_stage.match(make_candidate(), make_job())
    cert = next(r for r in result.results if r.kind == "certification")
    assert cert.status == "met"
    assert "PL-300" in cert.evidence


# --------------------------------------------------------------------------
# Stage 5 - ranking
# --------------------------------------------------------------------------
def test_tiers_follow_must_haves_only():
    job = make_job()
    full = match_stage.match(make_candidate(), job)
    assert rank.rank([full])[0].tier == "shortlist", "no nice-to-haves, still a match"

    # Clear the certification too: a Power BI certificate IS evidence of Power BI,
    # so leaving it in would credit the candidate with a skill they do have.
    weak = match_stage.match(
        make_candidate(skills=["Excel"], certifications=[], headline="Office Admin"), job
    )
    assert rank.rank([weak])[0].tier == "not_a_match"


def test_a_single_near_miss_lands_in_review_not_rejected():
    job = make_job()
    close = match_stage.match(make_candidate(total_years_experience=1.5), job)
    entry = rank.rank([close])[0]
    assert entry.tier == "review", "a human should see this, not have it closed"
    assert "Close on" in entry.reason


def test_ordering_puts_the_best_fit_first():
    job = make_job()
    # "Weak" has to be weak everywhere the engine now looks: a Power BI
    # certification or a Data Analyst headline is evidence, so leaving those in
    # would make this candidate a reasonable match rather than a poor one.
    results = [
        match_stage.match(
            make_candidate(
                full_name="Weak", skills=["Excel"], certifications=[],
                headline="Office Administrator", experience=[],
            ),
            job,
        ),
        match_stage.match(make_candidate(full_name="Strong"), job),
        match_stage.match(make_candidate(full_name="Close", total_years_experience=1.5), job),
    ]
    order = [r.name for r in rank.rank(results)]
    assert order[0] == "Strong"
    assert order[-1] == "Weak"


def test_a_non_cv_never_reaches_a_tier_of_its_own():
    job = make_job()
    letter = make_candidate(is_cv=False, document_type="cover_letter")
    entry = rank.rank([match_stage.match(letter, job)])[0]
    assert entry.tier == "not_a_cv"


def test_ai_suspicion_is_a_flag_and_changes_no_tier():
    job = make_job()
    flagged = match_stage.match(make_candidate(ai_generated_score=95), job)
    entry = rank.rank([flagged])[0]
    assert entry.flagged_ai is True
    assert entry.tier == "shortlist", "the flag must not decide anything"


# --------------------------------------------------------------------------
# The point of the whole design: parse once, match forever
# --------------------------------------------------------------------------
def test_a_stored_candidate_is_never_read_twice():
    calls: list[str] = []

    def fake_structured(system, user, schema, settings):
        calls.append(user[:20])
        return make_candidate()

    class FakeProvider:
        active_model = "fake"

        def structured(self, system, user, schema, settings):
            return fake_structured(system, user, schema, settings)

    tmp = Path(tempfile.mkdtemp())
    inbox = tmp / "inbox"
    inbox.mkdir()
    for i in range(3):
        shutil.copy2(FIXTURES / "sample_human_cv.pdf", inbox / f"cv_{i}.pdf")
    # Same content under a different name: the pool should recognise it.
    shutil.copy2(FIXTURES / "sample_human_cv.pdf", inbox / "renamed_copy.pdf")

    settings = Settings()
    settings.output_dir = tmp / "out"
    settings.max_workers = 1

    original = normalize.get_provider
    normalize.get_provider = lambda name: FakeProvider()
    try:
        paths = parse.discover(inbox)
        first = screening.intake(paths, settings)
        assert first.added == 1, "four identical files are one candidate"
        assert len(calls) == 1

        calls.clear()
        second = screening.intake(paths, settings)
        assert second.added == 0
        assert calls == [], "nothing is read a second time"
        assert screening.pending_count(paths, settings) == 0
    finally:
        normalize.get_provider = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_ranking_a_large_pool_is_fast_and_needs_no_model():
    """The property that makes thousands of CVs practical."""
    tmp = Path(tempfile.mkdtemp())
    settings = Settings()
    settings.output_dir = tmp
    try:
        for i in range(500):
            store.put(
                settings, f"hash{i:05d}",
                make_candidate(full_name=f"Person {i}", email=f"p{i}@e.com"),
                Path(f"cv_{i}.pdf"),
            )
        started = time.perf_counter()
        ranked = screening.shortlist(make_job(), settings)
        elapsed = time.perf_counter() - started

        assert len(ranked) == 500
        assert elapsed < 5.0, f"500 candidates took {elapsed:.1f}s"
        assert rank.summarize(ranked)["shortlist"] == 500
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# Evidence strength, requirement logic, and what the two of them do to a score
# --------------------------------------------------------------------------
def test_a_listed_skill_is_met_and_a_demonstrated_one_is_worth_more():
    """The distinction lives in the strength, never in the status.

    Reporting a skill written in the Technical Skills section as "not found" or
    "close" is simply wrong about the document, and it is the single complaint
    candidates make about ATS software most often.
    """
    listed = make_candidate(skills=["SQL", "Power BI", "Excel"], certifications=[],
                            projects=["Rebuilt the stock report"])
    entry = next(r for r in match_stage.match(listed, make_job()).results
                 if r.requirement == "Strong SQL")
    assert entry.status == "met"
    assert entry.strength == "valid"
    assert entry.source == "skills"
    assert "SQL" in entry.evidence
    assert entry.explanation, "a verdict with no explanation cannot be checked"

    shown = make_candidate(
        skills=["Excel"], certifications=[],
        experience=[Experience(title="Analyst", company="X", start="2022", end="2025",
                               years=3, is_internship=False,
                               highlights=["Wrote SQL window functions for the pack"])],
    )
    proven = next(r for r in match_stage.match(shown, make_job()).results
                  if r.requirement == "Strong SQL")
    assert proven.status == "met"
    assert proven.strength == "strong"
    assert proven.credit > entry.credit


def test_a_missing_preferred_skill_costs_less_than_a_missing_required_one():
    """Otherwise 'preferred' is a word with no effect on anything."""
    job = make_job(requirements=[
        Requirement(text="Strong SQL", kind="skill", importance="must_have"),
        Requirement(text="Power BI", kind="skill", importance="must_have"),
        Requirement(text="Kubernetes", kind="skill", importance="nice_to_have"),
    ])
    misses_optional = rank.rank([match_stage.match(
        make_candidate(skills=["SQL", "Power BI"], certifications=[]), job
    )])[0]
    misses_required = rank.rank([match_stage.match(
        make_candidate(skills=["SQL", "Kubernetes"], certifications=[]), job
    )])[0]

    # Each candidate is missing exactly one requirement. The one who is missing
    # something the advert only preferred must come out ahead - otherwise the
    # word "preferred" has no effect on anything and the distinction is theatre.
    assert misses_optional.percent > misses_required.percent
    assert misses_optional.tier == "shortlist"
    assert misses_required.tier != "shortlist"

    # And the two figures are reported apart, so a reader can see which is which.
    assert misses_optional.required_percent > misses_optional.preferred_percent
    assert misses_optional.preferred_percent == 0


def test_an_either_or_requirement_is_met_in_full_by_either_side():
    job = make_job(requirements=[
        Requirement(text="Docker or Kubernetes", kind="skill", importance="must_have",
                    any_of=["Docker", "Kubernetes"]),
    ])
    with_second = rank.rank([match_stage.match(
        make_candidate(skills=["Kubernetes"], certifications=[]), job
    )])[0]
    with_first = rank.rank([match_stage.match(
        make_candidate(skills=["Docker"], certifications=[]), job
    )])[0]
    with_neither = rank.rank([match_stage.match(
        make_candidate(skills=["Excel"], certifications=[]), job
    )])[0]

    # Either alternative satisfies it, and satisfies it identically. Splitting an
    # "or" into two requirements is what scores a Kubernetes engineer at 50% on a
    # line they fully meet.
    assert with_second.required_percent == with_first.required_percent
    assert with_second.required_percent > with_neither.required_percent
    assert with_second.match.results[0].status == "met"
    assert "Kubernetes" in with_second.match.results[0].explanation
    assert with_neither.match.results[0].status == "not_met"


def test_supporting_keywords_find_the_skill_under_another_name():
    """A CV that says 'trained a ResNet' has done deep learning."""
    job = make_job(requirements=[
        Requirement(text="Deep learning", kind="skill", importance="must_have",
                    keywords=["neural network", "PyTorch", "ResNet"]),
    ])
    candidate = make_candidate(
        skills=["Python"], certifications=[],
        experience=[Experience(title="ML Engineer", company="X", start="2022",
                               end="2025", years=3, is_internship=False,
                               highlights=["Trained a ResNet on chest X-rays"])],
    )
    result = match_stage.match(candidate, job).results[0]
    assert result.status == "met"
    assert result.strength == "strong"
    assert "ResNet" in result.evidence


def test_a_skills_wall_with_no_work_behind_it_counts_for_less():
    """Still met - the candidate does claim it - but not worth a proven skill."""
    stuffed = make_candidate(
        skills=["SQL", "Power BI", "Python", "Spark", "Airflow", "Kafka", "dbt",
                "AWS", "Azure", "Docker", "Kubernetes", "Tableau", "Excel"],
        certifications=[], experience=[], projects=[],
    )
    claim = next(r for r in match_stage.match(stuffed, make_job()).results
                 if r.requirement == "Strong SQL")
    assert claim.status == "met", "the skill is on the CV and must be reported so"
    assert claim.strength == "partial"
    assert "corroborates" in claim.explanation

    # A short, honest CV is not caught by the same rule.
    honest = make_candidate(skills=["SQL", "Power BI"], certifications=[],
                            experience=[], projects=["Weekly sales dashboard"])
    fine = next(r for r in match_stage.match(honest, make_job()).results
                if r.requirement == "Strong SQL")
    assert fine.strength == "valid"


def test_the_same_requirement_listed_twice_is_scored_once():
    job = make_job(requirements=[
        Requirement(text="SQL", kind="skill", importance="nice_to_have"),
        Requirement(text="Strong SQL", kind="skill", importance="must_have"),
        Requirement(text="Power BI", kind="skill", importance="must_have"),
    ]).deduplicate()
    assert len(job.requirements) == 2
    # The must-have survives, never its nice-to-have twin.
    assert job.requirements[0].importance == "must_have"


# --------------------------------------------------------------------------
# Is there experience, and is it the experience this job asked for?
# --------------------------------------------------------------------------
def _worker(*roles) -> CandidateProfile:
    return make_candidate(
        experience=list(roles),
        total_years_experience=sum(r.years for r in roles),
        skills=["SQL", "Power BI"], certifications=[],
    )


def _role(title, years, highlights, internship=False) -> Experience:
    return Experience(
        title=title, company="Acme", start="2020", end="present", years=years,
        is_internship=internship, highlights=list(highlights),
    )


def test_ten_years_in_another_field_is_not_ten_relevant_years():
    """The failure this exists to stop: "10 years" satisfying "3+ years"."""
    job = make_job()
    changer = _worker(_role("Site Engineer", 10, [
        "Supervised concrete pours and site safety.",
        "Managed subcontractor schedules.",
    ]))
    result = match_stage.match(changer, job)
    review = result.experience

    assert review.has_experience
    assert review.total_years == 10
    assert review.relevant_years == 0
    assert review.roles[0].relevance == "unrelated"

    years = next(r for r in result.results if "2 years" in r.requirement)
    # Not a rejection - a decade of work is real and might transfer. But it is
    # not a clean "met" either, and the reason says which is which.
    assert years.status == "partial"
    assert "only 0 of it evidences this job" in years.explanation


def test_relevant_work_meets_the_years_requirement_outright():
    job = make_job()
    analyst = _worker(_role("Data Analyst", 4, [
        "Built the weekly pack in Power BI for 40 users.",
        "Rewrote the stock-cover query in SQL.",
    ]))
    result = match_stage.match(analyst, job)
    review = result.experience

    assert review.relevant_years == 4
    assert review.roles[0].relevance == "core"
    assert review.roles[0].has_outcomes, "40 users is a measurable outcome"
    assert set(review.roles[0].demonstrates) >= {"Strong SQL", "Power BI or Tableau"}
    assert next(r for r in result.results if "2 years" in r.requirement).status == "met"


def test_only_the_relevant_half_of_a_mixed_career_counts():
    job = make_job()
    mixed = _worker(
        _role("Data Analyst", 2, ["Built SQL reports and Power BI dashboards."]),
        _role("Sales Representative", 6, ["Sold packaging to retail clients."]),
    )
    review = match_stage.match(mixed, job).experience
    assert review.total_years == 8
    assert review.relevant_years == 2
    assert [r.relevance for r in review.roles] == ["core", "unrelated"]


def test_a_role_the_cv_never_describes_is_unclear_not_unrelated():
    """A thin CV is a fact about the document, not a verdict on the person."""
    job = make_job()
    terse = _worker(_role("Warehouse Supervisor", 5, []))
    review = match_stage.match(terse, job).experience

    assert review.roles[0].relevance == "unclear"
    # Counted, because calling it irrelevant would be a claim the page does not
    # support - and the verdict says so out loud.
    assert review.relevant_years == 5
    assert "does not describe" in review.verdict


def test_no_experience_is_reported_plainly():
    job = make_job()
    graduate = make_candidate(experience=[], total_years_experience=0.0,
                              certifications=[])
    review = match_stage.match(graduate, job).experience
    assert not review.has_experience
    assert review.relevant_years == 0
    assert "No professional experience" in review.verdict
    assert review.roles == []


def test_relevant_years_never_exceed_the_total():
    """Role durations and the computed total can disagree; the panel cannot."""
    job = make_job()
    odd = make_candidate(
        total_years_experience=1.5,
        experience=[_role("Data Analyst", 2.5, ["Wrote SQL for the weekly pack."])],
        certifications=[],
    )
    review = match_stage.match(odd, job).experience
    assert review.relevant_years <= review.total_years


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'FAILED' if failures else 'ALL PASSED'} ({failures} failure(s))")
    raise SystemExit(1 if failures else 0)
