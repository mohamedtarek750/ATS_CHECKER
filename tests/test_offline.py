"""The no-model path: rules only, so a large intake is never blocked by a quota.

Run: python tests/test_offline.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import screening, store  # noqa: E402
from ats.config import PROVIDER_NAMES, Settings  # noqa: E402
from ats.pipeline import preflight  # noqa: E402
from ats.stages import offline, parse  # noqa: E402

SAMPLES = ROOT / "samples"


def offline_settings(tmp: Path) -> Settings:
    saved = os.environ.get("ATS_PROVIDER")
    os.environ["ATS_PROVIDER"] = "offline"
    try:
        settings = Settings()
    finally:
        if saved is None:
            os.environ.pop("ATS_PROVIDER", None)
        else:
            os.environ["ATS_PROVIDER"] = saved
    settings.provider = "offline"
    settings.output_dir = tmp
    return settings


def profile_for(name: str):
    return offline.extract_profile(parse.parse_one(SAMPLES / name))


# --------------------------------------------------------------------------
# It must never be the reason a run stops
# --------------------------------------------------------------------------
def test_offline_needs_no_credentials():
    """The whole point: no key, so no quota, so no batch dies half way."""
    tmp = Path(tempfile.mkdtemp())
    try:
        assert "offline" in PROVIDER_NAMES
        assert preflight(offline_settings(tmp)) == ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_offline_works_with_every_api_key_removed():
    tmp = Path(tempfile.mkdtemp())
    saved = {
        name: os.environ.pop(name, None)
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY")
    }
    try:
        settings = offline_settings(tmp)
        report = screening.intake([SAMPLES / "01_data_analyst_omar.pdf"], settings)
        assert report.added == 1
        assert report.failed == 0
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# What it actually extracts
# --------------------------------------------------------------------------
def test_it_finds_the_things_matching_depends_on():
    profile = profile_for("01_data_analyst_omar.pdf")

    assert profile.is_cv
    assert profile.document_type == "cv_resume"
    assert "Omar" in profile.full_name
    assert profile.email == "omar.abdelrahman.data@example.com"
    assert profile.phone
    assert profile.total_years_experience > 0

    # The skills vocabulary is the part stages 4 and 5 consume, and the part
    # rules do as well as a model - it is lookup, not comprehension.
    for skill in ("SQL", "Power BI", "Excel", "Power Query"):
        assert skill in profile.skills, f"{skill} not found in {profile.skills}"

    assert any(e.degree == "bachelor" for e in profile.education)
    assert any("english" in language.lower() for language in profile.languages)


def test_skills_are_found_outside_the_skills_section():
    """A tool used in a project counts, so a modest CV is not penalised."""
    profile = profile_for("03_backend_youssef.docx")
    assert "Django" in profile.skills or "FastAPI" in profile.skills
    assert "Docker" in profile.skills


def test_non_cvs_are_recognised_without_a_model():
    assert not profile_for("09_cover_letter.pdf").is_cv
    assert profile_for("09_cover_letter.pdf").document_type == "cover_letter"

    posting = profile_for("11_job_posting.txt")
    assert not posting.is_cv
    assert posting.document_type == "job_description"

    certificate = profile_for("10_certificate.txt")
    assert not certificate.is_cv


def test_it_never_claims_to_detect_ai_writing():
    """Rules cannot judge prose. Reporting a number would be inventing one."""
    profile = profile_for("07_ai_generated_data_scientist.pdf")
    assert profile.ai_generated_score == 0
    assert profile.ai_signals == []


def test_concurrent_roles_are_not_counted_twice():
    """Two overlapping jobs are not six years of experience."""
    from ats.stages.offline import _experience

    sections = {
        "experience": (
            "Data Analyst - Alpha (2020 - 2023)\n"
            "Consultant - Beta (2021 - 2023)\n"
        )
    }
    _entries, years = _experience(sections)
    assert 2.5 <= years <= 3.5, f"overlapping ranges gave {years} years"


def test_internships_do_not_count_as_professional_years():
    from ats.stages.offline import _experience

    only_intern = {"experience": "Data Intern - Alpha (2020 - 2022)\n"}
    _entries, years = _experience(only_intern)
    assert years == 0.0


# --------------------------------------------------------------------------
# Speed - the reason this path exists
# --------------------------------------------------------------------------
def test_every_file_reports_its_own_outcome():
    """A scan must say what happened to each file, not just how many succeeded."""
    tmp = Path(tempfile.mkdtemp())
    settings = offline_settings(tmp)
    seen = []
    try:
        report = screening.intake(
            [
                SAMPLES / "01_data_analyst_omar.pdf",
                SAMPLES / "09_cover_letter.pdf",
                SAMPLES / "11_job_posting.txt",
            ],
            settings,
            on_progress=lambda event, done, total: seen.append(event),
        )

        assert len(seen) == 3, "one event per file, as it finishes"
        assert len(report.events) == 3, "and kept on the report afterwards"

        by_file = {e.filename: e for e in report.events}
        cv = by_file["01_data_analyst_omar.pdf"]
        assert cv.status == "added"
        assert "Omar" in cv.name
        assert cv.summary, "an added CV says who it is"

        letter = by_file["09_cover_letter.pdf"]
        assert letter.status == "not_a_cv"
        assert "cover letter" in letter.summary

        # Every event renders a line a terminal can print.
        for event in report.events:
            assert event.filename in event.line()
            assert event.label.strip()
    finally:
        store.close_all()
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_failed_file_says_why_next_to_its_name():
    from ats.screening import IntakeEvent

    event = IntakeEvent("broken.pdf", "failed", detail="daily quota is used up")
    assert "broken.pdf" in event.line()
    assert "quota" in event.line()
    assert event.label == "FAIL"


def test_a_large_intake_is_fast_and_free():
    tmp = Path(tempfile.mkdtemp())
    inbox = tmp / "inbox"
    inbox.mkdir()
    # Genuinely different people. Appending bytes to a PDF would not do it: the
    # pool is keyed on extracted text, so identical CVs correctly collapse to one.
    template = "\n".join([
        "PERSON {i}",
        "Cairo, Egypt | +20 100 000 {i:04d} | person{i}@example.com",
        "",
        "EXPERIENCE",
        "Data Analyst - Company {i} (2021 - present)",
        "",
        "EDUCATION",
        "Bachelor of Statistics, Cairo University, 2020",
        "",
        "SKILLS",
        "SQL, Power BI, Excel, Power Query, Python",
        "",
        "LANGUAGES",
        "Arabic (native), English (fluent)",
    ])
    for i in range(40):
        (inbox / f"cv_{i:03d}.txt").write_text(template.format(i=i), encoding="utf-8")

    settings = offline_settings(tmp / "out")
    try:
        started = time.perf_counter()
        report = screening.intake(parse.discover(inbox), settings)
        elapsed = time.perf_counter() - started

        assert report.added == 40
        assert report.failed == 0
        per_cv = elapsed / 40
        assert per_cv < 1.0, f"{per_cv*1000:.0f} ms per CV is too slow for this path"
        assert store.stats(settings)["total"] == 40
    finally:
        store.close_all()
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
