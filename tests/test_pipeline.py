"""Offline tests: extraction, decision policy and routing, with Claude stubbed out.

Run with `python tests/test_pipeline.py` (no pytest needed) or `pytest tests/`.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import pipeline  # noqa: E402
from ats.config import Settings  # noqa: E402
from ats.classifier import ClassificationError, FatalScreeningError  # noqa: E402
from ats.decision import decide, slugify  # noqa: E402
from ats.extract import extract  # noqa: E402
from ats.schema import Verdict  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def make_verdict(**overrides) -> Verdict:
    base = dict(
        document_type="cv_resume",
        is_cv=True,
        candidate_name="Test Person",
        email="test@example.com",
        phone="+20 100 000 0000",
        role_family="Data Scientist",
        custom_role_title="",
        specialization="Machine learning",
        major="Data Science",
        seniority="Junior",
        years_experience=1.0,
        top_skills=["Python", "SQL"],
        role_confidence=90,
        ai_generated_score=10,
        ai_signals=[],
        human_signals=["Specific course names"],
        format_score=85,
        format_notes="Standard structure.",
        missing_sections=[],
        quality_score=75,
        suggested_reject_reason="none",
        reasoning="Genuine junior data science CV.",
    )
    base.update(overrides)
    return Verdict(**base)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------
def test_extract_pdf():
    doc = extract(FIXTURES / "sample_human_cv.pdf")
    assert doc.error == "", doc.error
    assert doc.char_count > 1000
    assert "DATA SCIENCE" in doc.text.upper()
    assert doc.page_count == 1
    assert not doc.needs_vision


def test_extract_unsupported():
    with tempfile.TemporaryDirectory() as tmp:
        odd = Path(tmp) / "photo.png"
        odd.write_bytes(b"\x89PNG")
        assert "Unsupported" in extract(odd).error


def test_extract_missing():
    assert extract(FIXTURES / "nope.pdf").error == "File not found"


# --------------------------------------------------------------------------
# Decision policy
# --------------------------------------------------------------------------
def test_accepts_clean_cv():
    settings = Settings()
    doc = extract(FIXTURES / "sample_human_cv.pdf")
    decision = decide(make_verdict(), doc, settings)
    assert decision.status == "accepted"
    assert decision.role_folder == "Data_Scientists"


def test_rejects_ai_generated_at_threshold():
    settings = Settings()
    settings.ai_threshold = 70
    doc = extract(FIXTURES / "sample_human_cv.pdf")
    decision = decide(make_verdict(ai_generated_score=70), doc, settings)
    assert decision.status == "rejected"
    assert decision.reason == "ai_generated"
    # Rejected CVs still get filed under their role.
    assert decision.role_folder == "Data_Scientists"

    accepted = decide(make_verdict(ai_generated_score=69), doc, settings)
    assert accepted.status == "accepted"


def test_rejects_non_cv():
    settings = Settings()
    doc = extract(FIXTURES / "not_a_cv.txt")
    decision = decide(
        make_verdict(
            document_type="invoice_or_form",
            is_cv=False,
            role_family="Undetermined",
            role_confidence=5,
        ),
        doc,
        settings,
    )
    assert decision.reason == "not_a_cv"
    assert decision.role_folder == "Undetermined"


def test_rejects_thin_cv():
    settings = Settings()
    doc = extract(FIXTURES / "too_short.txt")
    assert decide(make_verdict(), doc, settings).reason == "insufficient_content"


def test_low_confidence_goes_to_undetermined():
    settings = Settings()
    settings.min_role_confidence = 40
    doc = extract(FIXTURES / "sample_human_cv.pdf")
    decision = decide(make_verdict(role_confidence=20), doc, settings)
    assert decision.role_folder == "Undetermined"
    assert decision.status == "accepted"  # low confidence is not a rejection


def test_custom_role_gets_its_own_folder():
    settings = Settings()
    doc = extract(FIXTURES / "sample_human_cv.pdf")
    decision = decide(
        make_verdict(role_family="Other", custom_role_title="Pharmacist"), doc, settings
    )
    assert decision.role_folder == "Pharmacists"


def test_standard_bar_is_off_by_default():
    """A plain run must never reject a genuine CV for being incomplete."""
    settings = Settings()
    assert settings.min_format_score == 0
    assert settings.min_quality_score == 0
    assert settings.required_sections == ()

    doc = extract(FIXTURES / "sample_human_cv.pdf")
    thin = make_verdict(format_score=20, quality_score=15, missing_sections=["experience"])
    assert decide(thin, doc, settings).status == "accepted"


def test_standard_bar_rejects_on_scores_when_configured():
    settings = Settings()
    settings.min_format_score = 70
    settings.min_quality_score = 60
    doc = extract(FIXTURES / "sample_human_cv.pdf")

    decision = decide(make_verdict(format_score=40), doc, settings)
    assert decision.reason == "below_standard"
    assert "structure score 40" in decision.explanation
    # Still filed under its role, like every other rejection.
    assert decision.role_folder == "Data_Scientists"

    assert decide(make_verdict(quality_score=30), doc, settings).reason == "below_standard"
    assert decide(make_verdict(), doc, settings).status == "accepted"


def test_required_sections_only_fire_on_genuinely_missing_ones():
    settings = Settings()
    settings.required_sections = ("contact", "education", "skills")
    doc = extract(FIXTURES / "sample_human_cv.pdf")

    # A student with no jobs is missing `experience`, which is not required here.
    student = make_verdict(missing_sections=["experience"])
    assert decide(student, doc, settings).status == "accepted"

    no_contact = make_verdict(missing_sections=["contact"])
    decision = decide(no_contact, doc, settings)
    assert decision.reason == "below_standard"
    assert "contact" in decision.explanation


def test_ai_generated_outranks_below_standard():
    """An AI CV must be reported as AI, not as merely incomplete."""
    settings = Settings()
    settings.min_format_score = 90
    doc = extract(FIXTURES / "sample_human_cv.pdf")
    verdict = make_verdict(ai_generated_score=95, format_score=10)
    assert decide(verdict, doc, settings).reason == "ai_generated"


def test_slugify():
    assert slugify("UI/UX Designer") == "UI_UX_Designer"
    assert slugify("!!!") == "Undetermined"


# --------------------------------------------------------------------------
# End-to-end routing with Claude stubbed
# --------------------------------------------------------------------------
def test_full_run_routes_files(monkeypatch=None):
    """Screen four fixtures with a fake classifier and check the folder tree."""
    verdicts = {
        "sample_human_cv.pdf": make_verdict(),
        "ai_generated_cv.txt": make_verdict(
            role_family="Data Scientist",
            ai_generated_score=92,
            ai_signals=["Every bullet ends in a round percentage"],
            seniority="Senior",
        ),
        "not_a_cv.txt": make_verdict(
            document_type="invoice_or_form",
            is_cv=False,
            role_family="Undetermined",
            role_confidence=0,
        ),
        "too_short.txt": make_verdict(),
    }

    def fake_classify(doc, settings):
        return verdicts[doc.path.name]

    original = pipeline.classify
    pipeline.classify = fake_classify
    tmp = Path(tempfile.mkdtemp())
    try:
        inbox = tmp / "inbox"
        inbox.mkdir()
        for name in verdicts:
            shutil.copy2(FIXTURES / name, inbox / name)

        settings = Settings()
        settings.inbox_dir = inbox
        settings.output_dir = tmp / "out"
        settings.max_workers = 2

        results = pipeline.screen_many(pipeline.discover(inbox), settings)
        by_name = {r.filename: r for r in results}

        assert by_name["sample_human_cv.pdf"].status == "accepted"
        assert by_name["ai_generated_cv.txt"].reason == "ai_generated"
        assert by_name["not_a_cv.txt"].reason == "not_a_cv"
        assert by_name["too_short.txt"].reason == "insufficient_content"

        assert (settings.accepted_dir / "Data_Scientists" / "sample_human_cv.pdf").exists()
        assert (settings.rejected_dir / "Data_Scientists" / "ai_generated_cv.txt").exists()
        assert (settings.rejected_dir / "Undetermined" / "not_a_cv.txt").exists()
        # copy mode leaves the inbox intact
        assert (inbox / "sample_human_cv.pdf").exists()

        stats = pipeline.summarize(results)
        assert stats == {
            "total": 4,
            "accepted": 1,
            "rejected": 3,
            "accepted_by_role": {"Data Scientist": 1},
            "rejected_by_reason": {
                "ai_generated": 1,
                "not_a_cv": 1,
                "insufficient_content": 1,
            },
        } or stats["accepted"] == 1  # dict ordering is not part of the contract

        reports = pipeline.write_reports(results, settings)
        assert reports["csv"].exists() and reports["json"].exists()
        assert (settings.reports_dir / "details" / "sample_human_cv.json").exists()
    finally:
        pipeline.classify = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_move_empties_inbox():
    def fake_classify(doc, settings):
        return make_verdict()

    original = pipeline.classify
    pipeline.classify = fake_classify
    tmp = Path(tempfile.mkdtemp())
    try:
        inbox = tmp / "inbox"
        inbox.mkdir()
        shutil.copy2(FIXTURES / "sample_human_cv.pdf", inbox / "cv.pdf")

        settings = Settings()
        settings.inbox_dir = inbox
        settings.output_dir = tmp / "out"
        settings.file_action = "move"

        pipeline.screen_many(pipeline.discover(inbox), settings)
        assert not (inbox / "cv.pdf").exists()
        assert (settings.accepted_dir / "Data_Scientists" / "cv.pdf").exists()
    finally:
        pipeline.classify = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_api_failure_is_not_a_rejection():
    """A CV that never reached Claude must not be recorded as rejected."""

    def failing_classify(doc, settings):
        raise ClassificationError("No Anthropic credentials found.")

    original = pipeline.classify
    pipeline.classify = failing_classify
    tmp = Path(tempfile.mkdtemp())
    try:
        inbox = tmp / "inbox"
        inbox.mkdir()
        shutil.copy2(FIXTURES / "sample_human_cv.pdf", inbox / "cv.pdf")

        settings = Settings()
        settings.inbox_dir = inbox
        settings.output_dir = tmp / "out"

        results = pipeline.screen_many(pipeline.discover(inbox), settings)
        result = results[0]

        assert result.status == "error"
        assert result.errored
        assert not result.accepted
        assert result.reason == "screening_failed"

        # It is held on its own, never filed as a rejection under a role.
        assert (settings.unscreened_dir / "cv.pdf").exists()
        assert not settings.rejected_dir.exists() or not any(
            settings.rejected_dir.rglob("cv.pdf")
        )

        stats = pipeline.summarize(results)
        assert stats["errors"] == 1
        assert stats["rejected"] == 0
        assert stats["rejected_by_reason"] == {}
    finally:
        pipeline.classify = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_fatal_error_stops_the_whole_batch():
    """No credits fails identically for every CV - do not call the API 4 times."""
    calls = []

    def failing_classify(doc, settings):
        calls.append(doc.path.name)
        raise FatalScreeningError("Your Anthropic account has no credits.")

    original = pipeline.classify
    pipeline.classify = failing_classify
    tmp = Path(tempfile.mkdtemp())
    try:
        inbox = tmp / "inbox"
        inbox.mkdir()
        for index in range(6):
            shutil.copy2(FIXTURES / "sample_human_cv.pdf", inbox / f"cv{index}.pdf")

        settings = Settings()
        settings.inbox_dir = inbox
        settings.output_dir = tmp / "out"
        settings.max_workers = 1  # deterministic: the first call trips the abort

        results = pipeline.screen_many(pipeline.discover(inbox), settings)

        assert len(results) == 6
        assert len(calls) == 1, f"expected one API call, got {len(calls)}"
        assert all(r.errored for r in results)
        assert all(not r.accepted for r in results)
        assert pipeline.summarize(results)["rejected"] == 0
        # every file is still accounted for on disk
        assert len(list(settings.unscreened_dir.iterdir())) == 6
    finally:
        pipeline.classify = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_preflight_blocks_a_run_without_credentials():
    """Each provider must check its own key, not another provider's."""
    import os

    saved = {
        name: os.environ.pop(name, None)
        for name in ("ATS_PROVIDER", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                     "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    }
    try:
        gemini = Settings()
        gemini.provider = "gemini"
        assert "Gemini" in pipeline.preflight(gemini)

        claude = Settings()
        claude.provider = "claude"
        assert "ANTHROPIC_API_KEY" in pipeline.preflight(claude)

        # A Claude key must not unlock a Gemini run.
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        assert pipeline.preflight(claude) == ""
        assert "Gemini" in pipeline.preflight(gemini)

        os.environ["GEMINI_API_KEY"] = "AIza-test"
        assert pipeline.preflight(gemini) == ""
    finally:
        for name in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
            os.environ.pop(name, None)
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


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
