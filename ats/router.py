"""Places a screened CV into accepted/<Role>/ or rejected/<Role>/."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .config import Settings
from .decision import Decision

_UNSAFE = re.compile(r'[<>:"/\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    """Windows-safe file name, trailing dots/spaces removed."""
    cleaned = _UNSAFE.sub("_", name).rstrip(" .")
    return cleaned or "unnamed"


def unique_path(directory: Path, filename: str) -> Path:
    """A path inside `directory` that does not overwrite an existing file."""
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}__{counter}{suffix}"
        counter += 1
    return candidate


def target_dir(decision: Decision, settings: Settings) -> Path:
    base = settings.accepted_dir if decision.accepted else settings.rejected_dir
    return base / decision.role_folder


def route(source: Path, decision: Decision, settings: Settings) -> Path:
    """Copy (or move) `source` into its destination folder. Returns the new path."""
    destination_dir = target_dir(decision, settings)
    destination_dir.mkdir(parents=True, exist_ok=True)

    destination = unique_path(destination_dir, safe_name(source.name))
    if settings.file_action == "move":
        shutil.move(str(source), str(destination))
    else:
        shutil.copy2(str(source), str(destination))
    return destination


def prepare_tree(settings: Settings, role_folders: list[str] | None = None) -> None:
    """Create the accepted/ and rejected/ skeleton up front."""
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    for base in (settings.accepted_dir, settings.rejected_dir):
        base.mkdir(parents=True, exist_ok=True)
        for folder in role_folders or []:
            (base / folder).mkdir(parents=True, exist_ok=True)
