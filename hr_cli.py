"""The five-stage pipeline from the command line.

    python hr_cli.py intake --input data/inbox        # stages 1-2, once per CV
    python hr_cli.py job --from job_ad.txt            # stage 3, once per vacancy
    python hr_cli.py shortlist --job Data_Analyst     # stages 4-5, free and instant
    python hr_cli.py pool                             # what is stored
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

from ats import screening, store
from ats.config import PROVIDER_NAMES, Settings
from ats.pipeline import preflight
from ats.providers import ClassificationError
from ats.stages import jobspec, parse, rank

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# Stages 1-2
# --------------------------------------------------------------------------
def cmd_intake(args: argparse.Namespace) -> int:
    if args.provider:
        os.environ["ATS_PROVIDER"] = args.provider
    settings = Settings()
    if args.workers:
        settings.max_workers = args.workers

    inbox = Path(args.input) if args.input else settings.inbox_dir
    paths = parse.discover(inbox)
    if not paths:
        print(f"No CVs found in {inbox.resolve()}")
        return 1

    pending = screening.pending_count(paths, settings)
    known = len(paths) - pending
    print(f"{len(paths)} file(s) found. {known} already in the pool, {pending} to read.")

    if pending == 0:
        print("Nothing to do - every CV here has already been read.")
        return 0

    problem = preflight(settings)
    if problem:
        print(f"Cannot start: {problem}")
        return 2

    from ats.stages.normalize import estimate_seconds

    minutes = estimate_seconds(pending, settings) / 60
    print(f"Estimated {minutes:.0f} minute(s) on {settings.model} [{settings.provider}].")
    print("Progress is saved as it goes - if this stops, run it again.\n")

    started = time.time()

    def on_progress(name: str, done: int, total: int) -> None:
        print(f"  [{done}/{total}] {name[:56]}")

    report = screening.intake(paths, settings, on_progress=on_progress)

    print(f"\n  Read and stored : {report.added}")
    print(f"  Already known   : {report.already_known}")
    if report.not_cvs:
        print(f"  Not CVs         : {report.not_cvs}")
    if report.unreadable:
        print(f"  Unreadable      : {report.unreadable}")
    if report.failed:
        print(f"  Failed          : {report.failed}  (re-run to retry)")
    print(f"  Pool now holds  : {store.stats(settings)['total']} candidate(s)")
    print(f"  Elapsed         : {time.time() - started:.0f}s")

    if report.errors:
        print("\n  Problems")
        for name, why in report.errors[:10]:
            print(f"    {name[:40]:<42} {why[:70]}")
    return 0


# --------------------------------------------------------------------------
# Stage 3
# --------------------------------------------------------------------------
def cmd_job(args: argparse.Namespace) -> int:
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
        print("No job description given. Use --from <file> or pipe it in.")
        return 1

    print("Reading the job description...")
    try:
        profile = jobspec.from_text(text, settings)
    except ClassificationError as exc:
        print(f"Could not parse it: {exc}")
        return 2

    print(f"\n  {profile.title} - {profile.seniority}")
    print(f"  {profile.summary}\n")
    print(f"  MUST HAVE ({len(profile.must_haves)})")
    for req in profile.must_haves:
        print(f"    [{req.kind:<13}] {req.text}")
    print(f"\n  NICE TO HAVE ({len(profile.nice_to_haves)})")
    for req in profile.nice_to_haves:
        print(f"    [{req.kind:<13}] {req.text}")

    path = jobspec.save(profile, args.name)
    print(f"\n  Saved to {path}")
    print(
        "\n  Check the must-have list before shortlisting anyone. Each entry removes\n"
        "  every applicant who lacks it, and nobody reviews who was removed. Move\n"
        "  anything you would hire without into \"nice_to_have\" in that file."
    )
    return 0


# --------------------------------------------------------------------------
# Stages 4-5
# --------------------------------------------------------------------------
def cmd_shortlist(args: argparse.Namespace) -> int:
    settings = Settings()
    try:
        job = jobspec.load(args.job)
    except (OSError, ValueError) as exc:
        print(f"Could not load job '{args.job}': {exc}")
        return 1

    pool = store.stats(settings)
    if pool["total"] == 0:
        print("The pool is empty. Read some CVs first:")
        print("  python hr_cli.py intake --input data/inbox")
        return 1

    started = time.time()
    ranked = screening.shortlist(job, settings)
    stats = rank.summarize(ranked)

    print(f"\n{job.title} - {pool['total']} candidate(s) in the pool, "
          f"ranked in {time.time() - started:.2f}s")
    print(f"  Shortlist    : {stats['shortlist']}")
    print(f"  Worth a look : {stats['review']}")
    print(f"  Not a match  : {stats['not_a_match']}")
    if stats["not_a_cv"]:
        print(f"  Not CVs      : {stats['not_a_cv']}")
    if stats["flagged_ai"]:
        print(f"  Flagged as possibly AI-written (review, not rejected): "
              f"{stats['flagged_ai']}")

    shown = [r for r in ranked if r.tier in ("shortlist", "review")]
    if args.all:
        shown = ranked

    print()
    for entry in shown[: args.limit]:
        flag = "  [AI?]" if entry.flagged_ai else ""
        print(f"  {rank.TIER_LABEL[entry.tier]:<13} {entry.name[:30]:<32} "
              f"{entry.match.must_met}/{entry.match.must_total}  "
              f"{entry.headline[:24]:<26}{flag}")
        if args.verbose:
            for r in entry.match.results:
                mark = {"met": "+", "partial": "~", "unclear": "?", "not_met": "-"}[r.status]
                star = "*" if r.is_must else " "
                print(f"      {star}{mark} {r.requirement[:46]:<48} {r.evidence[:34]}")
            print()

    if args.csv:
        path = Path(args.csv)
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["tier", "name", "headline", "email", "phone", "must_met",
                 "must_total", "meets", "missing", "reason", "possibly_ai", "source"]
            )
            for entry in ranked:
                c = entry.match.candidate
                writer.writerow([
                    rank.TIER_LABEL[entry.tier], entry.name, c.headline, c.email,
                    c.phone, entry.match.must_met, entry.match.must_total,
                    " | ".join(entry.match.met_labels),
                    " | ".join(entry.match.missing_labels),
                    entry.reason, "yes" if entry.flagged_ai else "",
                    entry.match.source_name,
                ])
        print(f"\n  Written to {path}")
    return 0


def cmd_pool(args: argparse.Namespace) -> int:
    settings = Settings()
    stats = store.stats(settings)
    print(f"Pool at {store.db_path(settings)}")
    print(f"  candidates : {stats['cvs']}")
    print(f"  non-CVs    : {stats['not_cvs']}")
    print(f"  total      : {stats['total']}")
    if args.forget:
        removed = store.forget_all(settings)
        print(f"\n  Removed {removed} record(s). Every CV will be read again.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hr_cli",
        description="Read CVs once, then shortlist against any vacancy instantly.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    intake = sub.add_parser("intake", help="Stages 1-2: read CVs into the pool.")
    intake.add_argument("-i", "--input", default=None)
    intake.add_argument("--workers", type=int, default=None)
    intake.add_argument(
        "--provider", default=None, choices=PROVIDER_NAMES,
        help="offline = rules, no key and no quota. ollama = a model on this "
             "machine. gemini/claude = an API.",
    )
    intake.set_defaults(func=cmd_intake)

    job = sub.add_parser("job", help="Stage 3: turn a job advert into a checklist.")
    job.add_argument("--from", dest="source", default=None)
    job.add_argument("--name", default=None)
    job.set_defaults(func=cmd_job)

    short = sub.add_parser("shortlist", help="Stages 4-5: rank the pool for a vacancy.")
    short.add_argument("--job", required=True)
    short.add_argument("--limit", type=int, default=50)
    short.add_argument("--all", action="store_true", help="Include non-matches.")
    short.add_argument("--verbose", action="store_true", help="Show every requirement.")
    short.add_argument("--csv", default=None, help="Write the full ranking to a file.")
    short.set_defaults(func=cmd_shortlist)

    pool = sub.add_parser("pool", help="What is stored.")
    pool.add_argument("--forget", action="store_true", help="Empty the pool.")
    pool.set_defaults(func=cmd_pool)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
