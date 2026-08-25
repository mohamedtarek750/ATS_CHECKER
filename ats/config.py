"""Configuration: role taxonomy, tunable thresholds, and paths."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional, only to load a local .env during development
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


# --------------------------------------------------------------------------
# Role taxonomy
# --------------------------------------------------------------------------
# `label` is what the LLM is allowed to choose from (singular, human readable).
# `folder` is the directory name used on disk (plural, filesystem safe).
ROLE_TAXONOMY: list[dict[str, str]] = [
    # --- Data / AI ---
    {"label": "Data Scientist", "folder": "Data_Scientists"},
    {"label": "Data Analyst", "folder": "Data_Analysts"},
    {"label": "Data Engineer", "folder": "Data_Engineers"},
    {"label": "Machine Learning Engineer", "folder": "Machine_Learning_Engineers"},
    {"label": "AI Engineer", "folder": "AI_Engineers"},
    {"label": "Business Intelligence Analyst", "folder": "BI_Analysts"},
    {"label": "Data Entry Specialist", "folder": "Data_Entry_Specialists"},
    # --- Software ---
    {"label": "Frontend Developer", "folder": "Frontend_Developers"},
    {"label": "Backend Developer", "folder": "Backend_Developers"},
    {"label": "Full Stack Developer", "folder": "Full_Stack_Developers"},
    {"label": "Mobile Developer", "folder": "Mobile_Developers"},
    {"label": "Game Developer", "folder": "Game_Developers"},
    {"label": "Embedded Systems Engineer", "folder": "Embedded_Engineers"},
    {"label": "Software Engineer", "folder": "Software_Engineers"},
    {"label": "QA / Test Engineer", "folder": "QA_Engineers"},
    # --- Infrastructure / Security ---
    {"label": "DevOps Engineer", "folder": "DevOps_Engineers"},
    {"label": "Cloud Engineer", "folder": "Cloud_Engineers"},
    {"label": "Cybersecurity Engineer", "folder": "Cybersecurity_Engineers"},
    {"label": "Network Engineer", "folder": "Network_Engineers"},
    {"label": "Database Administrator", "folder": "Database_Administrators"},
    {"label": "IT Support Specialist", "folder": "IT_Support_Specialists"},
    # --- Product / Business ---
    {"label": "Product Manager", "folder": "Product_Managers"},
    {"label": "Project Manager", "folder": "Project_Managers"},
    {"label": "Business Analyst", "folder": "Business_Analysts"},
    {"label": "UI/UX Designer", "folder": "UI_UX_Designers"},
    {"label": "Graphic Designer", "folder": "Graphic_Designers"},
    {"label": "Digital Marketing Specialist", "folder": "Digital_Marketing_Specialists"},
    {"label": "Sales Representative", "folder": "Sales_Representatives"},
    {"label": "HR Specialist", "folder": "HR_Specialists"},
    {"label": "Accountant", "folder": "Accountants"},
    # --- Non-software engineering (ACUD gets a lot of these) ---
    {"label": "Civil Engineer", "folder": "Civil_Engineers"},
    {"label": "Architect", "folder": "Architects"},
    {"label": "Mechanical Engineer", "folder": "Mechanical_Engineers"},
    {"label": "Electrical Engineer", "folder": "Electrical_Engineers"},
    # --- Fallbacks ---
    {"label": "Other", "folder": "Other"},
    {"label": "Undetermined", "folder": "Undetermined"},
]

ROLE_LABELS: list[str] = [r["label"] for r in ROLE_TAXONOMY]
LABEL_TO_FOLDER: dict[str, str] = {r["label"]: r["folder"] for r in ROLE_TAXONOMY}

# Rejection reasons the pipeline understands.
REJECT_REASONS: list[str] = [
    "not_a_cv",           # invoice, cover letter, essay, screenshot, random file
    "ai_generated",       # written by an LLM
    "unreadable",         # encrypted / scanned with no text / corrupt
    "insufficient_content",  # a CV, but far too thin to evaluate
]

# Not a rejection. The CV never reached a verdict (no API key, rate limit, network
# failure), so it must never be filed as though a human judgement went against it.
SCREENING_FAILED = "screening_failed"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    """Runtime settings. Every field can be overridden by an env var."""

    # --- Claude ---
    model: str = field(default_factory=lambda: os.getenv("ATS_MODEL", "claude-opus-5"))
    effort: str = field(default_factory=lambda: os.getenv("ATS_EFFORT", "medium"))
    max_tokens: int = field(default_factory=lambda: _env_int("ATS_MAX_TOKENS", 8000))

    # --- Decision thresholds ---
    # A CV scoring >= this on ai_generated_score (0-100) is rejected.
    ai_threshold: int = field(default_factory=lambda: _env_int("ATS_AI_THRESHOLD", 70))
    # A CV whose extracted text is shorter than this is treated as unreadable
    # (for PDFs we retry by sending the file itself to Claude's vision path).
    min_chars: int = field(default_factory=lambda: _env_int("ATS_MIN_CHARS", 250))
    # Below this classification confidence the CV is routed to Undetermined.
    min_role_confidence: int = field(
        default_factory=lambda: _env_int("ATS_MIN_ROLE_CONFIDENCE", 40)
    )

    # --- Paths ---
    inbox_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ATS_INBOX", "data/inbox"))
    )
    output_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ATS_OUTPUT", "data/output"))
    )

    # --- Behaviour ---
    # "copy" keeps the original in the inbox; "move" empties the inbox.
    file_action: str = field(default_factory=lambda: os.getenv("ATS_FILE_ACTION", "copy"))
    max_workers: int = field(default_factory=lambda: _env_int("ATS_MAX_WORKERS", 4))
    # When true, files are screened and reported but never copied or moved.
    dry_run: bool = False

    @property
    def accepted_dir(self) -> Path:
        return self.output_dir / "accepted"

    @property
    def rejected_dir(self) -> Path:
        return self.output_dir / "rejected"

    @property
    def unscreened_dir(self) -> Path:
        """Files that errored before a verdict existed - NOT rejections."""
        return self.output_dir / "_unscreened"

    @property
    def reports_dir(self) -> Path:
        return self.output_dir / "_reports"


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".rtf"}
