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
    candidate = make_candidate(skills=["SQL", "Tableau", "Excel", "Power Query"])
    result = match_stage.match(candidate, make_job())
    both = next(r for r in result.results if "Power BI or Tableau" in r.requirement)
    assert both.status == "met" and "Tableau" in both.evidence


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
    results = [
        match_stage.match(make_candidate(full_name="Weak", skills=["Excel"]), job),
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
