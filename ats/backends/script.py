"""Storage in a Google Sheet, through a script the sheet runs itself.

The same destination as `sheets.py` and a completely different door into it.

`sheets.py` goes through the Google Sheets API, which will not write for anybody
who cannot prove who they are - so it needs a Google Cloud project, a service
account, a key file, and both APIs switched on. That is the right shape for a
system holding real applicants, and it is a lot of setup to look at a prototype.

This one talks to an Apps Script Web app deployed from the spreadsheet. The
script runs AS THE SHEET'S OWNER, so it already has the access it needs and
there is nothing to authenticate: no cloud project, no service account, no API
key. Two settings and it works.

    ATS_BACKEND=script
    ATS_SCRIPT_URL=https://script.google.com/macros/s/AKfy.../exec
    ATS_SCRIPT_KEY=          # optional; must match SHARED_KEY in the script

The cost is that the URL is an open endpoint - whoever holds it can read and
write that sheet. For a prototype carrying test data that is a fair trade. Set
SHARED_KEY in the script and ATS_SCRIPT_KEY here before real applicants use it,
and the endpoint stops answering strangers.

The install steps live at the top of scripts/ats_sheet_backend.gs.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

from . import BackendError
from ..job_profile import JobProfile
from ..models import CandidateProfile
from ..postings import Application, JobPosting

#: Apps Script is not fast. Reading a CV back can take a few seconds.
TIMEOUT_SECONDS = 60


class ScriptError(BackendError):
    """Configuration or transport problem, said plainly enough to act on."""


#: Refusals the script sends back that mean something specific about how it was
#: installed, rather than about the request. Matched on a fragment, because the
#: rest of Google's wording is a stack trace and a documentation link.
_MEANINGS = [
    (
        "do not have permission",
        "The deployed script is running on an older authorisation than the "
        "code it now holds. Apps Script only asks for new permissions when "
        "somebody runs a function from the editor: open the script, pick "
        "`authorise` from the function list, press Run, and accept everything "
        "it asks for. Then Deploy > Manage deployments > edit > New version.",
    ),
    (
        "needs SHARED_KEY",
        "Set SHARED_KEY at the top of the script to the same value as "
        "ATS_SCRIPT_KEY. Mail and scheduling refuse without it, because that "
        "URL answers whoever holds it.",
    ),
    (
        "Unknown operation",
        "The script deployed on the sheet is older than this app. Paste the "
        "current scripts/ats_sheet_backend.gs into the editor, then Deploy > "
        "Manage deployments > edit > New version - which keeps the same URL.",
    ),
    (
        "Service invoked too many times",
        "The account has sent as much mail as Google allows it today - 100 "
        "recipients on a gmail.com account, 1,500 on Workspace. It resets 24 "
        "hours after the first message.",
    ),
]


def _explain(error: str) -> str:
    """The script's own words, and what they mean for whoever installed it."""
    for fragment, meaning in _MEANINGS:
        if fragment.lower() in error.lower():
            return f"The script refused: {error[:220]} — {meaning}"
    return f"The script refused: {error[:300]}"


