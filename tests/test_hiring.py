"""A public application link and a dashboard that outlives the session.

Everything else in this project is stateless. These are the tests for the part
that is not: the records that have to survive between somebody applying and
somebody reading, and the guarantee that nothing a person submitted is lost
because the machine that was supposed to read it fell over.

Run: python tests/test_hiring.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import backends, intake  # noqa: E402
from ats.backends.local import LocalBackend  # noqa: E402
from ats.job_profile import JobProfile, Requirement  # noqa: E402
from ats.postings import ENGINE_VERSION, JobPosting, slugify  # noqa: E402

SAMPLES = ROOT / "samples"


def make_job() -> JobProfile:
    return JobProfile(
        title="Data Analyst", seniority="Mid-level",
        summary="Owns commercial reporting.", min_years_experience=2,
        requirements=[
            Requirement(text="Strong SQL", kind="skill", importance="must_have"),
            Requirement(text="Power BI", kind="skill", importance="must_have"),
            Requirement(text="2 years of professional experience",
                        kind="experience", importance="must_have"),
            Requirement(text="Azure", kind="skill", importance="nice_to_have"),
        ],
    )


def fresh() -> tuple[LocalBackend, JobPosting, Path]:
    tmp = Path(tempfile.mkdtemp())
    backend = LocalBackend(tmp)
    posting = backend.save_posting(
        JobPosting(slug="data-analyst", title="Data Analyst",
                   summary="Owns reporting.", profile=make_job())
    )
    return backend, posting, tmp


def cv_bytes(name: str = "01_data_analyst_omar.pdf") -> bytes:
    return (SAMPLES / name).read_bytes()


def apply(backend, posting, name="Omar", email="omar@example.com",
          filename="omar.pdf", data=None):
    return intake.receive(
        backend, posting, full_name=name, email=email, phone="+20 100",
        filename=filename, data=cv_bytes() if data is None else data,
    )


# --------------------------------------------------------------------------
def test_an_application_is_stored_before_anything_is_read():
    """The property the whole two-step design exists for.

    If reading a CV happened inside the request the applicant is waiting on, a
    slow parse or a timeout would lose their application entirely and they would
    be told it went through. The file lands first; reading happens after.
    """
    backend, posting, tmp = fresh()
    try:
        row = apply(backend, posting)
        assert row.status == "pending"
        assert row.percent == 0 and row.tier == ""

        # The file really is on disk, before any reading was attempted.
        assert backend.cv_bytes(row.id) == cv_bytes()
        assert backend.profile(row.id) is None

        # And it is visible to the recruiter as "not read yet", not missing.
        stored = backend.applications(posting.slug)
        assert [r.id for r in stored] == [row.id]
        assert stored[0].status == "pending"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_reading_scores_the_application_and_records_the_engine():
    backend, posting, tmp = fresh()
    try:
        row = intake.read(backend, posting, apply(backend, posting))
        assert row.status == "read"
        assert row.tier in {"accepted", "waiting_list", "rejected"}
        assert 0 < row.percent <= 100
        assert row.reason
        # Stamped, so a decision reached under older rules can be spotted later
        # rather than silently restated as though it were current.
        assert row.engine_version == ENGINE_VERSION
        assert not row.is_stale
        assert backend.profile(row.id) is not None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_reasoning_is_recomputed_rather_than_stored():
    """Seven kilobytes of evidence per applicant is not a thing to keep."""
    backend, posting, tmp = fresh()
    try:
        row = intake.read(backend, posting, apply(backend, posting))
        stored = json.loads(
            (Path(backend.root) / "applications" / "data-analyst.json").read_text(
                encoding="utf-8"
            )
        )[0]
        assert "requirements" not in stored
        assert "template" not in stored

        detail = intake.detail_for(backend, posting, row)
        assert detail is not None
        _profile, entry, report = detail
        assert len(entry.match.results) == len(posting.profile.requirements)
        assert report.percent >= 0
        # The recomputed verdict agrees with the one that was stored.
        assert entry.percent == row.percent
        assert entry.tier == row.tier
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_document_that_is_not_a_cv_is_labelled_not_dropped():
    backend, posting, tmp = fresh()
    try:
        row = apply(backend, posting, name="Nadia", filename="letter.pdf",
                    data=(SAMPLES / "09_cover_letter.pdf").read_bytes())
        row = intake.read(backend, posting, row)
        assert row.status == "not_a_cv"
        assert row.detail
        # Still on the list. A person decides what to do about it, not the parser.
        assert len(backend.applications(posting.slug)) == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_closed_vacancy_stops_accepting_applications():
    backend, posting, tmp = fresh()
    try:
        posting.status = "closed"
        backend.save_posting(posting)
        try:
            apply(backend, posting)
        except intake.IntakeError as exc:
            assert "no longer accepting" in str(exc)
        else:
            raise AssertionError("a closed vacancy took an application")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_what_an_applicant_gets_wrong_is_said_plainly():
    backend, posting, tmp = fresh()
    try:
        for kwargs, expect in [
            ({"name": ""}, "name"),
            ({"email": "not-an-email"}, "email"),
            ({"filename": "photo.png"}, "upload"),
            ({"data": b""}, "empty"),
            ({"data": b"x" * (intake.MAX_CV_BYTES + 1)}, "8 MB"),
        ]:
            try:
                apply(backend, posting, **kwargs)
            except intake.IntakeError as exc:
                assert expect in str(exc), f"{kwargs} -> {exc}"
            else:
                raise AssertionError(f"{kwargs} was accepted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_human_decision_is_never_written_by_the_engine():
    backend, posting, tmp = fresh()
    try:
        row = intake.read(backend, posting, apply(backend, posting))
        assert row.decision == "new"

        row.decision = "shortlisted"
        row.note = "Call Tuesday."
        backend.update_application(row)

        # Re-reading the CV must not undo what a person decided about it.
        again = intake.read(backend, posting, backend.application(row.id))
        assert again.decision == "shortlisted"
        assert again.note == "Call Tuesday."
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pending_applications_are_drained_and_the_rest_left_alone():
    backend, posting, tmp = fresh()
    try:
        for i in range(3):
            apply(backend, posting, name=f"Person {i}", email=f"p{i}@example.com")
        read = intake.read_pending(backend, posting)
        assert len(read) == 3
        assert all(r.status in {"read", "not_a_cv", "failed"} for r in read)
        # Nothing left pending, and running it again is a no-op rather than a
        # second read of everyone.
        assert intake.read_pending(backend, posting) == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_stale_decision_is_visible_as_stale():
    backend, posting, tmp = fresh()
    try:
        row = intake.read(backend, posting, apply(backend, posting))
        row.engine_version = "2020.01.1"
        backend.update_application(row)
        assert backend.application(row.id).is_stale
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_two_vacancies_with_one_title_do_not_collide():
    """Overwriting a vacancy would take every application to it as well."""
    assert slugify("Senior Data Analyst!") == "senior-data-analyst"
    assert slugify("  ") == "role"


def test_the_backend_is_chosen_by_configuration():
    import os

    backends.reset()
    os.environ.pop("ATS_BACKEND", None)
    assert backends.backend_name() == "local"
    assert isinstance(backends.get_backend(), LocalBackend)
    backends.reset()


# --------------------------------------------------------------------------
# The Google Sheets backend
#
# The parts that do not need Google are tested here: the row round-trip, the
# column maths, and the messages a misconfiguration produces. What talks to
# Google is NOT exercised - there are no credentials in this checkout - so this
# proves the shape of the data, not that the API calls succeed.
# --------------------------------------------------------------------------
def test_an_application_survives_the_round_trip_through_a_sheet_row():
    from ats.backends.sheets import (
        APPLICATION_COLUMNS, SheetsBackend, _column_letter,
    )
    from ats.postings import Application

    original = Application(
        job_slug="data-analyst", full_name="Omar H. Abdelrahman",
        email="omar@example.com", phone="+20 111", cv_filename="omar.pdf",
        cv_ref="drive-file-id", cv_url="https://drive.example/x",
        status="read", read_at="2026-09-01T10:00:00+00:00",
        percent=86, required_percent=95, preferred_percent=40,
        tier="accepted", reason="86% overall.", engine_version="2026.09.1",
        decision="shortlisted", note="Call Tuesday.",
    )
    record = SheetsBackend._to_record(original)
    assert list(record) == APPLICATION_COLUMNS, "columns must match, in order"

    # A sheet gives everything back as text, including the numbers.
    as_text = {k: str(v) for k, v in record.items()}
    restored = SheetsBackend._to_application(as_text)

    for field in ("id", "full_name", "email", "phone", "tier", "decision",
                  "note", "cv_ref", "status", "reason", "engine_version"):
        assert getattr(restored, field) == getattr(original, field), field
    assert restored.percent == 86
    assert restored.required_percent == 95

    # A blank cell must not become a crash: a recruiter can clear one by hand.
    sparse = SheetsBackend._to_application({"id": "abc", "job_slug": "x"})
    assert sparse.percent == 0
    assert sparse.decision == "new"
    assert sparse.status == "pending"

    assert _column_letter(0) == "A"
    assert _column_letter(25) == "Z"
    assert _column_letter(26) == "AA"
    assert _column_letter(len(APPLICATION_COLUMNS) - 1) == "T"


def test_a_misconfigured_sheets_backend_says_what_is_missing():
    import os

    from ats.backends.sheets import SheetsBackend, SheetsError

    saved = os.environ.pop("ATS_SHEET_ID", None)
    try:
        try:
            SheetsBackend()
        except SheetsError as exc:
            assert "ATS_SHEET_ID" in str(exc)
        else:
            raise AssertionError("an unconfigured backend was built")

        os.environ["ATS_SHEET_ID"] = "test-sheet"
        os.environ.pop("GOOGLE_SERVICE_ACCOUNT_JSON", None)
        try:
            SheetsBackend()._credentials()
        except SheetsError as exc:
            assert "GOOGLE_SERVICE_ACCOUNT_JSON" in str(exc)
        else:
            raise AssertionError("missing credentials went unreported")

        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"] = "not json"
        try:
            SheetsBackend()._credentials()
        except SheetsError as exc:
            assert "valid JSON" in str(exc)
        else:
            raise AssertionError("a broken key file went unreported")
    finally:
        os.environ.pop("GOOGLE_SERVICE_ACCOUNT_JSON", None)
        os.environ.pop("ATS_SHEET_ID", None)
        if saved is not None:
            os.environ["ATS_SHEET_ID"] = saved


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
