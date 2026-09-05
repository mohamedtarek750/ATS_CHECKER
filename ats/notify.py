"""Email, and the rules about when this system is allowed to send one.

Two messages, and only two:

  * A receipt to the person who applied, so they know their CV arrived.
  * A digest to the hiring team when new applications have been read.

Nothing else. In particular this NEVER emails a rejection. A percentage from a
document parser is not grounds for a machine to tell somebody they did not get
the job, and once such a mail is automatic nobody reads the decision behind it.
Rejections stay a thing a person does.

Three rules the code has to hold to:

  1. Sending must never break an application. The applicant's CV is already
     stored before this is called, and every failure here is swallowed and
     recorded - an outage at the mail provider cannot cost somebody their
     application.
  2. The applicant writes their own name and address. Both reach an email, so
     the name is escaped before it goes near HTML and stripped of the newlines
     that would otherwise let it inject headers.
  3. With nothing configured, nothing is sent and nothing fails. The whole
     feature is optional.

THREE WAYS TO POST A LETTER
---------------------------
Any one is enough. ATS_MAIL_TRANSPORT forces a choice; with it unset they are
tried in the order below.

    # 1. Resend. Needs a domain you can prove you own.
    RESEND_API_KEY=re_...
    ATS_MAIL_FROM="Careers <careers@yourdomain.com>"

    # 2. An ordinary mailbox, over SMTP. Needs no domain.
    ATS_SMTP_HOST=smtp.gmail.com
    ATS_SMTP_PORT=587
    ATS_SMTP_USER=you@gmail.com
    ATS_SMTP_PASSWORD=...        # Gmail: an App Password, not the account one
    ATS_MAIL_FROM="ACUD Careers <you@gmail.com>"   # must be the same mailbox

    # 3. The sheet's own Apps Script. Needs nothing new at all.
    ATS_SCRIPT_URL=https://script.google.com/macros/s/AKfy.../exec
    ATS_SCRIPT_KEY=...           # required for mail, unlike for storage

    ATS_HR_EMAILS=hr@company.com,lead@company.com

The third is the one that costs nothing to set up, because the script is
already deployed for storage and already runs AS THE SHEET'S OWNER - so it can
send as them with no credential of any kind. It is the same mechanism a Google
Sheets booking form uses to email a confirmation.

Resend is first when several are configured: one HTTP request completes inside
a single serverless invocation, and it sends from a domain rather than from a
person. The other two send from somebody's personal mailbox, which means that
mailbox's daily limit (100 a day through Apps Script on a gmail.com account,
a few hundred over SMTP), a personal address in front of every applicant, and
their replies landing in a personal inbox.
"""

from __future__ import annotations

import html
import json
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr

from .postings import UNASSIGNED_SLUG

RESEND_ENDPOINT = "https://api.resend.com/emails"
TIMEOUT_SECONDS = 10

#: Vercel blocks outbound port 25 - the one mail servers use to relay to each
#: other, and the one spam relays abuse. 587 and 465 are open, so those are the
#: two that are any use here.
BLOCKED_PORTS = {25}

#: Quotation marks that get copied along with the thing they were quoting.
#: Named individually because "a non-ASCII character" is not something anybody
#: can look for, and "a ‹ at the start" is.
_STRAY = {
    "\u2039": "‹", "\u203a": "›",
    "\u201c": "“", "\u201d": "”",
    "\u2018": "‘", "\u2019": "’",
    "\u00ab": "«", "\u00bb": "»",
    "\u2013": "–", "\u2014": "—",
    "\u00a0": "a non-breaking space",
}


def _not_ascii(label: str, value: str) -> str:
    """A sentence about the first character SMTP cannot carry, or "".

    SMTP authentication is ASCII only - smtplib encodes both the username and
    the password with .encode('ascii') and raises if it cannot. The error it
    raises names a position in a string the reader has never seen.
    """
    for index, character in enumerate(value):
        if ord(character) < 128:
            continue
        named = _STRAY.get(character)
        hint = (
            f" That is {named}, which is usually copied along with the text it "
            f"was quoting - paste the value on its own, without the marks "
            f"around it."
            if named
            else ""
        )
        return (
            f"{label} has a character SMTP cannot carry at position "
            f"{index + 1}: {character!r}.{hint}"
        )
    return ""

