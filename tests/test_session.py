"""Sessions: renewed under somebody using them, ended for somebody who is not.

The bug this exists for: a dashboard left open overnight, a twelve-hour session
quietly gone, and the only sign of it a red box beside a button that still
invited another go. Two properties fix it, and both need holding to.

  * A session past halfway is renewed on every admin request, so the twelve
    hours run from the LAST request rather than from signing in.
  * A renewal never resurrects a session that has already expired, never
    changes whose it is, and never happens for a Google token - which is
    Google's to renew and not this module's to mint.

Run: python tests/test_session.py
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats import auth  # noqa: E402


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


SIGNED_IN = dict(
    ATS_AUTH="on",
    ATS_ADMIN_EMAILS="hr@company.com",
    ATS_ADMIN_PASSWORD="a-long-enough-password",
    GOOGLE_OAUTH_CLIENT_ID=None,
)


@contextlib.contextmanager
def clock(offset_seconds: float):
    """Move time forward, without waiting for it."""
    real = time.time
    time.time = lambda: real() + offset_seconds
    try:
        yield
    finally:
        time.time = real


def test_a_fresh_session_is_left_alone():
    """Renewing on every request would mint a token per keystroke."""
    with environment(**SIGNED_IN):
        token = auth.sign_in("hr@company.com", "a-long-enough-password")
        assert auth.renewed_token(token) == ""


def test_a_session_past_halfway_is_renewed():
    with environment(**SIGNED_IN):
        token = auth.sign_in("hr@company.com", "a-long-enough-password")

        # Seven hours into a twelve-hour session.
        with clock(7 * 3600):
            fresh = auth.renewed_token(token)
            assert fresh and fresh != token
            # And it is the same person, not a new identity.
            assert auth.verify(fresh).email == "hr@company.com"


def test_working_through_the_day_never_signs_anybody_out():
    """The property the whole thing exists for.

    A request every few hours keeps the session alive indefinitely, because
    each renewal restarts the twelve hours.
    """
    with environment(**SIGNED_IN):
        token = auth.sign_in("hr@company.com", "a-long-enough-password")

        # Two days, checking in every seven hours.
        for hours in range(7, 48, 7):
            with clock(hours * 3600):
                auth.verify(token)  # still good, or this raises
                fresh = auth.renewed_token(token)
                if fresh:
                    token = fresh

        with clock(48 * 3600):
            assert auth.verify(token).email == "hr@company.com"


def test_walking_away_still_ends_the_session():
    """Otherwise the expiry means nothing at all."""
    with environment(**SIGNED_IN):
        token = auth.sign_in("hr@company.com", "a-long-enough-password")

        with clock(13 * 3600):
            try:
                auth.verify(token)
            except auth.AuthError as exc:
                assert "expired" in str(exc)
            else:
                raise AssertionError("a thirteen-hour-old session was accepted")

            # And an expired token is not renewable - that would be a session
            # that never ends, reachable by anybody who kept an old one.
            assert auth.renewed_token(token) == ""


def test_a_renewal_cannot_be_forged_into_somebody_elses_session():
    with environment(**SIGNED_IN):
        token = auth.sign_in("hr@company.com", "a-long-enough-password")
        with clock(7 * 3600):
            fresh = auth.renewed_token(token)

        # Signed with the same key, so it verifies - and says who it started as.
        assert auth.verify(fresh).email == "hr@company.com"

    # Change the password and every session opened under the old one dies,
    # renewed or not.
    with environment(**{**SIGNED_IN, "ATS_ADMIN_PASSWORD": "a-different-password"}):
        for one in (token, fresh):
            try:
                auth.verify(one)
            except auth.AuthError:
                pass
            else:
                raise AssertionError("a token outlived the password behind it")


def test_a_google_token_is_not_renewed_here():
    """It is Google's to renew, and this has no business minting one."""
    with environment(**SIGNED_IN):
        assert auth.renewed_token("eyJhbGciOiJSUzI1NiIsImtpZCI6IngifQ.e30.") == ""
        assert auth.renewed_token("") == ""
        assert auth.renewed_token("nonsense") == ""


def test_the_api_hands_the_renewed_session_back_in_a_header():
    """A header rather than a body field, so every admin route gets it without
    any of them knowing it exists."""
    import tempfile

    from fastapi.testclient import TestClient

    from api.index import SESSION_HEADER, app
    from ats import backends
    from ats.backends.local import LocalBackend

    backends._backend = LocalBackend(Path(tempfile.mkdtemp()))
    client = TestClient(app)

    with environment(**SIGNED_IN):
        token = auth.sign_in("hr@company.com", "a-long-enough-password")
        headers = {"Authorization": f"Bearer {token}"}

        fresh = client.get("/api/postings", headers=headers)
        assert fresh.status_code == 200
        assert SESSION_HEADER not in fresh.headers, "a new session was minted early"

        with clock(7 * 3600):
            renewed = client.get("/api/postings", headers=headers)
        assert renewed.status_code == 200
        handed_back = renewed.headers.get(SESSION_HEADER)
        assert handed_back and handed_back != token

        # The browser can carry it, and it works.
        with clock(7 * 3600):
            after = client.get(
                "/api/postings", headers={"Authorization": f"Bearer {handed_back}"}
            )
        assert after.status_code == 200


def test_a_refused_request_hands_back_no_session_at_all():
    """A 401 that carried a token would be a way in without a password."""
    import tempfile

    from fastapi.testclient import TestClient

    from api.index import SESSION_HEADER, app
    from ats import backends
    from ats.backends.local import LocalBackend

    backends._backend = LocalBackend(Path(tempfile.mkdtemp()))
    client = TestClient(app)

    with environment(**SIGNED_IN):
        for bad in ("", "nonsense", "ats1.forged"):
            response = client.get(
                "/api/postings", headers={"Authorization": f"Bearer {bad}"}
            )
            assert response.status_code == 401, bad
            assert SESSION_HEADER not in response.headers, bad


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
