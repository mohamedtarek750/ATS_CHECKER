"""Replay a finished report against different settings, with no API calls.

A run already recorded every score. This re-applies the accept/reject rules at
other thresholds so you can see exactly who each setting would have rejected -
by name - before you commit to it.

    python eval/tune.py                          # latest report, a sweep
    python eval/tune.py --threshold 70           # who does this drop?
    python eval/tune.py --min-quality 85 --threshold 70
    python eval/tune.py --report path/to/report.json
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ats.config import Settings  # noqa: E402


def latest_report(settings: Settings) -> Path | None:
    found = sorted(glob.glob(str(settings.reports_dir / "report_*.json")))
    return Path(found[-1]) if found else None


def load(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    # Only rows that were actually judged carry usable scores.
    return [r for r in data["results"] if r["status"] != "error"]


def verdict_at(
    row: dict, ai_threshold: int, min_quality: int, min_format: int, min_prof: int = 0
) -> str:
    """Re-apply the rules in the same priority order as ats/decision.py."""
    if row["reason"] in {"not_a_cv", "unreadable", "insufficient_content"}:
        return row["reason"]
    if row["ai_generated_score"] >= ai_threshold:
        return "ai_generated"
    if min_format and row["format_score"] < min_format:
        return "poor_structure"
    if min_prof and row.get("professionalism_score", 100) < min_prof:
        return "unprofessional"
    if min_quality and row["quality_score"] < min_quality:
        return "low_quality"
    return "accepted"


def sweep(rows: list[dict]) -> None:
    print("\nAI threshold sweep - how many CVs get rejected as AI-generated\n")
    print(f"  {'threshold':>10}  {'rejected':>9}  {'accepted':>9}   who gets rejected")
    print("  " + "-" * 84)
    for threshold in (50, 60, 65, 70, 75, 80, 85, 90):
        dropped = [r for r in rows if r["ai_generated_score"] >= threshold]
        names = ", ".join(Path(r["filename"]).stem[:22] for r in dropped[:3])
        more = f" +{len(dropped)-3} more" if len(dropped) > 3 else ""
        print(f"  {threshold:>10}  {len(dropped):>9}  {len(rows)-len(dropped):>9}   "
              f"{names}{more}")

    print("\nQuality bar sweep - how many get rejected as below standard\n")
    print(f"  {'min quality':>11}  {'rejected':>9}  {'accepted':>9}")
    print("  " + "-" * 40)
    for bar in (0, 60, 65, 70, 75, 80, 85, 90):
        dropped = [r for r in rows if bar and r["quality_score"] < bar]
        print(f"  {bar:>11}  {len(dropped):>9}  {len(rows)-len(dropped):>9}")


def show(rows: list[dict], ai: int, quality: int, fmt: int, prof: int = 0) -> None:
    results = [(r, verdict_at(r, ai, quality, fmt, prof)) for r in rows]
    accepted = [r for r, v in results if v == "accepted"]
    rejected = [(r, v) for r, v in results if v != "accepted"]

    print(f"\nSettings: AI threshold {ai}"
          + (f", min quality {quality}" if quality else "")
          + (f", min format {fmt}" if fmt else ""))
    print(f"Accepted {len(accepted)} / {len(rows)}   Rejected {len(rejected)}\n")

    if rejected:
        print("  REJECTED")
        for row, reason in sorted(rejected, key=lambda x: -x[0]["ai_generated_score"]):
            print(f"    {row['filename'][:46]:<48} {reason:<16} "
                  f"ai={row['ai_generated_score']:>3} qual={row['quality_score']:>3}")
    if accepted:
        print("\n  ACCEPTED (best first)")
        for row in sorted(accepted, key=lambda r: -r["quality_score"]):
            print(f"    {row['filename'][:46]:<48} {row['role_label'][:24]:<26} "
                  f"ai={row['ai_generated_score']:>3} qual={row['quality_score']:>3}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a report at other settings.")
    parser.add_argument("--report", default=None)
    parser.add_argument("--threshold", type=int, default=None, help="AI reject threshold.")
    parser.add_argument("--min-quality", type=int, default=0)
    parser.add_argument("--min-format", type=int, default=0)
    parser.add_argument("--min-professionalism", type=int, default=0)
    args = parser.parse_args()

    settings = Settings()
    path = Path(args.report) if args.report else latest_report(settings)
    if path is None or not path.exists():
        print(f"No report found in {settings.reports_dir}. Run a screening first.")
        return 1

    rows = load(path)
    if not rows:
        print(f"{path} has no scored CVs in it.")
        return 1

    print(f"Report: {path}")
    print(f"CVs   : {len(rows)}")

    if (args.threshold is None and not args.min_quality and not args.min_format
            and not args.min_professionalism):
        sweep(rows)
        print("\nThen pick a setting and see exactly who it drops:")
        print("  python eval/tune.py --threshold 70")
        print("  python eval/tune.py --threshold 70 --min-quality 85")
        print("\nNothing here re-screens anything - it replays scores already recorded.")
        return 0

    show(rows, args.threshold or settings.ai_threshold, args.min_quality,
         args.min_format, args.min_professionalism)
    print("\nApply it for real with:")
    bits = [f"--threshold {args.threshold or settings.ai_threshold}"]
    if args.min_quality:
        bits.append(f"--min-quality {args.min_quality}")
    if args.min_format:
        bits.append(f"--min-format {args.min_format}")
    if args.min_professionalism:
        bits.append(f"--min-professionalism {args.min_professionalism}")
    print(f"  python ats_cli.py --input data/inbox {' '.join(bits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
