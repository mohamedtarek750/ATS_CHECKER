"""Storage in a Google Sheet, with the files in Drive.

Chosen because a recruiter can open the sheet and read it - filter it, sort it,
send it to a colleague - without this application being in the way. That is a
real advantage and it dictates the split:

  * The SHEET holds one row per application: who applied, the decision, the
    status a person set, their notes. Small, tabular, human. This is the part
    somebody opens.
  * DRIVE holds the CV itself and the parsed profile. Blobs, never in a cell.

What is deliberately NOT stored anywhere is the per-requirement reasoning. It is
about seven kilobytes of prose per applicant; at a thousand applicants that is
seven megabytes of text in a spreadsheet, which makes the spreadsheet unopenable
and destroys the only reason to have chosen one. It is recomputed from the saved
profile in milliseconds instead.

Two limits shape the code, and both are real:

  * A cell holds 50,000 characters and a spreadsheet holds 10 million cells.
    Room for hundreds of thousands of applications at ~15 columns each.
  * The API allows 300 requests per minute. So every operation here reads or
    writes a WHOLE RANGE in one call. Writing a thousand rows one request at a
    time would exceed the quota in seconds; writing them as one batch does not.

Google Sheets is not a database. It has no transactions, so two recruiters
changing the SAME candidate at the same moment can overwrite one another.
Different candidates are unaffected, because each update writes only its own
row. This is a property of the tool, not something the code hides.

Configure with:
    ATS_BACKEND=sheets
    ATS_SHEET_ID=<the spreadsheet id from its URL>
    ATS_DRIVE_FOLDER_ID=<a Drive folder id the service account can write to>
    GOOGLE_SERVICE_ACCOUNT_JSON=<the whole key file, as one line>

Share both the sheet and the folder with the service account's email address,
which is the `client_email` field in that key.
"""

from __future__ import annotations

import io
import json
import os
import threading

from . import BackendError
from ..job_profile import JobProfile
from ..models import CandidateProfile
from ..postings import Application, JobPosting

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

POSTINGS_TAB = "postings"
APPLICATIONS_TAB = "applications"

#: Column order in the postings tab. Append only - a recruiter may have the
#: sheet open, and reordering columns would silently rewrite their data.
POSTING_COLUMNS = ["slug", "title", "summary", "status", "created", "created_by", "profile_json"]

#: Column order in the applications tab. Everything a recruiter would want to
#: read at a glance, and nothing they would not.
APPLICATION_COLUMNS = [
    "id", "job_slug", "full_name", "email", "phone", "applied_at",
    "cv_filename", "cv_ref", "cv_url",
    "status", "detail", "read_at",
    "percent", "required_percent", "preferred_percent", "tier", "reason",
    "engine_version", "decision", "decided_by", "decided_at", "note",
    "security_flags",
]


class SheetsError(BackendError):
    """Configuration or access problem, said plainly enough to act on."""


def _column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


