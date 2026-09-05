"""Email and statistics.

Email is the part of this system that reaches a stranger's inbox, so the tests
are mostly about restraint: what it refuses to send, what it does when the
provider is down, and what happens to a name somebody typed into a public form
before it reaches an HTML body.

Run: python tests/test_automation.py
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import backends, intake, notify, postings, stats  # noqa: E402
from ats.backends.local import LocalBackend  # noqa: E402
from ats.job_profile import JobProfile, Requirement  # noqa: E402
from ats.postings import Application, JobPosting  # noqa: E402

SAMPLES = ROOT / "samples"


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


@contextlib.contextmanager
def fake_provider(status=200, raises=None):
    """Stand in for Resend, and keep what would have been sent."""
    sent: list[dict] = []
    original = urllib.request.urlopen

    class Response:
        def __init__(self, code):
            self.status = code

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(request, timeout=None):
        if raises is not None:
            raise raises
        sent.append(json.loads(request.data.decode("utf-8")))
        return Response(status)

    urllib.request.urlopen = fake
    try:
        yield sent
    finally:
        urllib.request.urlopen = original


MAIL_ON = dict(
    RESEND_API_KEY="re_test",
    ATS_MAIL_FROM="Careers <careers@example.com>",
    ATS_HR_EMAILS="hr@company.com,lead@company.com",
)


def make_posting() -> JobPosting:
    job = JobProfile(
        title="Data Analyst", seniority="Mid", summary="Owns reporting.",
        min_years_experience=2,
        requirements=[
            Requirement(text="Strong SQL", kind="skill", importance="must_have"),
            Requirement(text="Power BI", kind="skill", importance="must_have"),
            Requirement(text="Kubernetes", kind="skill", importance="must_have"),
            Requirement(text="Azure", kind="skill", importance="nice_to_have"),
        ],
    )
    return JobPosting(slug="data-analyst", title="Data Analyst",
                      summary="Owns reporting.", profile=job)


# --------------------------------------------------------------------------
def test_nothing_is_sent_and_nothing_breaks_without_a_provider():
    """The whole feature is optional, and an application must not depend on it."""
    with environment(RESEND_API_KEY=None, ATS_MAIL_FROM=None):
        assert not notify.is_configured()
        result = notify.application_received(
            Application(job_slug="x", full_name="Omar", email="omar@example.com"),
            make_posting(),
        )
        assert result.skipped
        assert not result.ok
        assert "no mail provider" in result.detail


def test_a_provider_outage_never_reaches_the_applicant():
    """The CV is already stored by the time this runs. A mail failure is a mail
    failure, not a lost application."""
    posting = make_posting()
    row = Application(job_slug="x", full_name="Omar", email="omar@example.com")

    with environment(**MAIL_ON):
        with fake_provider(raises=OSError("connection refused")):
            result = notify.application_received(row, posting)
        assert not result.ok and not result.skipped
        assert "connection refused" in result.detail

        with fake_provider(status=500):
            assert not notify.application_received(row, posting).ok


def test_a_name_from_a_public_form_cannot_inject_a_header_or_markup():
    """The applicant writes their own name, and it ends up in an email."""
    posting = make_posting()
    row = Application(
        job_slug="x",
        full_name="Omar<script>alert(1)</script>\r\nBcc: victim@example.com",
        email="attacker@example.com",
    )
    with environment(**MAIL_ON), fake_provider() as sent:
        assert notify.application_received(row, posting).ok

    message = sent[0]
    assert "\n" not in message["subject"] and "\r" not in message["subject"]
    assert "<script>" not in message["html"], "markup reached the HTML body"
    assert "&lt;script&gt;" in message["html"]
    # The recipient is the address on the application, and only that.
    assert message["to"] == ["attacker@example.com"]


def test_an_unusable_address_is_skipped_rather_than_sent():
    posting = make_posting()
    for address in ("", "not-an-email", "two@@at.com", "no-at-sign.com"):
        with environment(**MAIL_ON), fake_provider() as sent:
            result = notify.application_received(
                Application(job_slug="x", full_name="X", email=address), posting
            )
            assert result.skipped, f"{address!r} was sent to"
            assert sent == []


def test_the_team_gets_one_digest_not_one_email_per_applicant():
    """A vacancy that attracts two hundred people must not send two hundred."""
    posting = make_posting()
    rows = [
        Application(job_slug="x", full_name=f"Person {i}",
                    email=f"p{i}@example.com", status="read",
                    percent=90 - i, tier="accepted" if i < 3 else "rejected")
        for i in range(40)
    ]
    with environment(**MAIL_ON), fake_provider() as sent:
        results = notify.new_applications_digest(posting, rows)

    # Two recipients, one message each. Not 40, and not 80.
    assert len(results) == 2
    assert len(sent) == 2
    assert all(r.ok for r in results)
    assert "40 new applications" in sent[0]["subject"]
    assert "3 accepted" in sent[0]["text"]


def test_no_digest_goes_out_when_nothing_arrived():
    with environment(**MAIL_ON), fake_provider() as sent:
        assert notify.new_applications_digest(make_posting(), []) == []
        assert sent == []


def test_a_rejection_is_never_emailed():
    """Deliberate. A percentage from a document parser is not grounds for a
    machine to tell somebody they did not get the job."""
    public = {name for name in dir(notify) if not name.startswith("_")}
    assert "application_received" in public
    assert "new_applications_digest" in public
    # If a rejection mail is ever added, this is where somebody has to argue
    # for it rather than slipping it in.
    assert not any("reject" in name.lower() for name in public)


# --------------------------------------------------------------------------
def test_statistics_say_which_requirement_nobody_meets():
    """The figure worth having: a must-have met by nobody is a broken advert."""
    tmp = Path(tempfile.mkdtemp())
    backend = LocalBackend(tmp)
    posting = backend.save_posting(make_posting())
    try:
        for name, cv in [
            ("Omar", "01_data_analyst_omar.pdf"),
            ("Mona", "01_data_analyst_omar.pdf"),
            ("Hassan", "04_civil_engineer_hassan.pdf"),
        ]:
            row = intake.receive(
                backend, posting, full_name=name, email=f"{name.lower()}@e.com",
                phone="", filename=cv, data=(SAMPLES / cv).read_bytes(),
            )
            intake.read(backend, posting, row)

        computed = stats.summarize(posting, backend.applications(posting.slug), backend)
        assert computed.total == 3
        assert computed.read == 3
        assert computed.sampled == 3
        assert not computed.sample_capped
        assert computed.per_day and computed.per_day[0][1] == 3

        # Kubernetes is on the advert and on nobody's CV. It has to be first,
        # and it has to be identifiable as mandatory.
        hardest = computed.hardest[0]
        assert hardest.requirement == "Kubernetes"
        assert hardest.percent == 0
        assert hardest.is_must

        # Must-haves are ordered ahead of preferred extras: a preferred thing
        # nobody has is a footnote, a mandatory one is why the shortlist is empty.
        musts = [d for d in computed.hardest if d.is_must]
        assert computed.hardest[: len(musts)] == musts
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_statistics_do_not_average_applications_nobody_has_read():
    """A pending application has no score; counting it as zero would drag the
    average down and make a healthy vacancy look dead."""
    tmp = Path(tempfile.mkdtemp())
    backend = LocalBackend(tmp)
    posting = backend.save_posting(make_posting())
    try:
        read = intake.receive(
            backend, posting, full_name="Omar", email="o@e.com", phone="",
            filename="omar.pdf",
            data=(SAMPLES / "01_data_analyst_omar.pdf").read_bytes(),
        )
        intake.read(backend, posting, read)
        intake.receive(
            backend, posting, full_name="Later", email="l@e.com", phone="",
            filename="omar.pdf",
            data=(SAMPLES / "01_data_analyst_omar.pdf").read_bytes(),
        )

        computed = stats.summarize(posting, backend.applications(posting.slug), backend)
        assert computed.total == 2
        assert computed.read == 1
        assert computed.pending == 1
        scored = backend.applications(posting.slug)[0].percent
        assert computed.average_percent == scored
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_statistics_survive_a_vacancy_nobody_applied_to():
    computed = stats.summarize(make_posting(), [], None)
    assert computed.total == 0
    assert computed.average_percent == 0
    assert computed.hardest == []
    assert computed.per_day == []


def test_a_cv_sent_without_a_role_is_thanked_without_naming_one():
    """The holding pen's title is written for the recruiter's list.

    "Your application for Applicants without a job description has been
    received" is what the generic version produced, which reads like a
    rejection to the person who gets it.
    """
    pen = postings.unassigned_posting()
    row = Application(job_slug=pen.slug, full_name="Nadia Saleh",
                      email="nadia@example.com")

    with environment(**MAIL_ON), fake_provider() as sent:
        assert notify.application_received(row, pen).ok

    message = sent[0]
    everything = message["subject"] + message["text"] + message["html"]
    assert "without a job description" not in everything
    assert "unassigned" not in everything.lower()
    assert message["subject"] == "Application received - ACUD"
    assert "Nadia" in message["text"]
    # It still says what happens next, rather than trailing off.
    assert "kept on file" in message["text"]


def test_applying_to_a_vacancy_still_names_it():
    posting = make_posting()
    row = Application(job_slug=posting.slug, full_name="Omar Hassan",
                      email="omar@example.com")

    with environment(**MAIL_ON), fake_provider() as sent:
        assert notify.application_received(row, posting).ok

    assert sent[0]["subject"] == "Application received - Data Analyst"
    assert "Data Analyst" in sent[0]["text"]


def test_applying_through_the_form_sends_the_thank_you():
    """The wiring, not just the message.

    Both public routes are checked: a receipt that only went out on one of them
    would leave everybody who applied without picking a role hearing nothing.
    """
    from fastapi.testclient import TestClient

    from api.index import app
    from ats import backends
    from ats.backends.local import LocalBackend

    import json as _json
    import tempfile
    from pathlib import Path as _Path

    cv = (ROOT / "samples" / "01_data_analyst_omar.pdf").read_bytes()

    for route, expected in (
        ("vacancy", "Application received - Data Analyst"),
        ("open", "Application received - ACUD"),
    ):
        backends._backend = LocalBackend(_Path(tempfile.mkdtemp()))
        client = TestClient(app)
        with environment(ATS_AUTH="off", **MAIL_ON), fake_provider() as sent:
            if route == "vacancy":
                slug = client.post(
                    "/api/postings",
                    json={"job": _json.loads(make_posting().profile.model_dump_json())},
                ).json()["slug"]
                where = f"/api/public/postings/{slug}/apply"
            else:
                where = "/api/public/apply"

            receipt = client.post(
                where,
                data={"full_name": "Omar Hassan", "email": "omar@example.com",
                      "phone": ""},
                files={"file": ("omar.pdf", cv, "application/pdf")},
            )
            assert receipt.status_code == 200, receipt.text
            # The receipt the applicant sees still leaks nothing about scoring.
            assert set(receipt.json()) == {"id", "full_name", "status"}

            assert len(sent) == 1, f"{route}: {len(sent)} emails"
            assert sent[0]["subject"] == expected
            assert sent[0]["to"] == ["omar@example.com"]


def test_a_mail_outage_does_not_fail_the_application():
    """The one rule this whole feature hangs on."""
    from fastapi.testclient import TestClient

    from api.index import app
    from ats import backends
    from ats.backends.local import LocalBackend

    import tempfile
    from pathlib import Path as _Path

    backends._backend = LocalBackend(_Path(tempfile.mkdtemp()))
    client = TestClient(app)
    cv = (ROOT / "samples" / "01_data_analyst_omar.pdf").read_bytes()

    with environment(ATS_AUTH="off", **MAIL_ON):
        with fake_provider(raises=OSError("the provider is down")):
            response = client.post(
                "/api/public/apply",
                data={"full_name": "Omar", "email": "omar@example.com", "phone": ""},
                files={"file": ("omar.pdf", cv, "application/pdf")},
            )

        assert response.status_code == 200, response.text
        # And the CV is really there, not just acknowledged.
        stored = client.get(f"/api/cv-file/{response.json()['id']}")
        assert stored.status_code == 200, stored.text


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
