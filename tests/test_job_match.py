"""Offline tests for job-description screening. Claude/Gemini are stubbed out.

Run: python tests/test_job_match.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import job_profile as jobs  # noqa: E402
from ats import pipeline  # noqa: E402
from ats.config import Settings  # noqa: E402
from ats.decision import MATCH_FOLDERS, decide_match  # noqa: E402
from ats.extract import extract  # noqa: E402
from ats.job_profile import JobProfile, Requirement  # noqa: E402
from ats.schema import MatchVerdict, RequirementMatch  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def make_profile() -> JobProfile:
    return JobProfile(
        title="Data Analyst",
        seniority="Mid-level",
        summary="Owns the reporting layer.",
        min_years_experience=2,
        requirements=[
            Requirement(text="Strong SQL", kind="skill", importance="must_have"),
            Requirement(text="Power BI", kind="skill", importance="must_have"),
            Requirement(text="2 years experience", kind="experience", importance="must_have"),
            Requirement(text="Python (pandas)", kind="skill", importance="nice_to_have"),
        ],
    )


def make_match(**overrides) -> MatchVerdict:
    base = dict(
        document_type="cv_resume",
        is_cv=True,
        candidate_name="Omar Abdelrahman",
        email="omar@example.com",
        phone="+20 100 000 0000",
        current_title="Data Analyst",
        years_experience=3.0,
        requirement_matches=[
            RequirementMatch(
                requirement="Strong SQL", importance="must_have",
                status="met", evidence="window functions, CTEs, query tuning",
            ),
            RequirementMatch(
                requirement="Power BI", importance="must_have",
                status="met", evidence="11 dashboards, 40 users",
            ),
            RequirementMatch(
                requirement="2 years experience", importance="must_have",
                status="met", evidence="3 years at Alameda Retail",
            ),
            RequirementMatch(
                requirement="Python (pandas)", importance="nice_to_have",
                status="not_met", evidence="",
            ),
        ],
        overall="strong_match",
        strengths=["Owns a reporting stack end to end"],
        gaps=[],
        summary="Meets every requirement for the role.",
        ai_generated_score=10,
        ai_signals=[],
    )
    base.update(overrides)
    return MatchVerdict(**base)


# --------------------------------------------------------------------------
# Job profile
# --------------------------------------------------------------------------
def test_must_have_and_nice_to_have_are_separated():
    profile = make_profile()
    assert len(profile.must_haves) == 3
    assert len(profile.nice_to_haves) == 1
    block = profile.as_prompt_block()
    assert "Strong SQL" in block and "Python (pandas)" in block
    # The model must be able to tell the two lists apart.
    assert block.index("MUST HAVE") < block.index("NICE TO HAVE")


def test_profile_round_trips_to_disk():
    profile = make_profile()
    profile.source_text = "the original advert"
    tmp = Path(tempfile.mkdtemp())
    try:
        path = tmp / "job.json"
        path.write_text(json.dumps(profile.model_dump()), encoding="utf-8")
        loaded = jobs.load(path)
        assert loaded.title == profile.title
        assert len(loaded.must_haves) == 3
        # The advert itself is kept, so the criteria can be audited later.
        assert loaded.source_text == "the original advert"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# The decision
# --------------------------------------------------------------------------
def test_strong_match_is_shortlisted():
    settings = Settings()
    doc = extract(FIXTURES / "sample_human_cv.pdf")
    decision = decide_match(make_match(), doc, make_profile(), settings)

    assert decision.status == "accepted"
    assert decision.role_folder.endswith(MATCH_FOLDERS["strong_match"])
    assert "3 of 3" in decision.explanation
    assert decision.role_label == "Data Analyst"


def test_missing_must_haves_is_not_a_match():
    settings = Settings()
    doc = extract(FIXTURES / "sample_human_cv.pdf")
    matches = make_match().requirement_matches
    matches[1].status = "not_met"
    matches[1].evidence = ""
    verdict = make_match(overall="not_a_match", requirement_matches=matches)

    decision = decide_match(verdict, doc, make_profile(), settings)
    assert decision.status == "rejected"
    assert decision.reason == "not_a_match"
    assert "Power BI" in decision.explanation, "say which requirement was short"


def test_nice_to_have_never_causes_rejection():
    """The whole point of the distinction: optional means optional."""
    settings = Settings()
    doc = extract(FIXTURES / "sample_human_cv.pdf")
    # Python is not met in the default fixture, and every must-have is.
    decision = decide_match(make_match(), doc, make_profile(), settings)
    assert decision.status == "accepted"


def test_ai_suspicion_flags_but_does_not_reject():
    """AI detection is probabilistic; the cost of a false positive is a person."""
    settings = Settings()
    settings.ai_threshold = 70
    doc = extract(FIXTURES / "sample_human_cv.pdf")

    decision = decide_match(make_match(ai_generated_score=95), doc, make_profile(), settings)
    assert decision.status == "accepted", "a flag, not a verdict"
    assert "Possibly AI-written" in decision.explanation
    assert "review" in decision.explanation.lower()


def test_non_cv_is_dropped_before_any_matching():
    settings = Settings()
    doc = extract(FIXTURES / "not_a_cv.txt")
    verdict = make_match(document_type="invoice_or_form", is_cv=False)
    decision = decide_match(verdict, doc, make_profile(), settings)
    assert decision.reason == "not_a_cv"
    assert decision.role_folder.endswith("0_not_a_cv")


# --------------------------------------------------------------------------
# End to end, with the model stubbed
# --------------------------------------------------------------------------
def test_full_run_files_by_outcome():
    profile = make_profile()
    verdicts = {
        "strong.pdf": make_match(),
        "weak.pdf": make_match(
            overall="not_a_match",
            requirement_matches=[
                RequirementMatch(requirement="Strong SQL", importance="must_have",
                                 status="not_met", evidence=""),
                RequirementMatch(requirement="Power BI", importance="must_have",
                                 status="not_met", evidence=""),
                RequirementMatch(requirement="2 years experience",
                                 importance="must_have", status="met",
                                 evidence="2 years"),
                RequirementMatch(requirement="Python (pandas)",
                                 importance="nice_to_have", status="met",
                                 evidence="pandas"),
            ],
        ),
    }

    def fake_match(doc, prof, settings):
        return verdicts[doc.path.name]

    original = pipeline.match
    pipeline.match = fake_match
    tmp = Path(tempfile.mkdtemp())
    try:
        inbox = tmp / "inbox"
        inbox.mkdir()
        for name in verdicts:
            shutil.copy2(FIXTURES / "sample_human_cv.pdf", inbox / name)

        settings = Settings()
        settings.output_dir = tmp / "out"
        settings.max_workers = 1

        results = pipeline.screen_many(
            pipeline.discover(inbox), settings, profile=profile
        )
        by_name = {r.filename: r for r in results}

        strong = by_name["strong.pdf"]
        assert strong.overall == "strong_match"
        assert strong.must_haves_met == 3 and strong.must_haves_total == 3
        assert strong.missing == [], "nothing must-have is short"
        assert strong.missing_optional == ["Python (pandas)"]
        # With nothing short, the line shows what the candidate brings rather than
        # restating the count already on the row.
        assert strong.summary_line() == "Owns a reporting stack end to end"
        strong.strengths = []
        assert strong.summary_line() == "meets every must-have"

        weak = by_name["weak.pdf"]
        assert weak.overall == "not_a_match"
        assert set(weak.missing) == {"Strong SQL", "Power BI"}
        assert "Python" not in " ".join(weak.missing), "optional gaps stay out"

        assert (settings.output_dir / "Data_Analyst" / "1_matched" / "strong.pdf").exists()
        assert (settings.output_dir / "Data_Analyst" / "3_not_matched" / "weak.pdf").exists()

        assert pipeline.summarize(results)["by_outcome"]["strong_match"] == 1
    finally:
        pipeline.match = original
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
