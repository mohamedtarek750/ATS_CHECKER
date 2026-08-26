"""Create a job profile from a job description, then screen CVs against it.

    # 1. turn the advert into a reviewable checklist
    python jd_cli.py new --from job_ad.txt

    # 2. read data/jobs/<name>.json, fix anything wrong, then
    python jd_cli.py screen --job Senior_Data_Analyst --input data/inbox

    python jd_cli.py list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ats import job_profile as jobs
from ats.config import Settings
from ats.decision import MATCH_FOLDERS
from ats.matcher import parse_job_description
from ats.pipeline import discover, preflight, screen_many, summarize, write_reports
from ats.providers import ClassificationError

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def print_profile(profile: jobs.JobProfile) -> None:
    print(f"\n  Title     : {profile.title}")
    print(f"  Seniority : {profile.seniority}")
    print(f"  Summary   : {profile.summary}")
    if profile.min_years_experience:
        print(f"  Min years : {profile.min_years_experience}")

    print(f"\n  MUST HAVE ({len(profile.must_haves)}) - a CV missing these is not shortlisted")
    for req in profile.must_haves:
        print(f"    [{req.kind:<13}] {req.text}")
    if not profile.must_haves:
        print("    (none - every CV will pass the bar)")

    print(f"\n  NICE TO HAVE ({len(profile.nice_to_haves)}) - never cause a rejection")
    for req in profile.nice_to_haves:
        print(f"    [{req.kind:<13}] {req.text}")
    if not profile.nice_to_haves:
        print("    (none)")


def cmd_new(args: argparse.Namespace) -> int:
    settings = Settings()
    problem = preflight(settings)
    if problem:
        print(f"Cannot start: {problem}")
        return 2

    text = (
        Path(args.source).read_text(encoding="utf-8", errors="replace")
        if args.source
        else sys.stdin.read()
    )
    if not text.strip():
        print("No job description given. Use --from <file> or pipe it on stdin.")
        return 1

    print("Reading the job description...")
    try:
        profile = parse_job_description(text, settings)
    except ClassificationError as exc:
        print(f"Could not parse it: {exc}")
        return 2

    print_profile(profile)
    path = jobs.save(profile, args.name)
    print(f"\n  Saved to {path}")
    print(
        "\n  READ THE MUST-HAVE LIST ABOVE BEFORE SCREENING ANYONE.\n"
        "  Every entry there silently removes applicants who do not have it, and\n"
        "  nobody reviews the ones that were filtered out. If something is marked\n"
        "  must-have that you would actually accept without, edit the JSON and move\n"
        "  it to \"nice_to_have\"."
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    found = jobs.available()
    if not found:
        print(f"No job profiles yet in {jobs.profiles_dir()}")
        print("Create one with:  python jd_cli.py new --from job_ad.txt")
        return 1
    print(f"{len(found)} job profile(s) in {jobs.profiles_dir()}:\n")
    for path in found:
        profile = jobs.load(path)
        print(f"  {path.stem:<40} {profile.title}  "
              f"({len(profile.must_haves)} must-have, "
              f"{len(profile.nice_to_haves)} nice-to-have)")
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    settings = Settings()
    if args.output:
        settings.output_dir = Path(args.output)
    if args.workers:
        settings.max_workers = args.workers
    settings.dry_run = args.dry_run

    try:
        profile = jobs.load(args.job)
    except (OSError, ValueError) as exc:
        print(f"Could not load job profile '{args.job}': {exc}")
        return 1

    inbox = Path(args.input) if args.input else settings.inbox_dir
    paths = discover(inbox)
    if not paths:
        print(f"No CVs found in {inbox.resolve()}")
        return 1

    problem = preflight(settings)
    if problem:
        print(f"Cannot start: {problem}")
        return 2

    print(f"Screening {len(paths)} CV(s) against: {profile.title}")
    print(f"  {len(profile.must_haves)} must-have, {len(profile.nice_to_haves)} nice-to-have")
    print(f"  Model: {settings.model} [{settings.provider}]\n")

    def on_progress(result, done: int, total: int) -> None:
        if result.errored:
            mark = "FAIL"
            detail = "not screened"
        else:
            mark = {"strong_match": "MATCH", "partial_match": "PART "}.get(
                result.overall, "NO   "
            )
            detail = f"{result.must_haves_met}/{result.must_haves_total} must-haves"
            if result.reason == "not_a_cv":
                mark, detail = "DROP ", "not a CV"
        print(f"  [{done}/{total}] {mark}  {result.filename[:44]:<46} {detail}")

    results = screen_many(paths, settings, on_progress=on_progress, profile=profile)
    stats = summarize(results)

    print(f"\n  Shortlisted : {stats['by_outcome'].get('strong_match', 0)}")
    print(f"  Partial     : {stats['by_outcome'].get('partial_match', 0)}")
    print(f"  Not a match : {stats['by_outcome'].get('not_a_match', 0)}")
    if stats["errors"]:
        print(f"  Not screened: {stats['errors']}")

    shortlist = [r for r in results if r.overall == "strong_match"]
    if shortlist:
        print("\n  SHORTLIST")
        for r in sorted(shortlist, key=lambda r: -r.must_haves_met):
            print(f"    {(r.candidate_name or r.filename)[:38]:<40} "
                  f"{r.must_haves_met}/{r.must_haves_total}  {r.summary_line()}")

    if not settings.dry_run:
        reports = write_reports(results, settings)
        print(f"\n  Filed under : {settings.output_dir / profile.slug}")
        for key in MATCH_FOLDERS.values():
            print(f"                  {key}/")
        print(f"  Report      : {reports['csv']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jd_cli", description="Screen CVs against a job description."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="Turn a job description into a job profile.")
    new.add_argument("--from", dest="source", default=None, help="File with the advert.")
    new.add_argument("--name", default=None, help="File name to save it under.")
    new.set_defaults(func=cmd_new)

    lst = sub.add_parser("list", help="List saved job profiles.")
    lst.set_defaults(func=cmd_list)

    scr = sub.add_parser("screen", help="Screen CVs against a saved job profile.")
    scr.add_argument("--job", required=True, help="Profile name or path.")
    scr.add_argument("-i", "--input", default=None)
    scr.add_argument("-o", "--output", default=None)
    scr.add_argument("--workers", type=int, default=None)
    scr.add_argument("--dry-run", action="store_true")
    scr.set_defaults(func=cmd_screen)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