class SheetsBackend:
    name = "Google Sheets"

    def __init__(self) -> None:
        self.sheet_id = os.getenv("ATS_SHEET_ID", "").strip()
        self.folder_id = os.getenv("ATS_DRIVE_FOLDER_ID", "").strip()
        if not self.sheet_id:
            raise SheetsError(
                "ATS_SHEET_ID is not set. Create a Google Sheet, share it with "
                "the service account's client_email, and put the id from its URL "
                "in ATS_SHEET_ID."
            )
        self._lock = threading.Lock()
        self._sheets = None
        self._drive = None

    # -- clients ----------------------------------------------------------
    def _credentials(self):
        raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw:
            raise SheetsError(
                "GOOGLE_SERVICE_ACCOUNT_JSON is not set. Paste the whole service "
                "account key file into it as a single line."
            )
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SheetsError(
                "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON - it should be the "
                "key file's entire contents."
            ) from exc

        try:
            from google.oauth2 import service_account
        except ImportError as exc:  # pragma: no cover - depends on install
            raise SheetsError(
                "The Google client libraries are not installed. Run: "
                "pip install google-api-python-client google-auth"
            ) from exc
        return service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )

    def _clients(self):
        with self._lock:
            if self._sheets is None:
                from googleapiclient.discovery import build

                creds = self._credentials()
                # cache_discovery=False: the file cache is unwritable on a
                # serverless filesystem and logs a warning on every cold start.
                self._sheets = build(
                    "sheets", "v4", credentials=creds, cache_discovery=False
                )
                self._drive = build(
                    "drive", "v3", credentials=creds, cache_discovery=False
                )
            return self._sheets, self._drive

    # -- reading and writing whole ranges ---------------------------------
    def _read_tab(self, tab: str, columns: list[str]) -> list[dict]:
        """The whole tab in ONE request. Never a request per row."""
        sheets, _ = self._clients()
        last = _column_letter(len(columns) - 1)
        try:
            response = (
                sheets.spreadsheets()
                .values()
                .get(spreadsheetId=self.sheet_id, range=f"{tab}!A2:{last}")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001 - missing tab is the common case
            if "Unable to parse range" in str(exc):
                self._ensure_tab(tab, columns)
                return []
            raise
        rows = response.get("values", [])
        out = []
        for row in rows:
            padded = list(row) + [""] * (len(columns) - len(row))
            record = dict(zip(columns, padded))
            if record.get(columns[0]):
                out.append(record)
        return out

    def _ensure_tab(self, tab: str, columns: list[str]) -> None:
        """Create the tab and write its header. Runs once, on a fresh sheet."""
        sheets, _ = self._clients()
        try:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=self.sheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": tab}}}]},
            ).execute()
        except Exception:  # noqa: BLE001 - already exists, which is fine
            pass
        sheets.spreadsheets().values().update(
            spreadsheetId=self.sheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [columns]},
        ).execute()

    def _append(self, tab: str, columns: list[str], record: dict) -> None:
        sheets, _ = self._clients()
        row = [str(record.get(c, "")) for c in columns]
        sheets.spreadsheets().values().append(
            spreadsheetId=self.sheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

    def _update_row(
        self, tab: str, columns: list[str], key_column: str, key: str, record: dict
    ) -> None:
        """Rewrite one row, found by its key. Only that row's range is touched.

        Two people editing different candidates cannot collide. Two people
        editing the SAME candidate can, and the later write wins - Sheets has no
        transactions and this does not pretend otherwise.
        """
        rows = self._read_tab(tab, columns)
        for index, existing in enumerate(rows):
            if existing.get(key_column) == key:
                sheets, _ = self._clients()
                line = index + 2  # 1-based, and row 1 is the header
                last = _column_letter(len(columns) - 1)
                sheets.spreadsheets().values().update(
                    spreadsheetId=self.sheet_id,
                    range=f"{tab}!A{line}:{last}{line}",
                    valueInputOption="RAW",
                    body={"values": [[str(record.get(c, "")) for c in columns]]},
                ).execute()
                return
        self._append(tab, columns, record)

    # -- Drive ------------------------------------------------------------
    def _upload(self, name: str, data: bytes, mime: str) -> tuple[str, str]:
        from googleapiclient.http import MediaIoBaseUpload

        _, drive = self._clients()
        metadata = {"name": name}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]
        created = (
            drive.files()
            .create(
                body=metadata,
                media_body=MediaIoBaseUpload(io.BytesIO(data), mimetype=mime),
                fields="id, webViewLink",
            )
            .execute()
        )
        return created["id"], created.get("webViewLink", "")

    def _download(self, file_id: str) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        _, drive = self._clients()
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(
            buffer, drive.files().get_media(fileId=file_id)
        )
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        return buffer.getvalue()

    def _find_in_drive(self, name: str) -> str | None:
        _, drive = self._clients()
        query = f"name = '{name}' and trashed = false"
        if self.folder_id:
            query += f" and '{self.folder_id}' in parents"
        found = (
            drive.files()
            .list(q=query, fields="files(id)", pageSize=1)
            .execute()
            .get("files", [])
        )
        return found[0]["id"] if found else None

    # -- postings ---------------------------------------------------------
    @staticmethod
    def _to_posting(record: dict) -> JobPosting:
        return JobPosting(
            slug=record["slug"],
            title=record.get("title", ""),
            summary=record.get("summary", ""),
            profile=JobProfile(**json.loads(record.get("profile_json") or "{}")),
            status=record.get("status") or "open",
            created=record.get("created", ""),
            created_by=record.get("created_by", ""),
        )

    def postings(self) -> list[JobPosting]:
        found = [self._to_posting(r) for r in self._read_tab(POSTINGS_TAB, POSTING_COLUMNS)]
        found.sort(key=lambda p: p.created, reverse=True)
        return found

    def posting(self, slug: str) -> JobPosting | None:
        return next((p for p in self.postings() if p.slug == slug), None)

    def save_posting(self, posting: JobPosting) -> JobPosting:
        record = {
            "slug": posting.slug,
            "title": posting.title,
            "summary": posting.summary,
            "status": posting.status,
            "created": posting.created,
            "created_by": posting.created_by,
            "profile_json": posting.profile.model_dump_json(),
        }
        self._update_row(POSTINGS_TAB, POSTING_COLUMNS, "slug", posting.slug, record)
        return posting

    # -- applications -----------------------------------------------------
    @staticmethod
    def _to_application(record: dict) -> Application:
        def number(name: str) -> int:
            try:
                return int(float(record.get(name) or 0))
            except (TypeError, ValueError):
                return 0

        return Application(
            id=record["id"],
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
            percent=number("percent"),
            required_percent=number("required_percent"),
            preferred_percent=number("preferred_percent"),
            tier=record.get("tier", ""),
            reason=record.get("reason", ""),
            engine_version=record.get("engine_version", ""),
            decision=record.get("decision") or "new",  # type: ignore[arg-type]
            decided_by=record.get("decided_by", ""),
            decided_at=record.get("decided_at", ""),
            security_flags=[
                line for line in (record.get("security_flags", "") or "").split(" | ")
                if line
            ],
            note=record.get("note", ""),
        )

    @staticmethod
    def _to_record(application: Application) -> dict:
        record = {}
        for column in APPLICATION_COLUMNS:
            value = getattr(application, column, "")
            # A cell holds text. A list written straight in lands as
            # "['a', 'b']" and does not survive the trip back out, so the few
            # list-valued fields are joined on the separator they are split on.
            record[column] = " | ".join(value) if isinstance(value, list) else value
        return record

    def applications(self, job_slug: str) -> list[Application]:
        rows = self._read_tab(APPLICATIONS_TAB, APPLICATION_COLUMNS)
        return [self._to_application(r) for r in rows if r.get("job_slug") == job_slug]

    def application(self, application_id: str) -> Application | None:
        rows = self._read_tab(APPLICATIONS_TAB, APPLICATION_COLUMNS)
        record = next((r for r in rows if r.get("id") == application_id), None)
        return self._to_application(record) if record else None

    def add_application(
        self, application: Application, cv_bytes: bytes, filename: str
    ) -> Application:
        suffix = os.path.splitext(filename)[1].lower() or ".pdf"
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

        file_id, link = self._upload(f"{application.id}{suffix}", cv_bytes, mime)
        application.cv_filename = filename
        application.cv_ref = file_id
        # The Drive link, so the sheet itself is useful to somebody reading it
        # there rather than in this application.
        application.cv_url = link or f"/api/cv-file/{application.id}"

        self._append(APPLICATIONS_TAB, APPLICATION_COLUMNS, self._to_record(application))
        return application

    def update_application(self, application: Application) -> None:
        self._update_row(
            APPLICATIONS_TAB, APPLICATION_COLUMNS, "id", application.id,
            self._to_record(application),
        )

    # -- the parsed profile, kept as a blob beside the CV -----------------
    def profile(self, application_id: str) -> CandidateProfile | None:
        file_id = self._find_in_drive(f"{application_id}.profile.json")
        if not file_id:
            return None
        return CandidateProfile(**json.loads(self._download(file_id)))

    def save_profile(self, application_id: str, profile: CandidateProfile) -> None:
        name = f"{application_id}.profile.json"
        existing = self._find_in_drive(name)
        if existing:
            _, drive = self._clients()
            drive.files().delete(fileId=existing).execute()
        self._upload(name, profile.model_dump_json().encode("utf-8"), "application/json")

    def cv_bytes(self, application_id: str) -> bytes | None:
        row = self.application(application_id)
        if row is None or not row.cv_ref:
            return None
        return self._download(row.cv_ref)
