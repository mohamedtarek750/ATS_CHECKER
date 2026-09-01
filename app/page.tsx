"use client";

import { useEffect, useMemo, useState } from "react";
import JobStep from "@/components/JobStep";
import Results from "@/components/Results";
import { Note, Step } from "@/components/Shell";
import Uploads, { type UploadRow } from "@/components/Uploads";
import {
  MATCH_BATCH,
  health,
  matchAll,
  type Health,
  type JobProfile,
  type MatchResponse,
} from "@/lib/api";

export default function Page() {
  const [rows, setRows] = useState<UploadRow[]>([]);
  const [job, setJob] = useState<JobProfile | null>(null);
  const [results, setResults] = useState<MatchResponse | null>(null);
  const [server, setServer] = useState<Health | null>(null);
  const [busy, setBusy] = useState(false);
  const [matched, setMatched] = useState({ done: 0, total: 0 });
  const [error, setError] = useState("");

  useEffect(() => {
    health().then(setServer).catch(() => setServer(null));
  }, []);

  // A changed job means any previous ranking is stale.
  useEffect(() => setResults(null), [job]);

  const ready = rows.filter((r) => r.status === "done" && r.parsed);
  const provider = server?.provider ?? "offline";

  // A link back to the original document, so a recruiter can read the CV itself
  // rather than trusting the summary of it. The file is already in the browser -
  // an object URL points at that copy, so opening it uploads nothing and stores
  // nothing. Keyed on name and size so it is rebuilt when the pool changes but
  // not on every re-render while files are still being read.
  const poolKey = ready.map((r) => `${r.file.name}|${r.file.size}`).join("\n");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const fileUrls = useMemo(() => {
    const urls: Record<string, string> = {};
    for (const row of ready) urls[row.parsed!.filename] = URL.createObjectURL(row.file);
    return urls;
  }, [poolKey]);

  // Object URLs live until the document is unloaded unless they are released.
  useEffect(
    () => () => Object.values(fileUrls).forEach(URL.revokeObjectURL),
    [fileUrls],
  );

  async function run() {
    if (!job) return;
    setBusy(true);
    setError("");
    setMatched({ done: 0, total: ready.length });
    try {
      setResults(
        await matchAll(
          job,
          ready.map((row) => ({
            filename: row.parsed!.filename,
            profile: row.parsed!.profile,
          })),
          (done, total) => setMatched({ done, total })
        )
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Matching failed.");
    }
    setBusy(false);
  }

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-10 border-b bg-bg/85 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-6 py-3.5">
          <div className="min-w-0">
            <h1 className="truncate text-[15px] font-semibold tracking-tight">
              ACUD ATS
            </h1>
            <p className="truncate text-xs text-muted">
              Read each CV once, match it against any vacancy, see every reason
            </p>
          </div>
          {server && (
            <div className="hidden shrink-0 text-right text-xs text-muted sm:block">
              <div>
                CVs: <strong className="text-ink">{server.provider}</strong>
                {server.provider === "offline" && " (no key needed)"}
              </div>
              <div>
                Adverts:{" "}
                <strong className="text-ink">
                  {server.can_read_jobs ? server.job_model : "unavailable"}
                </strong>
              </div>
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-4xl space-y-12 px-6 py-10">
        <Step
          index={1}
          title="Add the CVs"
          hint="Read once, here in your browser session. Nothing is stored on the server."
          done={ready.length > 0}
          active={ready.length === 0}
        >
          <Uploads rows={rows} setRows={setRows} provider={provider} />
        </Step>

        {ready.length > 0 && (
          <Step
            index={2}
            title="What are you hiring for?"
            hint="Paste the advert, or point at one CV and find people like them."
            done={!!job}
            active={!job}
          >
            <JobStep
              job={job}
              setJob={setJob}
              provider={provider}
              canReadJobs={server?.can_read_jobs ?? false}
              jobModel={server?.job_model ?? null}
            />
          </Step>
        )}

        {job && ready.length > 0 && (
          <Step
            index={3}
            title="The decision"
            hint="Accepted at 80% and above, waiting list from 70%, rejected below that."
            active={!results}
            done={!!results}
          >
            <div className="space-y-4">
              {!results && (
                <div className="space-y-2">
                  <button className="btn-primary" onClick={run} disabled={busy}>
                    {busy
                      ? matched.total > MATCH_BATCH
                        ? `Matching ${matched.done} of ${matched.total}…`
                        : "Matching…"
                      : `Match ${ready.length} candidate${ready.length === 1 ? "" : "s"}`}
                  </button>
                  <p className="text-xs text-muted">
                    Matching is pure computation — no model call.
                    {ready.length > MATCH_BATCH &&
                      ` Sent in batches of ${MATCH_BATCH}, because one request
                        carrying every candidate would exceed what the server may
                        return.`}
                  </p>
                </div>
              )}
              {error && <Note tone="bad">{error}</Note>}
              {results && <Results data={results} fileUrls={fileUrls} />}
            </div>
          </Step>
        )}
      </main>

      <footer className="mx-auto max-w-4xl border-t px-6 py-6 text-xs text-muted">
        CVs are read one at a time and the results stay in this browser session.
        Nothing is written to a server.
      </footer>
    </div>
  );
}
