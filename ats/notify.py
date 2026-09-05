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
  3. With no API key configured, nothing is sent and nothing fails. The whole
     feature is optional.

    RESEND_API_KEY=re_...
    ATS_MAIL_FROM="Careers <careers@yourdomain.com>"   # a verified domain
    ATS_HR_EMAILS=hr@company.com,lead@company.com
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .postings import UNASSIGNED_SLUG

RESEND_ENDPOINT = "https://api.resend.com/emails"
TIMEOUT_SECONDS = 10

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


def is_configured() -> bool:
    return bool(api_key() and mail_from())


def status() -> dict:
    return {
        "configured": is_configured(),
        "from": mail_from() if is_configured() else "",
        "hr_recipients": len(hr_emails()),
    }


def safe_name(name: str) -> str:
    """A person's name, fit to put in a subject line. One line, bounded."""
    return _HEADER_BREAK.sub(" ", name).strip()[:80]


def send(to: str, subject: str, text: str, html_body: str) -> Sent:
    """One email. Returns what happened; never raises at the caller."""
    if not is_configured():
        return Sent(ok=False, skipped=True, detail="no mail provider configured")
    if not _EMAIL.match(to.strip()):
        return Sent(ok=False, skipped=True, detail=f"not a usable address: {to!r}")

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
