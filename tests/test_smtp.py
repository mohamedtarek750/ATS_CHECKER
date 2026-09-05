"""Sending through an ordinary mailbox instead of through Resend.

This transport exists for one reason: Resend will not send as somebody@gmail.com,
because nobody can prove they own gmail.com. A Gmail account can send as itself
over SMTP.

Most of what can go wrong here goes wrong in configuration, silently, and is
discovered by an applicant who never got a reply. So these tests are mostly
about the misconfigurations - a From address that does not match the mailbox, a
port the host blocks, a password that is not an App Password - and about each
one producing a sentence somebody can act on rather than a provider's error
code.

No password appears in this file, and none is needed: the mailbox is a double.

Run: python tests/test_smtp.py
"""

from __future__ import annotations

import contextlib
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import notify  # noqa: E402


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


#: A mailbox that is set up correctly. The password is a placeholder; nothing
#: here ever reaches a real server.
SMTP_ON = dict(
    RESEND_API_KEY=None,
    ATS_SMTP_HOST="smtp.gmail.com",
    ATS_SMTP_PORT="587",
    ATS_SMTP_USER="me@gmail.com",
    ATS_SMTP_PASSWORD="not-a-real-password",
    ATS_MAIL_FROM="ACUD Careers <me@gmail.com>",
)


