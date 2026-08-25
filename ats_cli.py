"""Command-line entry point for the ACUD ATS checker.

    python ats_cli.py --input data/inbox
    python ats_cli.py --input "D:/CVs" --output "D:/screened" --move --threshold 60
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ats.config import ROLE_TAXONOMY, Settings
from ats.pipeline import discover, preflight, screen_many, summarize, write_reports
from ats.router import prepare_tree

# Windows consoles default to cp1252 and choke on CV text.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ats_cli",
        description="Screen CVs with Claude and file them by role into accepted/rejected.",
    )
    parser.add_argument("-i", "--input", default=None, help="Folder (or single file) of CVs.")
    parser.add_argument("-o", "--output", default=None, help="Where accepted/ and rejected/ go.")
    parser.add_argument("--move", action="store_true", help="Move files instead of copying.")
    parser.add_argument("--dry-run", action="store_true", help="Screen and report, file nothing.")
    parser.add_argument(
        "--threshold", type=int, default=None,
        help="AI score (0-100) at or above which a CV is rejected. Default 70.",
    )
    parser.add_argument("--workers", type=int, default=None, help="Parallel screenings.")
    parser.add_argument("--model", default=None, help="Claude model id.")
    parser.add_argument(
        "--scaffold", action="store_true",
        help="Pre-create an empty folder for every role in the taxonomy.",
    )
    return parser


def make_settings(args: argparse.Namespace) -> Settings:
    settings = Settings()
    if args.input:
        settings.inbox_dir = Path(args.input)
    if args.output:
        settings.output_dir = Path(args.output)
    if args.move:
        settings.file_action = "move"
    if args.threshold is not None:
        settings.ai_threshold = args.threshold
    if args.workers is not None:
        settings.max_workers = args.workers
    if args.model:
        settings.model = args.model
    settings.dry_run = args.dry_run
    return settings


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = make_settings(args)
    folders = [r["folder"] for r in ROLE_TAXONOMY] if args.scaffold else None
    prepare_tree(settings, folders)

    paths = discover(settings.inbox_dir)
    if not paths:
        print(f"No CVs found in {settings.inbox_dir.resolve()}")
        print("Supported: .pdf .docx .txt .md .rtf")
        return 1

    # Fail once, loudly, rather than turning every CV in the batch into a failure.
    problem = preflight(settings)
    if problem:
        print(f"Cannot start: {problem}")
        return 2

    print(f"Screening {len(paths)} file(s) with {settings.model} "
          f"(AI-reject threshold {settings.ai_threshold})\n")

    def on_progress(result, done: int, total: int) -> None:
        mark = "FAIL" if result.errored else "PASS" if result.accepted else "DROP"
        detail = result.role_label if result.accepted else result.reason
        print(f"  [{done}/{total}] {mark}  {result.filename}  ->  {detail}")

    results = screen_many(paths, settings, on_progress=on_progress)
    stats = summarize(results)

    print(
        f"\nAccepted: {stats['accepted']}   Rejected: {stats['rejected']}"
        f"   Not screened: {stats['errors']}"
    )
    if stats["accepted_by_role"]:
        print("\n  Accepted by role")
        for role, count in stats["accepted_by_role"].items():
            print(f"    {role:<34} {count}")
    if stats["rejected_by_reason"]:
        print("\n  Rejected by reason")
        for reason, count in stats["rejected_by_reason"].items():
            print(f"    {reason:<34} {count}")

    if not settings.dry_run:
        reports = write_reports(results, settings)
        print(f"\nOutput  : {settings.output_dir.resolve()}")
        print(f"Report  : {reports['csv']}")

    unscreened = [r for r in results if r.errored]
    if unscreened:
        print(
            f"\n{len(unscreened)} file(s) were NOT screened. These are not "
            f"rejections - nothing was judged."
        )
        if not settings.dry_run:
            print(f"They are held in {settings.unscreened_dir}. Re-run them.")
        for result in unscreened[:10]:
            print(f"    {result.filename}: {result.error}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
