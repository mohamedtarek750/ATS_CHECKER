"""A batch that dies half way must not lose the half it finished.

Reproduces the real failure: 100 CVs uploaded, the browser connection drops after
50, and previously the whole run - including the 50 already paid for - was gone.

Run: python tests/test_resume.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import ledger, pipeline  # noqa: E402
from ats.classifier import FatalScreeningError  # noqa: E402
from ats.config import Settings  # noqa: E402
from ats.schema import Verdict  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def make_verdict(**overrides) -> Verdict:
    base = dict(
        document_type="cv_resume", is_cv=True, candidate_name="Test Person",
        email="t@example.com", phone="", role_family="Data Scientist",
        custom_role_title="", specialization="ML", major="DS", seniority="Junior",
        years_experience=1.0, top_skills=["Python"], role_confidence=90,
        ai_generated_score=10, ai_signals=[], human_signals=[],
        format_score=85, format_notes="fine", missing_sections=[],
        structure_issues=[], professionalism_score=90, professionalism_issues=[],
        quality_score=80, suggested_reject_reason="none", reasoning="ok",
    )
    base.update(overrides)
    return Verdict(**base)


def build_inbox(count: int) -> tuple[Path, Settings]:
    tmp = Path(tempfile.mkdtemp())
    inbox = tmp / "inbox"
    inbox.mkdir()
    for i in range(count):
        shutil.copy2(FIXTURES / "sample_human_cv.pdf", inbox / f"cv_{i:03d}.pdf")
    settings = Settings()
    settings.inbox_dir = inbox
    settings.output_dir = tmp / "out"
    settings.max_workers = 1
    return tmp, settings


def test_interrupted_run_keeps_what_it_finished():
    """Kill the run at CV 4 of 10, then re-run: only 6 should be screened."""
    calls: list[str] = []

    def dies_after_four(doc, settings):
        calls.append(doc.path.name)
        if len(calls) > 4:
            raise KeyboardInterrupt("browser connection dropped")
        return make_verdict()

    tmp, settings = build_inbox(10)
    original = pipeline.classify
    pipeline.classify = dies_after_four
    try:
        try:
            pipeline.screen_many(pipeline.discover(settings.inbox_dir), settings)
        except KeyboardInterrupt:
            pass

        # The four that completed are on disk, not lost with the run.
        done = ledger.load_done(settings)
        assert len(done) == 4, f"expected 4 recorded, got {len(done)}"

        # Re-run: the finished four are not screened again.
        second: list[str] = []

        def counting(doc, s):
            second.append(doc.path.name)
            return make_verdict()

        pipeline.classify = counting
        results = pipeline.screen_many(
            pipeline.discover(settings.inbox_dir), settings
        )

        assert len(second) == 6, f"expected 6 new calls, got {len(second)}"
        assert len(results) == 10, "the report still covers all ten"
        assert len(ledger.load_done(settings)) == 10
    finally:
        pipeline.classify = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_failed_cvs_are_retried_not_treated_as_done():
    """A CV that failed on a spent quota has not been screened."""
    tmp, settings = build_inbox(3)
    original = pipeline.classify
    pipeline.classify = lambda doc, s: (_ for _ in ()).throw(
        FatalScreeningError("daily quota spent")
    )
    try:
        pipeline.screen_many(pipeline.discover(settings.inbox_dir), settings)
        assert ledger.load_done(settings) == {}, "errors must not count as done"

        calls: list[str] = []

        def works(doc, s):
            calls.append(doc.path.name)
            return make_verdict()

        pipeline.classify = works
        pipeline.screen_many(pipeline.discover(settings.inbox_dir), settings)
        assert len(calls) == 3, "all three retried once the quota is back"
    finally:
        pipeline.classify = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_restart_ignores_the_ledger():
    tmp, settings = build_inbox(3)
    original = pipeline.classify
    pipeline.classify = lambda doc, s: make_verdict()
    try:
        pipeline.screen_many(pipeline.discover(settings.inbox_dir), settings)

        calls: list[str] = []

        def counting(doc, s):
            calls.append(doc.path.name)
            return make_verdict()

        pipeline.classify = counting
        pipeline.screen_many(
            pipeline.discover(settings.inbox_dir), settings, resume=False
        )
        assert len(calls) == 3, "--restart re-screens everything"
    finally:
        pipeline.classify = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_dry_run_never_writes_to_the_ledger():
    """A rehearsal must not make the real run skip files."""
    tmp, settings = build_inbox(3)
    settings.dry_run = True
    original = pipeline.classify
    pipeline.classify = lambda doc, s: make_verdict()
    try:
        pipeline.screen_many(pipeline.discover(settings.inbox_dir), settings)
        assert ledger.load_done(settings) == {}
    finally:
        pipeline.classify = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_replaced_file_is_screened_again():
    """Same name, different content: the candidate sent a new version."""
    tmp, settings = build_inbox(1)
    original = pipeline.classify
    pipeline.classify = lambda doc, s: make_verdict()
    try:
        pipeline.screen_many(pipeline.discover(settings.inbox_dir), settings)
        target = settings.inbox_dir / "cv_000.pdf"
        assert ledger.key_for(target) in ledger.load_done(settings)

        target.write_bytes(target.read_bytes() + b"a different, longer version")
        assert ledger.key_for(target) not in ledger.load_done(settings)
    finally:
        pipeline.classify = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_half_written_ledger_line_is_skipped():
    """A killed process can leave a truncated line. It must not break the resume."""
    tmp, settings = build_inbox(2)
    original = pipeline.classify
    pipeline.classify = lambda doc, s: make_verdict()
    try:
        pipeline.screen_many(pipeline.discover(settings.inbox_dir), settings)
        path = ledger.ledger_path(settings)
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"filename": "truncated", "sta')

        done = ledger.load_done(settings)
        assert len(done) == 2, "the two good rows still load"
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
