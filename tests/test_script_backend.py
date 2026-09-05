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

from ats import notify  # noqa: E402
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
        self.mail: list[dict] = []
        self.schedule = {
            "enabled": False, "hour": None, "timezone": "Africa/Cairo", "url": "",
        }
        self.cron_secret = ""
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

        if op == "delete_posting":
            slug = payload["slug"]
            going = [a for a in self.applications if a["job_slug"] == slug]
            for row in going:
                for name in (row.get("cv_ref"), row["id"] + ".json"):
                    self.files.pop(name, None)
            self.applications = [
                a for a in self.applications if a["job_slug"] != slug
            ]
            self.postings = [p for p in self.postings if p["slug"] != slug]
            return {"slug": slug, "applications": len(going)}

        if op == "send_mail":
            # The real script refuses this without a key, and so does the
            # double - the rule is the point of the operation, not a detail.
            if not self.key:
                raise AssertionError(
                    "the real script would refuse send_mail with no SHARED_KEY"
                )
            self.mail.append(payload)
            return {"sent": 1, "to": payload["to"], "remaining": 99}

        if op == "get_schedule":
            return dict(self.schedule)

        if op == "set_schedule":
            if not self.key:
                raise AssertionError(
                    "the real script would refuse set_schedule with no SHARED_KEY"
                )
            hour = int(payload["hour"])
            if not 0 <= hour <= 23:
                raise AssertionError("the real script would reject that hour")
            self.schedule = {
                "enabled": True, "hour": hour,
                "timezone": "Africa/Cairo", "url": payload["url"],
            }
            self.cron_secret = payload.get("secret", "")
            return dict(self.schedule)

        if op == "clear_schedule":
            self.schedule = {
                "enabled": False, "hour": None,
                "timezone": "Africa/Cairo", "url": self.schedule.get("url", ""),
            }
            return dict(self.schedule)

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


def test_deleting_a_posting_takes_its_applications_and_files():
    """One call, not a loop from the caller.

    Apps Script is slow enough that a delete built as "read all, then one
    request per row" would time out on a vacancy with any real number of
    applicants. The backend asks for the whole job to go and the script does
    the walking.
    """
    with script() as fake, environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY=None):
        backend = ScriptBackend()
        backend.save_posting(
            JobPosting(slug="data-analyst", title="Data Analyst", summary="",
                       profile=make_job())
        )
        backend.save_posting(
            JobPosting(slug="kept", title="Kept", summary="", profile=make_job())
        )
        backend.add_application(
            Application(id="a1", job_slug="data-analyst", full_name="Omar",
                        email="o@e.com", phone=""),
            b"%PDF-1.4 cv", "omar.pdf",
        )
        backend.add_application(
            Application(id="a2", job_slug="kept", full_name="Sara",
                        email="s@e.com", phone=""),
            b"%PDF-1.4 cv", "sara.pdf",
        )

        removed = backend.delete_posting("data-analyst")
        assert removed == 1
        assert [p.slug for p in backend.postings()] == ["kept"]
        assert backend.applications("data-analyst") == []
        assert "a1.pdf" not in fake.files

        # And the vacancy next to it is untouched, file included.
        assert len(backend.applications("kept")) == 1
        assert backend.cv_bytes("a2") == b"%PDF-1.4 cv"


def test_the_script_can_send_mail_as_the_sheets_owner():
    """The whole appeal: no API key, no domain, no App Password.

    The script already runs as the person who owns the spreadsheet, so it can
    send as them. This is the same mechanism a Google Sheets booking form uses
    to email a confirmation.
    """
    with script(key="s3cret") as fake, environment(
        ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY="s3cret"
    ):
        result = ScriptBackend().send_mail(
            to="malak@example.com",
            subject="4 critical workforce alerts",
            text="plain",
            html="<p>rich</p>",
            name="ACUD Careers",
        )

    assert result["sent"] == 1
    assert len(fake.mail) == 1
    assert fake.mail[0]["to"] == "malak@example.com"
    assert fake.mail[0]["subject"] == "4 critical workforce alerts"
    assert fake.mail[0]["html"] == "<p>rich</p>"
    assert fake.mail[0]["name"] == "ACUD Careers"


def test_notify_routes_through_the_script_when_that_is_all_there_is():
    with script(key="s3cret") as fake, environment(
        ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY="s3cret",
        RESEND_API_KEY=None, ATS_SMTP_HOST=None,
        ATS_MAIL_FROM="ACUD Careers <careers@acud.eg>",
    ):
        assert notify.transport() == "script"
        result = notify.send("malak@example.com", "Subject", "text", "<p>html</p>")

    assert result.ok, result.detail
    assert len(fake.mail) == 1
    # ATS_MAIL_FROM cannot change who it comes from - the script sends as its
    # owner - but the display name and reply-to are still worth carrying.
    assert fake.mail[0]["name"] == "ACUD Careers"
    assert fake.mail[0]["replyTo"] == "careers@acud.eg"


