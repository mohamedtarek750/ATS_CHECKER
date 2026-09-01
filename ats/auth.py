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

import os
from dataclasses import dataclass

#: Google's issuers for an ID token. Anything else is not a Google token.
_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

#: The stand-in identity used when auth is deliberately switched off, so the
#: audit trail says "unauthenticated" rather than inventing a person.
DEVELOPMENT_USER_EMAIL = "auth-disabled@localhost"


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


def is_configured() -> bool:
    return bool(client_id() and admin_emails())


def status() -> dict:
    """What the sign-in page needs to know before anybody has signed in."""
    return {
        "required": auth_enabled(),
        "configured": is_configured(),
        "client_id": client_id() if auth_enabled() else "",
        "admins": len(admin_emails()),
    }


def _setup_message() -> str:
    missing = []
    if not client_id():
        missing.append("GOOGLE_OAUTH_CLIENT_ID")
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