class ScriptBackend:
    name = "Google Sheet (Apps Script)"

    def __init__(self) -> None:
        self.url = (os.getenv("ATS_SCRIPT_URL") or "").strip()
        self.key = (os.getenv("ATS_SCRIPT_KEY") or "").strip()
        if not self.url:
            raise ScriptError(
                "ATS_SCRIPT_URL is not set. Open the spreadsheet, go to "
                "Extensions > Apps Script, paste scripts/ats_sheet_backend.gs, "
                "then Deploy > New deployment > Web app with 'Execute as: Me' "
                "and 'Who has access: Anyone'. The URL it gives you ends in "
                "/exec - that is the value."
            )
        if "/exec" not in self.url:
            raise ScriptError(
                f"ATS_SCRIPT_URL does not look like a deployed Web app: {self.url!r}. "
                "It must end in /exec. A /dev URL only works while you are signed "
                "in, and a docs.google.com link is the spreadsheet, not the script."
            )

    # -- talking to the script --------------------------------------------
    def _call(self, op: str, **payload):
        body = dict(payload, op=op)
        if self.key:
            body["key"] = self.key

        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise ScriptError(
                f"The script returned {exc.code}. If that is 401 or 403, the "
                f"deployment's 'Who has access' is not set to Anyone."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - network, DNS, timeout
            raise ScriptError(f"Could not reach the script: {exc}") from exc

        try:
            answer = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Apps Script answers an un-deployed or unauthorised URL with an
            # HTML sign-in page, which is the single most common mistake here.
            hint = (
                " The response was a web page rather than data, which usually "
                "means the deployment is set to 'Only myself' or the URL is the "
                "/dev one."
                if raw.lstrip().startswith("<")
                else ""
            )
            raise ScriptError(f"The script did not return JSON.{hint}") from exc

        if answer.get("error"):
            raise ScriptError(_explain(str(answer["error"])))
        return answer.get("result")

    def check(self) -> dict:
        """Prove the whole path works before anybody depends on it."""
        return self._call("ping") or {}

    # -- the script as a mail relay and a scheduler ------------------------
    #
    # Both live on this class because they are the same script, reached the
    # same way, and the two mistakes people make - a /dev URL, and a
    # deployment set to "Only myself" - produce the same two errors _call
    # already knows how to explain.

    def send_mail(
        self,
        to: str,
        subject: str,
        text: str,
        html: str,
        name: str = "",
        reply_to: str = "",
    ) -> dict:
        """One email, sent by the script as the sheet's owner."""
        return self._call(
            "send_mail", to=to, subject=subject, text=text, html=html,
            name=name, replyTo=reply_to,
        ) or {}

    def schedule(self) -> dict:
        """When the daily run happens, and on whose clock."""
        return self._call("get_schedule") or {}

    def set_schedule(self, hour: int, url: str, secret: str) -> dict:
        return self._call(
            "set_schedule", hour=hour, url=url, secret=secret
        ) or {}

    def clear_schedule(self) -> dict:
        return self._call("clear_schedule") or {}

    # -- postings ----------------------------------------------------------
    @staticmethod
    def _to_posting(record: dict) -> JobPosting:
        return JobPosting(
            slug=record.get("slug", ""),
            title=record.get("title", ""),
            summary=record.get("summary", ""),
            profile=JobProfile.model_validate_json(record["profile_json"])
            if record.get("profile_json")
            else JobProfile(
                title=record.get("title", ""), seniority="", summary="",
                min_years_experience=0, requirements=[],
            ),
            status=record.get("status") or "open",
            created=record.get("created", ""),
            created_by=record.get("created_by", ""),
        )

    def postings(self) -> list[JobPosting]:
        found = [self._to_posting(r) for r in (self._call("postings") or [])]
        found.sort(key=lambda p: p.created, reverse=True)
        return found

    def posting(self, slug: str) -> JobPosting | None:
        return next((p for p in self.postings() if p.slug == slug), None)

    def save_posting(self, posting: JobPosting) -> JobPosting:
        self._call(
            "save_posting",
            record={
                "slug": posting.slug,
                "title": posting.title,
                "summary": posting.summary,
                "status": posting.status,
                "created": posting.created,
                "created_by": posting.created_by,
                "profile_json": posting.profile.model_dump_json(),
            },
        )
        return posting

    def delete_posting(self, slug: str) -> int:
        removed = self._call("delete_posting", slug=slug) or {}
        return int(removed.get("applications") or 0)

    # -- applications ------------------------------------------------------
    @staticmethod
    def _to_application(record: dict) -> Application:
        def number(name: str) -> float:
            try:
                return float(record.get(name) or 0)
            except (TypeError, ValueError):
                return 0.0

        return Application(
            id=record.get("id", ""),
            job_slug=record.get("job_slug", ""),
            full_name=record.get("full_name", ""),
            email=record.get("email", ""),
            phone=record.get("phone", ""),
            applied_at=record.get("applied_at", ""),
            cv_filename=record.get("cv_filename", ""),
            cv_ref=record.get("cv_ref", ""),
            cv_url=record.get("cv_url", ""),
            status=record.get("status") or "pending",  # type: ignore[arg-type]
            detail=record.get("detail", ""),
            read_at=record.get("read_at", ""),
            percent=int(number("percent")),
            required_percent=int(number("required_percent")),
            preferred_percent=int(number("preferred_percent")),
            tier=record.get("tier", ""),
            reason=record.get("reason", ""),
            engine_version=record.get("engine_version", ""),
            decision=record.get("decision") or "new",  # type: ignore[arg-type]
            decided_by=record.get("decided_by", ""),
            decided_at=record.get("decided_at", ""),
            note=record.get("note", ""),
            security_flags=[
                line for line in (record.get("security_flags", "") or "").split(" | ")
                if line
            ],
        )

    @staticmethod
    def _to_record(application: Application) -> dict:
        record = {}
        for field in (
            "id", "job_slug", "full_name", "email", "phone", "applied_at",
            "cv_filename", "cv_ref", "cv_url", "status", "detail", "read_at",
            "percent", "required_percent", "preferred_percent", "tier", "reason",
            "engine_version", "decision", "decided_by", "decided_at", "note",
            "security_flags",
        ):
            value = getattr(application, field, "")
            # A cell holds text. A list written straight in comes back as
            # "['a', 'b']" and does not survive the trip.
            record[field] = " | ".join(value) if isinstance(value, list) else value
        return record

    def applications(self, job_slug: str) -> list[Application]:
        rows = self._call("applications", job_slug=job_slug) or []
        return [self._to_application(r) for r in rows]

    def application(self, application_id: str) -> Application | None:
        rows = self._call("applications") or []
        record = next((r for r in rows if r.get("id") == application_id), None)
        return self._to_application(record) if record else None

    def add_application(
        self, application: Application, cv_bytes: bytes, filename: str
    ) -> Application:
        suffix = os.path.splitext(filename)[1].lower() or ".pdf"
        stored = f"{application.id}{suffix}"
        mime = {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".md": "text/plain",
            ".rtf": "application/rtf",
            ".docx": (
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
        }.get(suffix, "application/octet-stream")

        placed = self._call(
            "put_file",
            name=stored,
            mime=mime,
            data=base64.b64encode(cv_bytes).decode("ascii"),
        ) or {}

        application.cv_filename = filename
        application.cv_ref = stored
        application.cv_url = placed.get("url", "")
        self._call("save_application", record=self._to_record(application))
        return application

    def update_application(self, application: Application) -> None:
        self._call("save_application", record=self._to_record(application))

    # -- the parsed record and the file itself -----------------------------
    def profile(self, application_id: str) -> CandidateProfile | None:
        got = self._call("get_file", name=f"{application_id}.json")
        if not got:
            return None
        raw = base64.b64decode(got["data"]).decode("utf-8")
        return CandidateProfile.model_validate_json(raw)

    def save_profile(self, application_id: str, profile: CandidateProfile) -> None:
        self._call(
            "put_file",
            name=f"{application_id}.json",
            mime="application/json",
            data=base64.b64encode(
                profile.model_dump_json().encode("utf-8")
            ).decode("ascii"),
        )

    def cv_bytes(self, application_id: str) -> bytes | None:
        row = self.application(application_id)
        if row is None or not row.cv_ref:
            return None
        got = self._call("get_file", name=row.cv_ref)
        return base64.b64decode(got["data"]) if got else None
