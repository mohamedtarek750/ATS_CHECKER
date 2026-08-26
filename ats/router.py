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
    # Unscreened files are held on their own, never mixed into rejected/.
    if decision.errored:
        return settings.unscreened_dir
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


# Files that live in the managed folders but are not CVs, and must survive a clear.
KEEP_ALWAYS = {".gitkeep", ".gitignore"}


def clear_files(directory: Path, extensions: set[str] | None = None) -> tuple[int, int]:
    """Delete CV files directly inside `directory`. Returns (deleted, bytes freed).

    Deliberately narrow, because this is the one destructive path in the project:
      * only files, never directories, and never recursively;
      * only extensions the pipeline itself accepts, so nothing unrelated that
        happens to share the folder is touched;
      * .gitkeep and .gitignore always survive.
    """
    from .config import SUPPORTED_EXTENSIONS

    allowed = extensions or SUPPORTED_EXTENSIONS
    directory = Path(directory)
    if not directory.is_dir():
        return (0, 0)

    deleted = freed = 0
    for entry in directory.iterdir():
        if not entry.is_file() or entry.name in KEEP_ALWAYS:
            continue
        if entry.suffix.lower() not in allowed:
            continue
        try:
            size = entry.stat().st_size
            entry.unlink()
        except OSError:
            continue
        deleted += 1
        freed += size
    return (deleted, freed)


def clear_results(settings: Settings) -> int:
    """Remove the accepted/, rejected/, _unscreened/ and _reports/ trees.

    Only ever touches directories this project created inside output_dir.
    """
    removed = 0
    for target in (
        settings.accepted_dir,
        settings.rejected_dir,
        settings.unscreened_dir,
        settings.reports_dir,
    ):
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            removed += 1
    return removed


def prepare_tree(settings: Settings, role_folders: list[str] | None = None) -> None:
    """Create the accepted/ and rejected/ skeleton up front."""
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    for base in (settings.accepted_dir, settings.rejected_dir):
        base.mkdir(parents=True, exist_ok=True)
        for folder in role_folders or []:
            (base / folder).mkdir(parents=True, exist_ok=True)
