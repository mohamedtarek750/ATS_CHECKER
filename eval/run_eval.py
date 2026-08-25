"""Measure the screener's accuracy against human-labelled ground truth.

    python eval/run_eval.py
    python eval/run_eval.py --model gemini-3.5-flash --repeat 3

`--repeat` runs every CV N times and reports how often the verdict changes. That
number matters more than raw accuracy: a system that gives a different answer to the
same CV twice is not a screening tool, whatever its average score is.

Nothing here files or moves anything - it only reads and scores.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from ats.classifier import ClassificationError, classify  # noqa: E402
from ats.config import Settings  # noqa: E402
from ats.decision import decide  # noqa: E402
from ats.extract import extract  # noqa: E402
from ats.pipeline import preflight  # noqa: E402

LABELS = ROOT / "eval" / "labels.json"


def load_cases() -> list[dict]:
    data = json.loads(LABELS.read_text(encoding="utf-8"))
    return data["cases"]


def screen(case: dict, settings: Settings) -> dict | None:
    """One screening pass. Returns the observed values, or None on failure."""
    doc = extract(ROOT / case["file"])
    if doc.error:
        return {"error": doc.error}
    try:
        verdict = classify(doc, settings)
    except ClassificationError as exc:
        return {"error": str(exc)}
    decision = decide(verdict, doc, settings)
    return {
        "status": decision.status,
        "reason": decision.reason,
        "role": decision.role_label,
        "ai": verdict.ai_generated_score,
        "confidence": verdict.role_confidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the screener against labels.")
    parser.add_argument("--model", default=None)
    parser.add_argument("--provider", default=None)
    parser.add_argument(
        "--repeat", type=int, default=1,
        help="Screen each CV N times to measure how stable the verdicts are.",
    )
    args = parser.parse_args()

    settings = Settings()
    if args.provider:
        settings.provider = args.provider
    if args.model:
        settings.model = args.model

    problem = preflight(settings)
    if problem:
        print(f"Cannot start: {problem}")
        return 2

    cases = load_cases()
    print(f"Scoring {len(cases)} labelled CV(s) on {settings.model} "
          f"[{settings.provider}], {args.repeat} run(s) each\n")

    rows: list[dict] = []
    errors: list[str] = []
    started = time.time()

    for case in cases:
        name = Path(case["file"]).name
        observations = []
        for _ in range(args.repeat):
            observed = screen(case, settings)
            if observed is None or "error" in observed:
                errors.append(f"{name}: {observed.get('error') if observed else 'unknown'}")
                break
            observations.append(observed)
        if not observations:
            print(f"  ERR   {name}")
            continue

        first = observations[0]
        status_ok = first["status"] == case["status"]
        reason_ok = first["reason"] == case["reason"]
        role_ok = first["role"] in case["role"]

        # Did repeated runs agree with each other?
        stable = len({(o["status"], o["reason"], o["role"]) for o in observations}) == 1

        rows.append({
            "name": name,
            "status_ok": status_ok,
            "reason_ok": reason_ok,
            "role_ok": role_ok,
            "stable": stable,
            "expected_role": case["role"][0],
            "got_role": first["role"],
            "got_reason": first["reason"],
            "expected_reason": case["reason"],
            "ai": first["ai"],
            "human_written": case["human_written"],
        })

        mark = "ok  " if (status_ok and reason_ok and role_ok) else "MISS"
        wobble = "" if stable else "  UNSTABLE"
        print(f"  {mark}  {name:<42} {first['role']:<26} ai={first['ai']:>3}{wobble}")

    if not rows:
        print("\nNothing scored.")
        for line in errors:
            print(f"  {line}")
        return 1

    total = len(rows)
    decision_ok = sum(r["status_ok"] and r["reason_ok"] for r in rows)
    role_ok = sum(r["role_ok"] for r in rows)
    stable = sum(r["stable"] for r in rows)

    print(f"\n{'='*74}")
    print(f"Decision accuracy (accept/reject + reason) : {decision_ok}/{total}"
          f"  ({100*decision_ok/total:.0f}%)")
    print(f"Role accuracy                              : {role_ok}/{total}"
          f"  ({100*role_ok/total:.0f}%)")
    if args.repeat > 1:
        print(f"Stable across {args.repeat} runs"
              f"{' ':<27}: {stable}/{total}  ({100*stable/total:.0f}%)")

    # The number that decides whether this is safe to deploy.
    humans = [r["ai"] for r in rows if r["human_written"] is True]
    ais = [r["ai"] for r in rows if r["human_written"] is False]
    if humans and ais:
        print(f"\nAI-detection separation")
        print(f"  human-written CVs : n={len(humans)}  "
              f"max={max(humans)}  mean={statistics.mean(humans):.0f}")
        print(f"  AI-written CVs    : n={len(ais)}  "
              f"min={min(ais)}   mean={statistics.mean(ais):.0f}")
        print(f"  threshold          : {settings.ai_threshold}")
        margin = min(ais) - max(humans)
        if max(humans) >= settings.ai_threshold:
            print(f"  >> FALSE POSITIVES: a real CV scored {max(humans)}, at or above "
                  f"the threshold. Real applicants would be rejected. Raise the "
                  f"threshold or improve the prompt before using this.")
        elif margin < 20:
            print(f"  >> Margin is only {margin} points. That is too tight to trust - "
                  f"add more labelled CVs before relying on it.")
        else:
            print(f"  >> Margin {margin} points. Nothing overlaps.")

    misses = [r for r in rows if not (r["status_ok"] and r["reason_ok"] and r["role_ok"])]
    if misses:
        print(f"\nMisses ({len(misses)})")
        for r in misses:
            if not r["role_ok"]:
                print(f"  {r['name']:<42} role: expected {r['expected_role']!r}, "
                      f"got {r['got_role']!r}")
            else:
                print(f"  {r['name']:<42} decision: expected {r['expected_reason']!r}, "
                      f"got {r['got_reason']!r}")

    if errors:
        print(f"\nNot screened ({len(errors)})")
        for line in Counter(errors).keys():
            print(f"  {line}")

    print(f"\nElapsed {time.time()-started:.0f}s")

    if len(rows) < 25:
        print(
            f"\nNOTE: only {len(rows)} labelled CVs. That is enough to catch a broken "
            f"pipeline, not enough to claim an accuracy figure. Add your own CVs to "
            f"eval/labels.json - especially real AI-written ones, which are far "
            f"subtler than the two synthetic samples here."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
