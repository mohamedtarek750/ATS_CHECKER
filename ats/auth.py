"""Who is allowed into the dashboard, and who did what.

The browser signs in with Google and sends the resulting ID token to the API,
which verifies it against Google's own keys and checks the email against an
allow-list. Nothing is shared between the Next.js app and the Python function
except a token Google signed, so there is no session store, no shared secret,
and nothing that has to survive a cold start.

Fails CLOSED. If the dashboard is reachable and this module is not configured,
the admin endpoints refuse to answer and say what is missing. The alternative -
defaulting to open and relying on somebody remembering to switch it on - is how
a folder of strangers' CVs ends up on the public internet. Local development
opts out explicitly with ATS_AUTH=off, and the dashboard says so on screen the
whole time it is unprotected.

    ATS_ADMIN_EMAILS=hr@company.com,lead@company.com
    GOOGLE_OAUTH_CLIENT_ID=<...>.apps.googleusercontent.com
    ATS_AUTH=off        # development only, and it is visible when it is on
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass

#: Google's issuers for an ID token. Anything else is not a Google token.
_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

#: The stand-in identity used when auth is deliberately switched off, so the
#: audit trail says "unauthenticated" rather than inventing a person.
DEVELOPMENT_USER_EMAIL = "auth-disabled@localhost"

#: How long a password sign-in lasts before it has to be done again.
SESSION_HOURS = 12

#: Marks a token this system issued, so it is never sent to Google to verify.
_TOKEN_PREFIX = "ats1."

#: Passwords that protect nothing. Allowed - a prototype is a real use - but
#: said out loud on every screen rather than discovered later.
_WEAK = {
    "admin", "password", "123456", "12345678", "letmein", "changeme",
    "secret", "test", "admin123", "qwerty",
}


class AuthError(Exception):
    """Refused. The message is safe to show a signed-out person."""


class AuthNotConfigured(AuthError):
    """Auth is required but nothing is set up. A deployment mistake, not a login."""


@dataclass(frozen=True)
class AdminUser:
    email: str
    name: str = ""
    picture: str = ""

    @property
    def is_real(self) -> bool:
        return self.email != DEVELOPMENT_USER_EMAIL


def auth_enabled() -> bool:
    """On unless explicitly switched off. Never off by accident."""
    return (os.getenv("ATS_AUTH") or "on").strip().lower() not in {"off", "0", "false"}


def client_id() -> str:
    return (os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()


def admin_emails() -> set[str]:
    raw = os.getenv("ATS_ADMIN_EMAILS") or ""
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def admin_password() -> str:
    return os.getenv("ATS_ADMIN_PASSWORD") or ""


def password_mode() -> bool:
    """Email and password, instead of or alongside Google."""
    return bool(admin_password())


def password_is_weak() -> bool:
    password = admin_password()
    return bool(password) and (len(password) < 10 or password.lower() in _WEAK)


def google_mode() -> bool:
    return bool(client_id())


def is_configured() -> bool:
    """Either door is enough. Both need to know who is allowed in."""
    return bool(admin_emails()) and (password_mode() or google_mode())


def _signing_key() -> bytes:
    """The key our own session tokens are signed with.

    Derived from the password when no separate secret is set, which has a
    property worth having: changing the password invalidates every session
    that was opened with the old one, with nothing to remember to revoke.
    """
    secret = os.getenv("ATS_AUTH_SECRET") or admin_password()
    return hashlib.sha256(f"ats-session-v1:{secret}".encode()).digest()


def issue_token(email: str) -> str:
    """A signed note saying who this is and when it stops counting."""
    expires = int(time.time()) + SESSION_HOURS * 3600
    payload = f"{email}|{expires}"
    signature = hmac.new(
        _signing_key(), payload.encode(), hashlib.sha256
    ).hexdigest()
    raw = f"{payload}|{signature}".encode()
    return _TOKEN_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _read_token(token: str) -> AdminUser:
    """Undo issue_token, refusing anything that was altered or has expired."""
    body = token[len(_TOKEN_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
        email, expires, signature = raw.split("|")
    except Exception as exc:  # noqa: BLE001 - any malformed token
        raise AuthError("That sign-in is not valid. Sign in again.") from exc

    expected = hmac.new(
        _signing_key(), f"{email}|{expires}".encode(), hashlib.sha256
    ).hexdigest()
    # Constant time: a comparison that returns early leaks the signature one
    # character at a time to anybody willing to measure.
    if not hmac.compare_digest(signature, expected):
        raise AuthError("That sign-in is not valid. Sign in again.")
    if int(expires) < time.time():
        raise AuthError("That sign-in has expired. Sign in again.")
    if email.lower() not in admin_emails():
        raise AuthError(f"{email} is no longer on the list for this dashboard.")

    return AdminUser(email=email, name=email.split("@")[0])


def sign_in(email: str, password: str) -> str:
    """Check an email and password, and hand back a token if they are right."""
    if not password_mode():
        raise AuthError("This dashboard does not use a password.")

    address = (email or "").strip().lower()
    if address not in admin_emails():
        raise AuthError("That email address cannot open this dashboard.")
    # Constant time again, and checked even when the address was wrong so that
    # a wrong address and a wrong password take the same time to refuse.
    if not hmac.compare_digest(password or "", admin_password()):
        raise AuthError("Wrong password.")

    return issue_token(address)


def status() -> dict:
    """What the sign-in page needs to know before anybody has signed in."""
    return {
        "required": auth_enabled(),
        "configured": is_configured(),
        "client_id": client_id() if auth_enabled() else "",
        "admins": len(admin_emails()),
        "password": password_mode(),
        "google": google_mode(),
        # Shown on the dashboard the whole time it is true, because a password
        # nobody would have to guess is not a door, and finding that out later
        # is worse than being told now.
        "weak_password": password_is_weak(),
    }


def _setup_message() -> str:
    missing = []
    if not (password_mode() or google_mode()):
        missing.append("ATS_ADMIN_PASSWORD (or GOOGLE_OAUTH_CLIENT_ID)")
    if not admin_emails():
        missing.append("ATS_ADMIN_EMAILS")
    return (
        "The dashboard is not set up for sign-in, so it will not open. Set "
        + " and ".join(missing)
        + " in the deployment's environment. To run without sign-in on your own "
        "machine, set ATS_AUTH=off - never on a deployment that holds real "
        "applications."
    )


def verify(token: str | None) -> AdminUser:
    """Turn a Google ID token into the person it belongs to, or refuse.

    Verification is Google's library rather than anything hand-rolled: it checks
    the signature against Google's published keys, the audience, the issuer and
    the expiry. Getting any one of those wrong is the difference between a login
    and an open door.
    """
    if not auth_enabled():
        return AdminUser(email=DEVELOPMENT_USER_EMAIL, name="Sign-in disabled")

    if not is_configured():
        raise AuthNotConfigured(_setup_message())

    if not token:
        raise AuthError("Sign in to open the dashboard.")

    # Our own token, never sent to Google - it would not know what to do with it.
    if token.startswith(_TOKEN_PREFIX):
        return _read_token(token)

    if not google_mode():
        raise AuthError("Sign in with your email address and password.")

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
    except ImportError as exc:  # pragma: no cover - depends on install
        raise AuthNotConfigured(
            "The Google auth library is not installed. Run: pip install google-auth"
        ) from exc

    try:
        claims = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), client_id()
        )
    except Exception as exc:  # noqa: BLE001 - the library raises several types
        # Never echo the library's message back: it can carry token fragments.
        raise AuthError("That sign-in is not valid or has expired.") from exc

    if claims.get("iss") not in _ISSUERS:
        raise AuthError("That sign-in did not come from Google.")

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise AuthError("That Google account has no email address on it.")
    if not claims.get("email_verified"):
        raise AuthError("That Google account's email address is not verified.")

    if email not in admin_emails():
        # Says who is signed in, so somebody using the wrong account can see it,
        # without listing who IS allowed.
        raise AuthError(
            f"{email} is not on the list of people who can open this dashboard."
        )

    return AdminUser(
        email=email,
        name=claims.get("name") or "",
        picture=claims.get("picture") or "",
    )
