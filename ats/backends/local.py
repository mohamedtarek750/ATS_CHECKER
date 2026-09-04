"""Storage on the local disk. The default, and how the app runs with no Google.

Plain JSON and the original files in a directory, so everything is inspectable
with a text editor and nothing is locked inside a service. This is what runs in
development, in the tests, and on any machine where you would rather applicants'
CVs did not leave it.
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from ..config import PROJECT_ROOT
from ..job_profile import JobProfile
from ..models import CandidateProfile
from ..postings import Application, JobPosting


class LocalBackend:
    """Files under one directory:

        postings/<slug>.json          the vacancy and its checklist
        applications/<slug>.json      every application to it, in order
        cvs/<application id>.<ext>    the CV exactly as it was uploaded
        profiles/<application id>.json  what stage 2 read out of it
    """

    name = "local files"

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or PROJECT_ROOT / "data" / "hiring")
        # One writer at a time. These are whole-file rewrites, and two requests
        # landing together would otherwise lose one of them.
        self._lock = threading.Lock()
        for folder in ("postings", "applications", "cvs", "profiles"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    # -- postings ---------------------------------------------------------
    def _posting_path(self, slug: str) -> Path:
        return self.root / "postings" / f"{slug}.json"

    def postings(self) -> list[JobPosting]:
        found = []
        for path in sorted((self.root / "postings").glob("*.json")):
            found.append(self._read_posting(path))
        found.sort(key=lambda p: p.created, reverse=True)
        return found

    @staticmethod
    def _read_posting(path: Path) -> JobPosting:
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["profile"] = JobProfile(**raw["profile"])
        return JobPosting(**raw)

    def posting(self, slug: str) -> JobPosting | None:
        path = self._posting_path(slug)
        return self._read_posting(path) if path.exists() else None

    def save_posting(self, posting: JobPosting) -> JobPosting:
        with self._lock:
            payload = {
                **posting.__dict__,
                "profile": json.loads(posting.profile.model_dump_json()),
            }
            self._posting_path(posting.slug).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        return posting

    # -- applications -----------------------------------------------------
    def _applications_path(self, job_slug: str) -> Path:
        return self.root / "applications" / f"{job_slug}.json"

    def applications(self, job_slug: str) -> list[Application]:
        path = self._applications_path(job_slug)
        if not path.exists():
            return []
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [Application(**row) for row in rows]

    def _write_applications(self, job_slug: str, rows: list[Application]) -> None:
        self._applications_path(job_slug).write_text(
            json.dumps([r.__dict__ for r in rows], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def application(self, application_id: str) -> Application | None:
        for posting in self.postings():
            for row in self.applications(posting.slug):
                if row.id == application_id:
                    return row
        return None

    def add_application(
        self, application: Application, cv_bytes: bytes, filename: str
    ) -> Application:
        suffix = Path(filename).suffix.lower() or ".pdf"
        target = self.root / "cvs" / f"{application.id}{suffix}"
        target.write_bytes(cv_bytes)

        application.cv_filename = filename
        application.cv_ref = target.name
        application.cv_url = f"/api/cv-file/{application.id}"

        with self._lock:
            rows = self.applications(application.job_slug)
            rows.append(application)
            self._write_applications(application.job_slug, rows)
        return application

    def update_application(self, application: Application) -> None:
        with self._lock:
            rows = self.applications(application.job_slug)
            for index, row in enumerate(rows):
                if row.id == application.id:
                    rows[index] = application
                    break
            else:
                # Not in this vacancy's file. Either it is new, or it has just
                # been moved here from another vacancy - and this layout keeps
                # one file per vacancy, so the row it left behind has to go or
                # the applicant shows up in two places at once.
                self._forget_elsewhere(application)
                rows.append(application)
            self._write_applications(application.job_slug, rows)

    def _forget_elsewhere(self, application: Application) -> None:
        """Drop this id from any other vacancy's file.

        Only ever runs when the row was not where it said it was, so the
        ordinary update path never pays for the scan. There are as many files
        as vacancies, which is a small number by construction.
        """
        folder = self.root / "applications"
        if not folder.exists():
            return
        for path in folder.glob("*.json"):
            if path.stem == application.job_slug:
                continue
            rows = self.applications(path.stem)
            kept = [row for row in rows if row.id != application.id]
            if len(kept) != len(rows):
                self._write_applications(path.stem, kept)

    # -- what stage 2 read, and the file itself ---------------------------
    def profile(self, application_id: str) -> CandidateProfile | None:
        path = self.root / "profiles" / f"{application_id}.json"
        if not path.exists():
            return None
        return CandidateProfile(**json.loads(path.read_text(encoding="utf-8")))

    def save_profile(self, application_id: str, profile: CandidateProfile) -> None:
        (self.root / "profiles" / f"{application_id}.json").write_text(
            profile.model_dump_json(indent=2), encoding="utf-8"
        )

    def cv_bytes(self, application_id: str) -> bytes | None:
        matches = list((self.root / "cvs").glob(f"{application_id}.*"))
        return matches[0].read_bytes() if matches else None

    # -- for the tests ----------------------------------------------------
    def wipe(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
