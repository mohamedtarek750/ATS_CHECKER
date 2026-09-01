"""Does this hold up at 1000+ CVs? Measured, not asserted.

Run:  python audit/load_test.py                 # 1000 CVs
      python audit/load_test.py --count 5000
      python audit/load_test.py --skip-read      # only the instant stages

The five stages have wildly different costs, and reporting one number for
"1000 CVs" would hide the only thing worth knowing: which stage is the wall.

  * Reading a CV (stages 1-2) is real CPU work, once per file, ever.
  * Matching and ranking (stages 4-5) are pure computation over already-read
    candidates, and are re-run for every new vacancy.

That asymmetry is the whole design. A pool read once is matched against any
number of vacancies for free, so the cost that matters at 1000 CVs is paid on
intake and never again.

Content is cycled from the real CVs in data/inbox, with identities varied so the
pool holds distinct records. Parsing is genuine work on genuine files; the
matcher sees real skills, real experience and real section structure.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
import tracemalloc
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# A load test that prints nothing for four minutes looks like a hang. Stream it.
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:  # pragma: no cover - very old interpreters
    pass

from ats.job_profile import JobProfile, Requirement  # noqa: E402
from ats.models import CandidateProfile  # noqa: E402
from ats.stages import offline, parse, rank  # noqa: E402
from ats.stages import match as match_stage  # noqa: E402
from ats.stages import template_match as template  # noqa: E402
from ats.blueprint import blueprint_for  # noqa: E402

#: Vercel rejects a request body or a response above this. The web app sends the
#: whole pool in one /api/match call, so it is a real ceiling, not a footnote.
VERCEL_PAYLOAD_MB = 4.5

JOB = JobProfile(
    title="Data Analyst",
    seniority="Mid-level",
    summary="Owns commercial reporting.",
    min_years_experience=2,
    requirements=[
        Requirement(text="Bachelor degree in Statistics, Computer Science or a related field",
                    kind="education", importance="must_have"),
        Requirement(text="2 years of professional experience in a data role",
                    kind="experience", importance="must_have"),
        Requirement(text="Strong SQL", kind="skill", importance="must_have"),
        Requirement(text="Power BI or Tableau", kind="skill", importance="must_have",
                    any_of=["Power BI", "Tableau"]),
        Requirement(text="Python", kind="skill", importance="must_have"),
        Requirement(text="Written English", kind="language", importance="must_have"),
        Requirement(text="Azure or Databricks", kind="skill", importance="nice_to_have",
                    any_of=["Azure", "Databricks"]),
        Requirement(text="Excel", kind="skill", importance="nice_to_have"),
        Requirement(text="PL-300 certification", kind="certification",
                    importance="nice_to_have"),
    ],
)


def source_files() -> list[Path]:
    files = sorted(p for p in (ROOT / "data" / "inbox").glob("*.pdf"))
    files += sorted(p for p in (ROOT / "samples").glob("*.pdf"))
    if not files:
        raise SystemExit("No PDFs in data/inbox or samples to load-test with.")
    return files


def materialise(count: int, sources: list[Path], into: Path) -> list[Path]:
    """`count` real files on disk, cycled from the real ones available."""
    into.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(count):
        src = sources[i % len(sources)]
        dst = into / f"cv_{i:05d}{src.suffix}"
        shutil.copyfile(src, dst)
        made.append(dst)
    return made


def read_one(path: Path) -> CandidateProfile | None:
    doc = parse.parse_one(path)
    if not doc.ok:
        return None
    return offline.extract_profile(doc)


def vary(profile: CandidateProfile, index: int) -> CandidateProfile:
    """A distinct person with the same career. Identity only - never the evidence."""
    clone = profile.model_copy(deep=True)
    clone.full_name = f"{profile.full_name or 'Candidate'} {index}"
    clone.email = f"candidate{index}@example.com"
    return clone


def band(seconds: float, count: int) -> str:
    per = seconds / count * 1000
    rate = count / seconds if seconds else float("inf")
    return f"{seconds:7.2f}s   {per:7.2f} ms/CV   {rate:8.0f} CV/s"


def section(title: str) -> None:
    print(f"\n{title}\n" + "-" * 78)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-read", action="store_true",
                    help="Skip stages 1-2, which dominate the wall time.")
    args = ap.parse_args()
    count = args.count

    print(f"Load test: {count} CVs")
    print(f"Vacancy  : {JOB.title} - {len(JOB.must_haves)} must-have, "
          f"{len(JOB.nice_to_haves)} nice-to-have")

    sources = source_files()
    print(f"Sources  : {len(sources)} real CV files, cycled")

    tmp = Path(tempfile.mkdtemp(prefix="ats_load_"))
    try:
        # ---------------------------------------------------------------
        # Stages 1-2: reading. Paid once per CV, ever.
        # ---------------------------------------------------------------
        profiles: list[CandidateProfile] = []
        if args.skip_read:
            section("STAGES 1-2  Reading CVs   [skipped]")
            seed = [p for p in (read_one(f) for f in sources[:8]) if p]
            profiles = [vary(seed[i % len(seed)], i) for i in range(count)]
        else:
            section("STAGES 1-2  Reading CVs (parse + normalize, offline rules)")
            print(f"  materialising {count} files on disk...")
            started = time.perf_counter()
            files = materialise(count, sources, tmp / "inbox")
            print(f"  ...done in {time.perf_counter() - started:.1f}s")

            sample = min(count, 40)
            started = time.perf_counter()
            serial = [read_one(f) for f in files[:sample]]
            serial_elapsed = time.perf_counter() - started
            print(f"  one at a time ({sample} CVs)   {band(serial_elapsed, sample)}")
            projected = serial_elapsed / sample * count
            print(f"  -> {count} CVs would take {projected:6.0f}s "
                  f"({projected/60:.1f} min) single-threaded")

            # Threads first, to show why they are the wrong tool: PDF text
            # extraction is pure Python, so the GIL serialises it and eight
            # workers buy almost nothing.
            thread_sample = min(count, 120)
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                list(pool.map(read_one, files[:thread_sample]))
            thread_elapsed = time.perf_counter() - started
            thread_rate = thread_sample / thread_elapsed
            print(f"  {args.workers} threads ({thread_sample} CVs)  "
                  f"{band(thread_elapsed, thread_sample)}")
            print(f"  -> {thread_rate / (sample / serial_elapsed):.1f}x over serial "
                  f"- threads cannot help, the work is pure-Python and GIL-bound")

            started = time.perf_counter()
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                read = list(pool.map(read_one, files, chunksize=8))
            parallel_elapsed = time.perf_counter() - started
            ok = [p for p in read if p is not None]
            print(f"  {args.workers} processes ({count} CVs)  "
                  f"{band(parallel_elapsed, count)}")
            print(f"  -> {len(ok)} read, {count - len(ok)} unreadable, "
                  f"speed-up {projected / parallel_elapsed:.1f}x over serial")
            profiles = [vary(ok[i % len(ok)], i) for i in range(count)]

        # ---------------------------------------------------------------
        # Stages 4-5: matching and ranking. Re-run for every vacancy.
        # ---------------------------------------------------------------
        section("STAGES 4-5  Matching and ranking the whole pool")
        pool_input = [(f"cv_{i:05d}.pdf", p) for i, p in enumerate(profiles)]

        started = time.perf_counter()
        results = match_stage.match_all(pool_input, JOB)
        match_elapsed = time.perf_counter() - started
        print(f"  match {count}                {band(match_elapsed, count)}")

        started = time.perf_counter()
        ranked = rank.rank(results)
        rank_elapsed = time.perf_counter() - started
        print(f"  rank {count}                 {band(rank_elapsed, count)}")

        counts = rank.summarize(ranked)
        print(f"  -> accepted {counts['accepted']}, waiting list "
              f"{counts['waiting_list']}, rejected {counts['rejected']}, "
              f"not a CV {counts['not_a_cv']}")
        print(f"  -> a second vacancy costs "
              f"{(match_elapsed + rank_elapsed):.2f}s, not a re-read")

        # ---------------------------------------------------------------
        # Stage 6: the per-candidate template report.
        # ---------------------------------------------------------------
        section("STAGE 6     Ideal-CV template report, per candidate")
        blueprint = blueprint_for(JOB)
        started = time.perf_counter()
        reports = [
            template.evaluate(r.candidate, blueprint, r) for r in results
        ]
        template_elapsed = time.perf_counter() - started
        print(f"  template {count}             {band(template_elapsed, count)}")

        # ---------------------------------------------------------------
        # The web path. This is where a serverless limit bites, not the CPU.
        # ---------------------------------------------------------------
        section("THE WEB PATH  One /api/match request carrying the whole pool")
        request_bytes = len(json.dumps({
            "job": json.loads(JOB.model_dump_json()),
            "candidates": [
                {"filename": name, "profile": json.loads(p.model_dump_json())}
                for name, p in pool_input
            ],
            "include_template": True,
        }))
        print(f"  request body                {request_bytes/1024/1024:6.2f} MB "
              f"for {count} candidates")

        try:
            from fastapi.testclient import TestClient
            from api.index import app

            client = TestClient(app)
            payload = {
                "job": json.loads(JOB.model_dump_json()),
                "candidates": [
                    {"filename": name, "profile": json.loads(p.model_dump_json())}
                    for name, p in pool_input
                ],
                "include_template": True,
            }
            started = time.perf_counter()
            response = client.post("/api/match", json=payload)
            api_elapsed = time.perf_counter() - started
            response_mb = len(response.content) / 1024 / 1024
            print(f"  handler                     {api_elapsed:6.2f}s, "
                  f"status {response.status_code}")
            print(f"  response body               {response_mb:6.2f} MB")

            over = max(request_bytes / 1024 / 1024, response_mb)
            if over > VERCEL_PAYLOAD_MB:
                headroom = int(count * VERCEL_PAYLOAD_MB / over)
                print(f"  !! over the {VERCEL_PAYLOAD_MB} MB serverless payload limit - "
                      f"about {headroom} candidates fit in one request")
            else:
                fits = int(count * VERCEL_PAYLOAD_MB / over) if over else count
                print(f"  -> fits, with room for roughly {fits} candidates per request")
        except Exception as exc:  # noqa: BLE001
            print(f"  handler not measured: {type(exc).__name__}: {exc}")

        # ---------------------------------------------------------------
        # Measured in a pass of its own, deliberately. tracemalloc instruments
        # every allocation and roughly quadruples parsing time, so leaving it on
        # during the timed stages reports the profiler's overhead as the
        # system's - it had this load test claiming 10 minutes for a job that
        # takes two and a half.
        section("MEMORY  (separate pass - tracemalloc distorts timings)")
        tracemalloc.start()
        held = match_stage.match_all(pool_input, JOB)
        held_ranked = rank.rank(held)
        held_reports = [template.evaluate(r.candidate, blueprint, r) for r in held]
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del held, held_ranked, held_reports
        print(f"  peak python allocation      {peak/1024/1024:6.1f} MB "
              f"holding {count} profiles, matches and template reports")
        print(f"  per candidate               {peak/count/1024:6.1f} KB")

        section("SUMMARY")
        if not args.skip_read:
            print(f"  Reading {count} CVs is the wall: "
                  f"{parallel_elapsed:.0f}s on {args.workers} workers, paid once.")
        print(f"  Matching that pool against a vacancy: "
              f"{match_elapsed + rank_elapsed:.2f}s, repeatable for free.")
        print(f"  Ranking and template reports are the cheap part "
              f"({rank_elapsed:.2f}s and {template_elapsed:.1f}s per {count}); "
              f"matching at {match_elapsed / count * 1000:.0f} ms/CV is not.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
