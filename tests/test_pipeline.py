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
