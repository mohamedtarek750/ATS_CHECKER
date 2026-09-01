"""Stage 1 - file to text. No model, no judgement, no network.

Kept separate from stage 2 so a batch can be checked for unreadable files before a
single API call is spent, and so the expensive stage never re-reads a disk.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ..config import SUPPORTED_EXTENSIONS, Settings
from ..extract import ExtractedDoc, extract
from .. import store
from ..store import doc_hash


@dataclass
class ParsedDoc:
    """One file, read. `key` identifies the content, not the filename."""

    path: Path
    key: str
    doc: ExtractedDoc

    @property
    def ok(self) -> bool:
        return not self.doc.error

    @property
    def error(self) -> str:
        return self.doc.error

    @property
    def text(self) -> str:
        return self.doc.text


def discover(inbox: Path) -> list[Path]:
    """Every supported file under `inbox`, recursively, in a stable order."""
    inbox = Path(inbox)
    if not inbox.exists():
        return []
    if inbox.is_file():
        return [inbox]
    return sorted(
        p for p in inbox.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def parse_one(path: Path, settings: Settings | None = None) -> ParsedDoc:
    """Read one file. Never raises - a failure is reported on the result."""
    doc = extract(path)
    # A PDF with no text layer still has a key: its own bytes, since there is no
    # text to hash. Stage 2 sends the file itself to the model in that case.
    if doc.needs_vision and not doc.text.strip():
        try:
            basis = path.read_bytes()[:2_000_000].decode("latin-1", "replace")
        except OSError:
            basis = path.name
    else:
        basis = doc.text
    return ParsedDoc(path=path, key=doc_hash(basis or path.name), doc=doc)


#: Below this, starting worker processes costs more than it saves. Process
#: start-up on Windows is most of a second; twenty-four CVs is about where the
#: parallel read overtakes the serial one.
_PARALLEL_FROM = 24


def parse_many(paths: list[Path], settings: Settings | None = None) -> list[ParsedDoc]:
    """Read a whole batch, across processes when the batch is worth it.

    Extracting text from a PDF is pure-Python CPU work, so threads cannot help:
    measured over a thousand real CVs, eight threads ran 1.2x faster than one and
    eight processes ran 10.9x faster. Reading is 72% of the cost of taking a CV
    in, and it is the only part paid per file, so this is the difference between
    a thousand CVs taking two minutes and taking twenty.

    Falls back to reading in this process if worker processes cannot be started -
    some sandboxes and hosts forbid them, and a slow read beats no read.
    """
    if len(paths) < _PARALLEL_FROM:
        return [parse_one(path, settings) for path in paths]

    workers = min(os.cpu_count() or 2, 8)
    if workers < 2:
        return [parse_one(path, settings) for path in paths]

    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(_parse_for_pool, paths, chunksize=8))
    except Exception:  # noqa: BLE001 - no subprocesses available, or pickling
        return [parse_one(path, settings) for path in paths]


def _parse_for_pool(path: Path) -> ParsedDoc:
    """Top-level so it can be pickled to a worker. Settings are read per process."""
    return parse_one(path)


def index_keys(paths: list[Path], settings) -> dict[Path, str]:
    """Content key per file, reading only the files we have not seen before.

    A file whose size and mtime match the index is identified from that record.
    Re-reading a thousand PDFs to answer "how many of these are new?" made every
    click in the UI cost seconds; this makes it a stat() call.
    """
    known = store.file_index(settings)
    keys: dict[Path, str] = {}
    fresh: list[tuple[Path, str]] = []

    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        record = known.get(str(path))
        if record and record[0] == stat.st_size and abs(record[1] - stat.st_mtime) < 1e-6:
            keys[path] = record[2]
            continue
        parsed = parse_one(path, settings)
        keys[path] = parsed.key
        if parsed.ok:
            fresh.append((path, parsed.key))

    store.remember_files(settings, fresh)
    return keys