class FakeServer:
    """Stands in for a mail server, and keeps what it was told.

    Records the conversation as well as the message, because the order matters:
    STARTTLS has to happen before the password is offered, or the password
    crosses the wire in clear text.
    """

    instances: list["FakeServer"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.steps: list[str] = []
        self.messages: list[EmailMessage] = []
        self.fail_login: Exception | None = None
        FakeServer.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.steps.append("quit")
        return False

    def starttls(self, context=None):
        self.steps.append("starttls")

    def login(self, user, password):
        if self.fail_login:
            raise self.fail_login
        self.user = user
        self.steps.append("login")

    def send_message(self, message):
        self.messages.append(message)
        self.steps.append("send")


@contextlib.contextmanager
def fake_smtp(login_error: Exception | None = None):
    FakeServer.instances = []
    plain, secure = smtplib.SMTP, smtplib.SMTP_SSL

    def make(*args, **kwargs):
        server = FakeServer(*args, **kwargs)
        server.fail_login = login_error
        return server

    smtplib.SMTP = make
    smtplib.SMTP_SSL = make
    try:
        yield FakeServer.instances
    finally:
        smtplib.SMTP, smtplib.SMTP_SSL = plain, secure


# -- which route is taken ----------------------------------------------------
def test_a_mailbox_alone_is_enough_to_send():
    """No Resend key, no domain, and mail still goes out."""
    with environment(**SMTP_ON):
        assert notify.is_configured()
        assert notify.transport() == "smtp"


def test_resend_wins_when_both_are_configured():
    """An HTTP request finishes inside one serverless invocation. An SMTP
    conversation holds a socket open across several round trips."""
    with environment(**{**SMTP_ON, "RESEND_API_KEY": "re_test"}):
        assert notify.transport() == "resend"


def test_a_half_configured_mailbox_is_no_mailbox():
    # A host with no password is somebody who stopped halfway. Treating it as
    # configured would mean failing on every send instead of saying so once.
    for missing in ("ATS_SMTP_HOST", "ATS_SMTP_USER", "ATS_SMTP_PASSWORD"):
        with environment(**{**SMTP_ON, missing: None}):
            assert notify.transport() == "none", missing
            assert not notify.is_configured(), missing


def test_the_dashboard_can_say_which_route_is_in_use():
    with environment(**SMTP_ON):
        state = notify.status()
        assert state["transport"] == "smtp"
        assert state["from"] == "ACUD Careers <me@gmail.com>"

    # And with no ATS_MAIL_FROM it reports the address a recipient would see,
    # not an empty string.
    with environment(**{**SMTP_ON, "ATS_MAIL_FROM": None}):
        assert notify.status()["from"] == "me@gmail.com"


# -- the happy path ----------------------------------------------------------
def test_a_message_goes_out_with_both_a_text_and_an_html_part():
    with environment(**SMTP_ON), fake_smtp() as servers:
        result = notify.send(
            "malak@example.com", "Hello", "plain words", "<p>rich words</p>"
        )

    assert result.ok, result.detail
    assert len(servers) == 1
    server = servers[0]
    assert (server.host, server.port) == ("smtp.gmail.com", 587)

    message = server.messages[0]
    assert message["To"] == "malak@example.com"
    assert message["From"] == "ACUD Careers <me@gmail.com>"
    assert message["Subject"] == "Hello"
    assert message.get_body("plain").get_content().strip() == "plain words"
    assert "rich words" in message.get_body("html").get_content()


def test_the_password_is_never_offered_before_the_connection_is_encrypted():
    """On 587 the session starts in clear text. Sending the password before
    STARTTLS would put it on the wire for anybody on the path to read."""
    with environment(**SMTP_ON), fake_smtp() as servers:
        notify.send("malak@example.com", "Hello", "text", "<p>html</p>")

    steps = servers[0].steps
    assert steps.index("starttls") < steps.index("login")
    assert steps.index("login") < steps.index("send")


def test_port_465_is_already_encrypted_and_is_not_upgraded_again():
    with environment(**{**SMTP_ON, "ATS_SMTP_PORT": "465"}), fake_smtp() as servers:
        assert notify.send("m@example.com", "s", "t", "<p>h</p>").ok
    assert "starttls" not in servers[0].steps


def test_every_recipient_gets_their_own_connection_and_their_own_message():
    """One message addressed to two people would show each of them the other's
    address. These are separate emails to separate people."""
    with environment(**SMTP_ON, ATS_ALERT_EMAILS="a@example.com,b@example.com"):
        with fake_smtp() as servers:
            from ats.alerts import Alert

            results = notify.alert_digest(
                [Alert(id="x", level="critical", title="Short", detail="d",
                       source="forecast")]
            )

    assert len(results) == 2 and all(r.ok for r in results)
    assert len(servers) == 2
    assert [s.messages[0]["To"] for s in servers] == ["a@example.com", "b@example.com"]


# -- the mistakes people actually make ---------------------------------------
def test_a_from_address_that_is_not_the_mailbox_is_refused_before_dialling():
    """Gmail rejects this with a code nobody can read. Saying it in English,
    without opening a connection, is the difference between a five-minute fix
    and an afternoon."""
    with environment(**{**SMTP_ON, "ATS_MAIL_FROM": "Careers <careers@acud.eg>"}):
        with fake_smtp() as servers:
            result = notify.send("m@example.com", "s", "t", "<p>h</p>")

    assert not result.ok and result.skipped
    assert "careers@acud.eg" in result.detail
    assert "me@gmail.com" in result.detail
    assert servers == [], "a connection was opened for a message that cannot send"


def test_a_display_name_around_the_right_address_is_fine():
    for sender in (
        "me@gmail.com",
        "ACUD Careers <me@gmail.com>",
        "ACUD <ME@GMAIL.COM>",
    ):
        with environment(**{**SMTP_ON, "ATS_MAIL_FROM": sender}), fake_smtp():
            assert notify.send("m@example.com", "s", "t", "<p>h</p>").ok, sender


def test_port_25_is_named_as_the_blocked_one():
    """Vercel blocks outbound 25 - the port mail servers relay to each other on,
    and the one spam relays abuse. A timeout tells nobody that."""
    with environment(**{**SMTP_ON, "ATS_SMTP_PORT": "25"}), fake_smtp() as servers:
        result = notify.send("m@example.com", "s", "t", "<p>h</p>")

    assert not result.ok and result.skipped
    assert "587" in result.detail
    assert servers == []


def test_a_nonsense_port_falls_back_to_the_usual_one_rather_than_crashing():
    with environment(**{**SMTP_ON, "ATS_SMTP_PORT": "not a number"}), fake_smtp() as s:
        assert notify.send("m@example.com", "s", "t", "<p>h</p>").ok
    assert s[0].port == 587


def test_a_refused_sign_in_says_what_to_check_and_never_the_password():
    refused = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")
    with environment(**SMTP_ON), fake_smtp(login_error=refused):
        result = notify.send("m@example.com", "s", "t", "<p>h</p>")

    assert not result.ok
    assert "App Password" in result.detail
    assert "2-Step Verification" in result.detail
    assert "not-a-real-password" not in result.detail


def test_a_dead_server_is_reported_rather_than_raised():
    """The CV is already stored by the time any of this runs."""
    with environment(**SMTP_ON), fake_smtp(login_error=OSError("connection refused")):
        result = notify.send("m@example.com", "s", "t", "<p>h</p>")
    assert not result.ok and not result.skipped
    assert "connection refused" in result.detail


def test_an_unusable_recipient_is_skipped_before_a_connection_is_opened():
    with environment(**SMTP_ON), fake_smtp() as servers:
        assert notify.send("not-an-email", "s", "t", "<p>h</p>").skipped
    assert servers == []


def test_a_subject_cannot_carry_a_second_header_into_the_message():
    """Subjects are built from vacancy titles, which a recruiter writes."""
    with environment(**SMTP_ON), fake_smtp() as servers:
        notify.send(
            "m@example.com",
            "Alert\r\nBcc: victim@example.com",
            "text",
            "<p>html</p>",
        )

    message = servers[0].messages[0]
    assert message["Bcc"] is None
    assert "\n" not in message["Subject"] and "\r" not in message["Subject"]
    assert message["To"] == "m@example.com"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {name}: {exc}")
    print(f"\n{'FAILED' if failures else 'ALL PASSED'} ({failures} failure(s))")
    sys.exit(1 if failures else 0)