#: Anything that could start a new header line. A name is one line, always.
_HEADER_BREAK = re.compile(r"[\r\n]+")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Sent:
    """What happened. Never an exception - the caller has already succeeded."""

    ok: bool
    detail: str = ""
    skipped: bool = False

    @property
    def note(self) -> str:
        if self.skipped:
            return f"not sent: {self.detail}"
        return "sent" if self.ok else f"failed: {self.detail}"


def api_key() -> str:
    return (os.getenv("RESEND_API_KEY") or "").strip()


def mail_from() -> str:
    return (os.getenv("ATS_MAIL_FROM") or "").strip()


def hr_emails() -> list[str]:
    raw = os.getenv("ATS_HR_EMAILS") or ""
    return [e.strip() for e in raw.split(",") if _EMAIL.match(e.strip())]


def smtp_settings() -> dict:
    """The mailbox to send through, or an empty dict if none is set up."""
    host = (os.getenv("ATS_SMTP_HOST") or "").strip()
    user = (os.getenv("ATS_SMTP_USER") or "").strip()
    password = os.getenv("ATS_SMTP_PASSWORD") or ""
    if not (host and user and password):
        return {}

    try:
        port = int((os.getenv("ATS_SMTP_PORT") or "587").strip())
    except ValueError:
        port = 587
    return {"host": host, "port": port, "user": user, "password": password}


def script_mail_ready() -> bool:
    """Whether the sheet's script can be asked to send.

    The key is required, and not by accident: the Web app answers whoever
    holds its URL, and an unkeyed send operation is an open relay running on
    somebody's personal Gmail. The script refuses too - this is the same rule
    said on the near side, so the reason reaches the person configuring it.
    """
    url = (os.getenv("ATS_SCRIPT_URL") or "").strip()
    key = (os.getenv("ATS_SCRIPT_KEY") or "").strip()
    return bool(url and key)


#: Tried in this order when ATS_MAIL_TRANSPORT does not name one. Resend leads
#: because it sends from a domain rather than from a person, and finishes in a
#: single request.
_ORDER = ("resend", "smtp", "script")


def transport() -> str:
    """Which way mail actually goes out."""
    available = {
        "resend": bool(api_key() and mail_from()),
        "smtp": bool(smtp_settings()),
        "script": script_mail_ready(),
    }

    forced = (os.getenv("ATS_MAIL_TRANSPORT") or "").strip().lower()
    if forced in available:
        # Honoured only if it can actually work. Silently falling back would
        # mean mail going out by a route somebody deliberately did not pick.
        return forced if available[forced] else "none"

    for name in _ORDER:
        if available[name]:
            return name
    return "none"


def is_configured() -> bool:
    return transport() != "none"


def status() -> dict:
    how = transport()
    settings = smtp_settings()

    # The address a recipient would actually see. SMTP can send as its own
    # mailbox with ATS_MAIL_FROM unset; the script always sends as whoever owns
    # the sheet, which this cannot know from here - so it says so rather than
    # printing an address that would be a guess.
    if how == "smtp":
        seen = mail_from() or settings.get("user", "")
    elif how == "script":
        seen = mail_from() or "the Google account that owns the sheet"
    elif how == "resend":
        seen = mail_from()
    else:
        seen = ""

    return {
        "configured": how != "none",
        "transport": how,
        "from": seen,
        "hr_recipients": len(hr_emails()),
    }


def safe_name(name: str) -> str:
    """A person's name, fit to put in a subject line. One line, bounded."""
    return _HEADER_BREAK.sub(" ", name).strip()[:80]