def test_mail_through_the_script_is_refused_without_a_shared_key():
    """An unkeyed Web app answers whoever holds the URL.

    That is a fair trade for a sheet of test data. It is not a fair trade for
    sending mail, because an open send endpoint is an open relay running on a
    real person's Gmail, on their quota, in their name.
    """
    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY=None,
                     RESEND_API_KEY=None, ATS_SMTP_HOST=None):
        assert not notify.script_mail_ready()
        assert notify.transport() == "none"

    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY="s3cret",
                     RESEND_API_KEY=None, ATS_SMTP_HOST=None):
        assert notify.script_mail_ready()


def test_a_transport_named_but_not_configured_sends_nothing():
    """Falling back silently would mean mail leaving by a route somebody
    deliberately did not pick."""
    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY="s3cret",
                     ATS_MAIL_TRANSPORT="resend", RESEND_API_KEY=None):
        assert notify.transport() == "none"

    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY="s3cret",
                     ATS_MAIL_TRANSPORT="script"):
        assert notify.transport() == "script"


def test_the_digest_goes_out_one_message_per_person_through_the_script():
    from ats.alerts import Alert

    found = [
        Alert(id="a", level="critical", title="Legal is three short",
              detail="Nothing is advertised.", source="forecast",
              action_label="Add a job", action_href="/admin"),
    ]
    with script(key="s3cret") as fake, environment(
        ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY="s3cret",
        RESEND_API_KEY=None, ATS_SMTP_HOST=None,
        ATS_ALERT_EMAILS="a@example.com,b@example.com",
    ):
        results = notify.alert_digest(found, base_url="https://acud.example.com")

    assert len(results) == 2 and all(r.ok for r in results)
    assert [m["to"] for m in fake.mail] == ["a@example.com", "b@example.com"]
    assert "Legal is three short" in fake.mail[0]["text"]
    assert "https://acud.example.com" in fake.mail[0]["text"]


def test_a_failing_script_is_reported_rather_than_raised():
    """The CV is already stored, and the alert is already on the dashboard."""
    with environment(ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY="s3cret",
                     RESEND_API_KEY=None, ATS_SMTP_HOST=None):
        with script(key="different-key"):
            result = notify.send("m@example.com", "s", "t", "<p>h</p>")

    assert not result.ok
    assert "key" in result.detail.lower()


# -- the schedule ------------------------------------------------------------
def test_the_hour_is_kept_where_the_thing_that_fires_lives():
    """Vercel's cron time is fixed in vercel.json when the project deploys, so
    nothing on a page can move it. An Apps Script trigger can be made and
    destroyed at will, which is why the schedule lives there."""
    with script(key="s3cret") as fake, environment(
        ATS_SCRIPT_URL=SCRIPT_URL, ATS_SCRIPT_KEY="s3cret"
    ):
        backend = ScriptBackend()
        assert backend.schedule()["enabled"] is False

        saved = backend.set_schedule(
            hour=22, url="https://acud.example.com", secret="cron-secret"
        )
        assert saved["enabled"] is True
        assert saved["hour"] == 22
        # An hour with no clock behind it is not a time.
        assert saved["timezone"] == "Africa/Cairo"
        assert fake.cron_secret == "cron-secret"

        assert backend.clear_schedule()["enabled"] is False
        assert backend.schedule()["hour"] is None


def test_the_script_file_still_implements_every_operation_the_backend_calls():
    """The two halves are deployed separately and drift silently.

    The .gs file is pasted into the sheet by hand, so an operation added here
    and not there fails only in production, on the first person to press the
    button.
    """
    source = (ROOT / "scripts" / "ats_sheet_backend.gs").read_text(encoding="utf-8")
    for op in (
        "ping", "postings", "save_posting", "delete_posting", "applications",
        "save_application", "send_mail", "set_schedule", "get_schedule",
        "clear_schedule", "put_file", "get_file",
    ):
        assert f"{op}: function" in source, f"the script has no {op} handler"

    # And the two operations that must never run on an unkeyed URL say so.
    for guarded in ("send_mail", "set_schedule"):
        body = source.split(f"{guarded}: function")[1].split("},")[0]
        assert "requireKey" in body, f"{guarded} does not require a key"

    # The trigger has something to call, and it wakes the app rather than
    # deciding for itself what is worth an alert.
    assert "function dailyDigest()" in source
    assert "/api/cron/intake?source=schedule" in source


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
