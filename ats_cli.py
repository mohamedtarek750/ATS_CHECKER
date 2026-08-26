"""Command-line entry point for the ACUD ATS checker.

    python ats_cli.py --input data/inbox
    python ats_cli.py --input "D:/CVs" --output "D:/screened" --move --threshold 60
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ats.config import PROVIDER_NAMES, ROLE_TAXONOMY, Settings
from ats.pipeline import discover, preflight, screen_many, summarize, write_reports
from ats.router import prepare_tree

# Windows consoles default to cp1252 and choke on CV text.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ats_cli",
        description="Screen CVs with an LLM and file them by role into accepted/rejected.",
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
    parser.add_argument(
        "--provider", default=None, choices=PROVIDER_NAMES,
        help="LLM backend. 'gemini' has a free tier; 'claude' is paid.",
    )
    parser.add_argument("--model", default=None, help="Model id for the provider.")
    parser.add_argument(
        "--min-format", type=int, default=None,
        help="Reject a CV whose structure score is below this (0 = off).",
    )
    parser.add_argument(
        "--min-quality", type=int, default=None,
        help="Reject a CV whose content score is below this (0 = off).",
    )
    parser.add_argument(
        "--min-professionalism", type=int, default=None,
        help="Reject a CV whose professionalism score is below this (0 = off).",
    )
    parser.add_argument(
        "--require", default=None,
        help="Comma-separated sections a CV must have, e.g. "
             "'contact,education,skills'. Rejects CVs missing any of them.",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Preset: --min-format 70 --min-quality 60 "
             "--require contact,education,skills.",
    )
    parser.add_argument(
        "--restart", action="store_true",
        help="Ignore the ledger and re-screen every file, including ones already done.",
    )
    parser.add_argument(
        "--list-models", action="store_true",
        help="Print the models this provider's key can actually call, then exit.",
    )
    parser.add_argument(
        "--scaffold", action="store_true",
        help="Pre-create an empty folder for every role in the taxonomy.",
    )
    return parser


def make_settings(args: argparse.Namespace) -> Settings:
    # Set the provider before constructing Settings so the model and worker count
    # resolve to that provider's defaults.
    if args.provider:
        os.environ["ATS_PROVIDER"] = args.provider
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

    if args.strict:
        settings.min_format_score = 70
        settings.min_quality_score = 60
        settings.min_professionalism_score = 70
        settings.required_sections = ("contact", "education", "skills")
    if args.min_format is not None:
        settings.min_format_score = args.min_format
    if args.min_quality is not None:
        settings.min_quality_score = args.min_quality
    if args.min_professionalism is not None:
        settings.min_professionalism_score = args.min_professionalism
    if args.require is not None:
        settings.required_sections = tuple(
            part.strip().lower() for part in args.require.split(",") if part.strip()
        )

    settings.dry_run = args.dry_run
    return settings


def list_models(settings: Settings) -> int:
    """Ask the provider what it can actually run. Model ids go stale silently."""
    from ats.providers import get_provider

    provider = get_provider(settings.provider)
    if not provider.has_credentials():
        print(f"Cannot list models: {provider.missing_credentials_message()}")
        return 2
    if not hasattr(provider, "list_models"):
        print(f"{provider.name} models: {', '.join(provider.models)}")
        return 0

    try:
        names = provider.list_models()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not list models: {exc}")
        return 2

    print(f"{provider.name} models available to this key ({len(names)}):\n")
    for name in names:
        marker = "  <- current" if name == settings.model else ""
        print(f"  {name}{marker}")
    print("\nSet one with:  ATS_MODEL=<name>  in .env,  or  --model <name>")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = make_settings(args)

    if args.list_models:
        return list_models(settings)

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

    print(
        f"Screening {len(paths)} file(s) with {settings.model} "
        f"[{settings.provider}], AI-reject threshold {settings.ai_threshold}"
    )
    bar = []
    if settings.min_format_score:
        bar.append(f"structure >= {settings.min_format_score}")
    if settings.min_quality_score:
        bar.append(f"content >= {settings.min_quality_score}")
    if settings.min_professionalism_score:
        bar.append(f"professionalism >= {settings.min_professionalism_score}")
    if settings.required_sections:
        bar.append("must have " + "/".join(settings.required_sections))
    if bar:
        print(f"Standard bar: {', '.join(bar)}")
    print()

    def on_progress(result, done: int, total: int) -> None:
        mark = "FAIL" if result.errored else "PASS" if result.accepted else "DROP"
        detail = result.role_label if result.accepted else result.reason
        print(f"  [{done}/{total}] {mark}  {result.filename}  ->  {detail}")

    results = screen_many(
        paths, settings, on_progress=on_progress, resume=not args.restart
    )
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

        # One cause usually explains the whole batch. Say it once, not N times.
        causes: dict[str, int] = {}
        for result in unscreened:
            causes[result.error] = causes.get(result.error, 0) + 1
        for cause, count in sorted(causes.items(), key=lambda kv: -kv[1]):
            print(f"\n  [{count} file(s)] {cause}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