def send(to: str, subject: str, text: str, html_body: str) -> Sent:
    """One email, by whichever route is configured.

    Returns what happened and never raises at the caller: everything that calls
    this has already succeeded at the thing that mattered, and a mail outage
    must not undo it.
    """
    how = transport()
    if how == "none":
        return Sent(ok=False, skipped=True, detail="no mail provider configured")
    if not _EMAIL.match(to.strip()):
        return Sent(ok=False, skipped=True, detail=f"not a usable address: {to!r}")
    if how == "smtp":
        return _send_over_smtp(to.strip(), safe_name(subject), text, html_body)
    if how == "script":
        return _send_over_script(to.strip(), safe_name(subject), text, html_body)

    payload = json.dumps(
        {
            "from": mail_from(),
            "to": [to.strip()],
            "subject": safe_name(subject),
            "text": text,
            "html": html_body,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        RESEND_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if 200 <= response.status < 300:
                return Sent(ok=True)
            return Sent(ok=False, detail=f"provider returned {response.status}")
    except urllib.error.HTTPError as exc:
        # The body can carry the reason (bad domain, unverified sender). The key
        # is in the request headers, not the response, so this is safe to keep.
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            detail = ""
        return Sent(ok=False, detail=f"{exc.code} {detail}".strip())
    except Exception as exc:  # noqa: BLE001 - a mail outage is not an error here
        return Sent(ok=False, detail=f"{type(exc).__name__}: {exc}"[:200])


def _send_over_script(to: str, subject: str, text: str, html_body: str) -> Sent:
    """Through the Apps Script deployed on the spreadsheet.

    The script runs as the sheet's owner, so it sends as them and there is no
    credential here at all - which is the whole appeal, and also why the shared
    key is not optional for it.
    """
    from .backends.script import ScriptBackend

    # Built here rather than reused from the storage backend: mail can go this
    # way while applications are stored somewhere else entirely, and this class
    # holds nothing but configuration read from the environment.
    try:
        script = ScriptBackend()
    except Exception as exc:  # noqa: BLE001 - a misconfiguration, said plainly
        return Sent(ok=False, skipped=True, detail=str(exc)[:200])

    name, address = parseaddr(mail_from())
    try:
        script.send_mail(
            to=to,
            subject=subject,
            text=text,
            html=html_body,
            # ATS_MAIL_FROM cannot change WHO it comes from - the script sends
            # as its owner - but the name beside the address is free, so a
            # message arrives as the careers team rather than as a person.
            name=name or "",
            reply_to=address or "",
        )
        return Sent(ok=True)
    except Exception as exc:  # noqa: BLE001 - a mail outage is not an error here
        return Sent(ok=False, detail=str(exc)[:200])


def _send_over_smtp(to: str, subject: str, text: str, html_body: str) -> Sent:
    """Through an ordinary mailbox. One connection, one message, then closed.

    No connection pooling on purpose. A serverless invocation is frozen the
    moment it answers, and a socket held open across invocations is a socket
    that is dead by the time the next one wants it.
    """
    settings = smtp_settings()
    if settings["port"] in BLOCKED_PORTS:
        return Sent(
            ok=False,
            skipped=True,
            detail=(
                f"port {settings['port']} is blocked in most hosting, this "
                f"one included. Use 587, or 465 for implicit TLS."
            ),
        )

    # Checked before dialling. smtplib raises UnicodeEncodeError deep inside
    # the AUTH exchange, naming a position in a string nobody has seen.
    for label, value in (
        ("ATS_SMTP_USER", settings["user"]),
        ("ATS_SMTP_PASSWORD", settings["password"]),
    ):
        complaint = _not_ascii(label, value)
        if complaint:
            return Sent(ok=False, skipped=True, detail=complaint)

    sender = mail_from() or settings["user"]
    # Gmail and most providers refuse to send as an address the session did not
    # authenticate as. Saying so beats a provider error nobody can read.
    _, sender_address = parseaddr(sender)
    if sender_address.lower() != settings["user"].lower():
        return Sent(
            ok=False,
            skipped=True,
            detail=(
                f"ATS_MAIL_FROM is {sender_address!r} but the mailbox signing "
                f"in is {settings['user']!r}. Most providers refuse to send as "
                f"an address they did not authenticate as - make the two match."
            ),
        )

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    try:
        if settings["port"] == 465:
            server = smtplib.SMTP_SSL(
                settings["host"], settings["port"],
                timeout=TIMEOUT_SECONDS, context=context,
            )
        else:
            server = smtplib.SMTP(
                settings["host"], settings["port"], timeout=TIMEOUT_SECONDS
            )
        with server:
            if settings["port"] != 465:
                server.starttls(context=context)
            server.login(settings["user"], settings["password"])
            server.send_message(message)
        return Sent(ok=True)
    except smtplib.SMTPAuthenticationError as exc:
        # By far the most common failure, and the provider's own wording for it
        # is unhelpful. The password is not in this message - only the fact
        # that it was refused.
        return Sent(
            ok=False,
            detail=(
                f"the mailbox refused the sign-in ({exc.smtp_code}). For Gmail "
                f"this means ATS_SMTP_PASSWORD is not an App Password, or "
                f"2-Step Verification is off on the account."
            ),
        )
    except Exception as exc:  # noqa: BLE001 - a mail outage is not an error here
        return Sent(ok=False, detail=f"{type(exc).__name__}: {exc}"[:200])


# --------------------------------------------------------------------------
# The two messages
# --------------------------------------------------------------------------
def _page(body: str) -> str:
    return (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
        'font-size:15px;line-height:1.55;color:#111;max-width:34rem">'
        f"{body}</div>"
    )


def application_received(application, posting) -> Sent:
    """The receipt. Says what happens next, and promises nothing about outcome.

    A CV sent without choosing a role gets the same message with the role taken
    out of it. The holding pen is titled "Applicants without a job description"
    - a name written for the recruiter's list, and one that reads like a
    rejection when it turns up in a stranger's inbox.
    """
    name = safe_name(application.full_name)
    first = html.escape(name.split(" ")[0] or "there")
    plain_first = name.split(" ")[0] or "there"
    no_role = posting.slug == UNASSIGNED_SLUG

    subject = (
        "Application received - ACUD"
        if no_role
        else f"Application received - {posting.title}"
    )
    opening_text = (
        "Your CV has been received and is with the hiring team."
        if no_role
        else f"Your application for {posting.title} has been received, along "
        f"with your CV."
    )
    opening_html = (
        "Your CV has been received and is with the hiring team."
        if no_role
        else f"Your application for <strong>{html.escape(posting.title)}</strong> "
        f"has been received, along with your CV."
    )
    next_step = (
        "It will be kept on file and looked at when a role it suits opens. If "
        "there is one, somebody will contact you at this address."
        if no_role
        else "The hiring team reviews applications as they come in. If your "
        "experience fits what the role needs, somebody will contact you at "
        "this address."
    )

    text = (
        f"Hello {plain_first},\n\n"
        f"{opening_text}\n\n"
        f"{next_step}\n\n"
        f"This message is automatic - there is no need to reply to it."
    )
    body = _page(
        f"<p>Hello {first},</p>"
        f"<p>{opening_html}</p>"
        f"<p>{next_step}</p>"
        f'<p style="color:#666;font-size:13px">This message is automatic - '
        f"there is no need to reply to it.</p>"
    )
    return send(application.email, subject, text, body)


def new_applications_digest(posting, rows: list) -> list[Sent]:
    """One summary to the hiring team, not one email per applicant.

    A vacancy that attracts two hundred people would otherwise produce two
    hundred emails, which is how a team learns to ignore the notifications.
    """
    recipients = hr_emails()
    if not recipients or not rows:
        return []

    accepted = [r for r in rows if r.tier == "accepted"]
    waiting = [r for r in rows if r.tier == "waiting_list"]
    unreadable = [r for r in rows if r.status in {"failed", "not_a_cv"}]

    headline = (
        f"{len(rows)} new application{'s' if len(rows) != 1 else ''} "
        f"for {posting.title}"
    )
    lines = [
        f"{len(accepted)} accepted, {len(waiting)} on the waiting list, "
        f"{len(rows) - len(accepted) - len(waiting)} below the bar."
    ]
    if unreadable:
        lines.append(
            f"{len(unreadable)} could not be read as a CV and need a person to look."
        )

    top = sorted(accepted, key=lambda r: -r.percent)[:5]
    text_rows = "\n".join(
        f"  {r.percent}%  {safe_name(r.full_name)}  <{r.email}>" for r in top
    )
    html_rows = "".join(
        f"<li><strong>{r.percent}%</strong> {html.escape(safe_name(r.full_name))} "
        f"&lt;{html.escape(r.email)}&gt;</li>"
        for r in top
    )

    text = (
        f"{headline}\n\n" + "\n".join(lines) +
        (f"\n\nHighest matches:\n{text_rows}" if top else "") +
        "\n\nOpen the dashboard to see the reasoning behind each one."
    )
    body = _page(
        f"<p><strong>{html.escape(headline)}</strong></p>"
        + "".join(f"<p>{html.escape(line)}</p>" for line in lines)
        + (f"<p>Highest matches:</p><ul>{html_rows}</ul>" if top else "")
        + '<p style="color:#666;font-size:13px">Open the dashboard to see the '
          "reasoning behind each one.</p>"
    )

    return [send(address, headline, text, body) for address in recipients]


def alert_emails() -> list[str]:
    """Who gets the alert digest.

    Falls back to the hiring-team list rather than to nobody: a deployment that
    set one address list and not the other meant to be told something, and
    silently sending to no one is the failure mode this whole feature exists to
    avoid.
    """
    raw = os.getenv("ATS_ALERT_EMAILS") or ""
    found = [e.strip() for e in raw.split(",") if _EMAIL.match(e.strip())]
    return found or hr_emails()


_LEVEL_MARK = {"critical": "🔴", "warning": "🟡", "info": "🟢"}
_LEVEL_WORD = {"critical": "Critical", "warning": "Warning", "info": "Note"}
_LEVEL_COLOUR = {"critical": "#c52027", "warning": "#a15c00", "info": "#4b7f52"}


def alert_digest(alerts: list, base_url: str = "", subject_prefix: str = "") -> list[Sent]:
    """One email carrying every open finding, to whoever is on the alert list.

    Deliberately one message and not one per alert. A quiet week produces
    nothing at all - an alert mail that arrives whether or not anything is
    wrong teaches its readers that it never is.

    `alerts` are `ats.alerts.Alert` objects. They are formatted here rather than
    passed as text so that the mail and the dashboard cannot describe the same
    finding differently.
    """
    recipients = alert_emails()
    if not recipients or not alerts:
        return []

    critical = [a for a in alerts if a.level == "critical"]
    warning = [a for a in alerts if a.level == "warning"]

    if critical:
        headline = (
            f"{len(critical)} critical workforce alert"
            f"{'' if len(critical) == 1 else 's'}"
        )
    elif warning:
        headline = (
            f"{len(warning)} workforce alert{'' if len(warning) == 1 else 's'}"
        )
    else:
        headline = f"{len(alerts)} workforce note{'' if len(alerts) == 1 else 's'}"

    lines = [headline, "=" * len(headline), ""]
    body = [
        f'<p style="margin:0 0 4px"><strong style="font-size:17px">'
        f"{html.escape(headline)}</strong></p>",
        '<p style="margin:0 0 18px;color:#666;font-size:13px">'
        "From the ACUD hiring and workforce dashboard.</p>",
    ]

    for alert in alerts:
        mark = _LEVEL_MARK.get(alert.level, "•")
        word = _LEVEL_WORD.get(alert.level, alert.level.title())
        where = f" · {alert.department}" if alert.department else ""

        lines.append(f"{mark} {word}{where}")
        lines.append(f"   {alert.title}")
        lines.append(f"   {alert.detail}")
        if base_url and alert.action_href:
            lines.append(f"   {base_url.rstrip('/')}{alert.action_href}")
        lines.append("")

        link = ""
        if base_url and alert.action_href:
            href = html.escape(f"{base_url.rstrip('/')}{alert.action_href}")
            link = (
                f'<a href="{href}" style="color:#ed1c24;text-decoration:none;'
                f'font-weight:600;font-size:13px">'
                f"{html.escape(alert.action_label or 'Open')} &rarr;</a>"
            )

        body.append(
            f'<div style="border-left:3px solid {_LEVEL_COLOUR.get(alert.level, "#ddd")};'
            f'background:#fafafa;padding:12px 14px;margin:0 0 10px;border-radius:6px">'
            f'<div style="font-size:12px;color:#666;text-transform:uppercase;'
            f'letter-spacing:.04em">{html.escape(word)}{html.escape(where)}'
            f" &middot; {html.escape(alert.source.title())}</div>"
            f'<div style="font-weight:600;margin-top:4px">{html.escape(alert.title)}</div>'
            f'<div style="color:#444;margin-top:4px;font-size:14px">'
            f"{html.escape(alert.detail)}</div>"
            + (f'<div style="margin-top:8px">{link}</div>' if link else "")
            + "</div>"
        )

    # The same caveat the dashboard carries. An emailed number travels further
    # than the page it came from and arrives without its context.
    lines += [
        "",
        "Findings marked Forecast rest on a frozen workforce model, not live HR "
        "data. Findings marked Live are current as of the moment this was sent.",
    ]
    body.append(
        '<p style="color:#666;font-size:12px;line-height:1.5;margin-top:16px">'
        "Findings marked <strong>Forecast</strong> rest on a frozen workforce "
        "model - trained once and unchanged since - not on live HR data. "
        "Findings marked <strong>Live</strong> are current as of the moment "
        "this was sent.</p>"
    )

    subject = f"{subject_prefix}{headline}" if subject_prefix else headline
    return [send(address, subject, "\n".join(lines), _page("".join(body)))
            for address in recipients]
