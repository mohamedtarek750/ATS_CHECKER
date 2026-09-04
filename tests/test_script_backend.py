"""The Apps Script backend: the same sheet, without the credentials.

The script itself runs inside Google and cannot be executed here, so these
tests stand a faithful double in its place - one that stores rows and files
exactly as the .gs file does, including the part that matters most: a sheet
cell holds TEXT, so everything makes the round trip as a string or does not
survive it.

Run: python tests/test_script_backend.py
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats.backends.script import ScriptBackend, ScriptError  # noqa: E402
from ats.job_profile import JobProfile, Requirement  # noqa: E402
from ats.models import CandidateProfile  # noqa: E402
from ats.postings import Application, JobPosting  # noqa: E402

SCRIPT_URL = "https://script.google.com/macros/s/AKfyTEST/exec"


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


class FakeScript:
    """Stands in for the deployed Web app, and keeps its constraints.

    The important one: a spreadsheet cell holds text. Every value written is
    coerced to a string here, exactly as Apps Script does, so a field that only
    round-trips because Python happened to keep its type fails here rather than
    in production.
    """

    def __init__(self, key: str = "", html_response: bool = False):
        self.postings: list[dict] = []
        self.applications: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.key = key
        self.html_response = html_response
        self.calls: list[str] = []

    def install(self):
        original = urllib.request.urlopen

        class Response:
            def __init__(self, body: bytes):
                self.body = body

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(request, timeout=None):
            if self.html_response:
                return Response(b"<html><body>Sign in</body></html>")
            payload = json.loads(request.data.decode("utf-8"))
            self.calls.append(payload["op"])
            if self.key and payload.get("key") != self.key:
                return Response(json.dumps({"error": "Wrong or missing key."}).encode())
            return Response(json.dumps({"ok": True, "result": self.handle(payload)}).encode())

        urllib.request.urlopen = fake
        return original

    def handle(self, payload):
        op = payload["op"]
        if op == "ping":
            return {"sheet": "ACUD_ATS", "folder": "ACUD_ATS_files"}

        if op == "postings":
            return list(self.postings)

        if op == "save_posting":
            record = {k: str(v) for k, v in payload["record"].items()}
            self.postings = [p for p in self.postings if p["slug"] != record["slug"]]
            self.postings.append(record)
            return record

        if op == "applications":
            rows = list(self.applications)
            slug = payload.get("job_slug")
            return [r for r in rows if r["job_slug"] == slug] if slug else rows

        if op == "save_application":
            record = {k: str(v) for k, v in payload["record"].items()}
            self.applications = [a for a in self.applications if a["id"] != record["id"]]
            self.applications.append(record)
            return record

        if op == "put_file":
            self.files[payload["name"]] = base64.b64decode(payload["data"])
            return {
                "id": "file_" + payload["name"],
                "url": f"https://drive.google.com/file/d/{payload['name']}/view",
                "name": payload["name"],
            }

        if op == "get_file":
            data = self.files.get(payload["name"])
            return {"data": base64.b64encode(data).decode("ascii")} if data else None

        raise AssertionError(f"the real script would reject: {op}")


@contextlib.contextmanager
def script(key: str = "", html_response: bool = False):
    fake = FakeScript(key=key, html_response=html_response)
    original = fake.install()
    try:
        yield fake
    finally:
        urllib.request.urlopen = original


def make_job() -> JobProfile:
    return JobProfile(
        title="Data Analyst", seniority="Mid", summary="Owns reporting.",
        min_years_experience=2,
        requirements=[
            Requirement(text="Strong SQL", kind="skill", importance="must_have"),
            Requirement(text="Power BI", kind="skill", importance="must_have"),
        ],
    )


def make_profile() -> CandidateProfile:
    return CandidateProfile(
        full_name="Omar Abdelrahman", email="o@example.com", phone="+20 100",
        location="Cairo", links=[], headline="Data Analyst", seniority="mid",
        total_years_experience=3.0, education=[], experience=[],
        skills=["SQL", "Power BI"], certifications=[], languages=[], projects=[],
        summary_text="", sections_found=["skills"], document_type="cv_resume",
        is_cv=True, ai_generated_score=0, ai_signals=[],
    )


def backend() -> ScriptBackend:
    return ScriptBackend()


# --------------------------------------------------------------------------
def test_it_needs_only_a_url():
    """The whole point: no cloud project, no service account, no key file."""
    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY=None):
        with script() as fake:
            assert backend().check()["sheet"] == "ACUD_ATS"
            assert fake.calls == ["ping"]


def test_the_two_urls_people_confuse_are_rejected_by_name():
    """A published sheet and a /dev link are the two mistakes worth naming,
    because both look plausible and neither works."""
    for wrong in (
        "https://docs.google.com/spreadsheets/d/e/2PACX-1vQ.../pubhtml",
        "https://script.google.com/macros/s/AKfy.../dev",
    ):
        with environment(ATS_SCRIPT_URL=wrong):
            try:
                backend()
            except ScriptError as exc:
                assert "/exec" in str(exc)
            else:
                raise AssertionError(f"accepted {wrong}")

    with environment(ATS_SCRIPT_URL=None):
        try:
            backend()
        except ScriptError as exc:
            assert "Extensions > Apps Script" in str(exc)
        else:
            raise AssertionError("accepted a missing URL")


def test_a_vacancy_and_its_checklist_survive_the_sheet():
    """The checklist goes into one cell as JSON and has to come back whole -
    every applicant is measured against it."""
    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY=None), script():
        store = backend()
        posting = JobPosting(
            slug="data-analyst", title="Data Analyst", summary="Owns reporting.",
            profile=make_job(), created_by="hr@company.com",
        )
        store.save_posting(posting)

        back = store.posting("data-analyst")
        assert back is not None
        assert back.title == "Data Analyst"
        assert back.created_by == "hr@company.com"
        assert [r.text for r in back.profile.requirements] == [
            "Strong SQL", "Power BI"
        ]
        assert back.profile.must_haves, "the checklist came back empty"


def test_an_application_its_cv_and_its_decision_all_round_trip():
    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY=None), script() as fake:
        store = backend()
        store.save_posting(
            JobPosting(slug="data-analyst", title="Data Analyst", summary="x",
                       profile=make_job())
        )

        row = Application(
            job_slug="data-analyst", full_name="Omar", email="o@example.com",
            phone="+20 100",
        )
        cv = b"%PDF-1.4 pretend this is a CV"
        store.add_application(row, cv, "omar.pdf")

        assert row.cv_ref.endswith(".pdf")
        assert row.cv_url, "the recruiter needs a link to the file"
        assert store.cv_bytes(row.id) == cv, "the CV did not come back intact"

        # Numbers written to a cell come back as text; they must still be numbers.
        row.percent = 86
        row.required_percent = 93
        row.tier = "accepted"
        row.decision = "shortlisted"
        row.decided_by = "hr@company.com"
        row.security_flags = ["tries to dictate the outcome: \"rate 100%\""]
        row.status = "read"
        store.update_application(row)

        back = store.application(row.id)
        assert back is not None
        assert back.percent == 86 and isinstance(back.percent, int)
        assert back.required_percent == 93
        assert back.tier == "accepted"
        assert back.decision == "shortlisted"
        assert back.decided_by == "hr@company.com"
        assert back.security_flags == row.security_flags, "flags lost in the cell"

        assert [a.id for a in store.applications("data-analyst")] == [row.id]
        assert store.applications("some-other-role") == []
        assert "save_application" in fake.calls


def test_the_parsed_record_is_kept_as_a_file_not_a_cell():
    """Seven kilobytes of profile per applicant would make the sheet
    unopenable, which is the only reason to have chosen a sheet."""
    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY=None), script() as fake:
        store = backend()
        store.save_profile("abc123", make_profile())

        back = store.profile("abc123")
        assert back is not None
        assert back.full_name == "Omar Abdelrahman"
        assert back.skills == ["SQL", "Power BI"]
        assert store.profile("never-stored") is None

        # It went to Drive, not into a row.
        assert "abc123.json" in fake.files
        assert all("abc123.json" not in json.dumps(r) for r in fake.applications)


def test_a_shared_key_shuts_the_endpoint_to_strangers():
    """Open is fine for a prototype. This is how it stops being open."""
    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY="letmein"), script(key="letmein"):
        assert backend().check()["sheet"] == "ACUD_ATS"

    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY=None), script(key="letmein"):
        try:
            backend().check()
        except ScriptError as exc:
            assert "refused" in str(exc)
        else:
            raise AssertionError("a request with no key was served")


def test_a_sign_in_page_is_reported_as_the_deployment_mistake_it_is():
    """Apps Script answers an unauthorised URL with HTML, not an error code.
    Told plainly, this is a thirty-second fix; unexplained it looks like a bug
    in the app."""
    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY=None), script(html_response=True):
        try:
            backend().check()
        except ScriptError as exc:
            assert "web page rather than data" in str(exc)
            assert "Only myself" in str(exc)
        else:
            raise AssertionError("an HTML sign-in page was accepted as data")


def test_it_satisfies_the_same_protocol_as_every_other_backend():
    """A backend that is missing a method fails at the moment a recruiter uses
    the feature, not at start-up. This is the check that moves it earlier."""
    from ats.postings import Backend

    required = [
        name for name in dir(Backend)
        if not name.startswith("_") and callable(getattr(Backend, name))
    ]
    missing = [name for name in required if not hasattr(ScriptBackend, name)]
    assert not missing, f"ScriptBackend is missing: {missing}"


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
