"use client";

import { useEffect, useState } from "react";
import JobStep from "@/components/JobStep";
import Results from "@/components/Results";
import Uploads, { type UploadRow } from "@/components/Uploads";
import {
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
  const [error, setError] = useState("");

  useEffect(() => {
    health().then(setServer).catch(() => setServer(null));
  }, []);

  const ready = rows.filter((r) => r.status === "done" && r.parsed);
  const provider = server?.provider ?? "offline";
  const canUseModel = provider !== "offline";

  // A new job means the previous ranking is stale.
  useEffect(() => setResults(null), [job]);

  async function run() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      setResults(
        await matchAll(
          job,
          ready.map((row) => ({
            filename: row.parsed!.filename,
            profile: row.parsed!.profile,
          }))
        )
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Matching failed.");
    }
    setBusy(false);
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <header className="mb-10">
        <h1 className="text-2xl font-semibold tracking-tight">ACUD ATS</h1>
        <p className="mt-1 text-sm text-muted">
          Add the CVs, say what you are hiring for, and see how far each candidate
          meets it — with the reason for every result.
        </p>
        {server && (
          <p className="mt-2 text-xs text-muted">
            Reading CVs with <strong>{server.provider}</strong>
            {server.provider === "offline"
              ? " — rules only, no key needed, nothing sent to a model."
              : ` (${server.model})`}
          </p>
        )}
      </header>

      <div className="space-y-12">
        <Uploads rows={rows} setRows={setRows} provider={provider} />

        {ready.length > 0 && (
          <JobStep
            job={job}
            setJob={setJob}
            provider={provider}
            canUseModel={canUseModel}
            disabled={false}
          />
        )}

        {job && ready.length > 0 && (
          <section className="space-y-3">
            <button className="btn-primary" onClick={run} disabled={busy}>
              {busy
                ? "Matching…"
                : `Match ${ready.length} candidate${ready.length === 1 ? "" : "s"}`}
            </button>
            <p className="text-xs text-muted">
              Matching is pure computation — no model call, so it is instant however
              many CVs you added.
            </p>
            {error && <p className="text-sm text-bad">{error}</p>}
          </section>
        )}

        {results && <Results data={results} />}
      </div>

      <footer className="mt-16 border-t border-line pt-6 text-xs text-muted">
        CVs are read one at a time and the results stay in this browser session.
        Nothing is written to a server.
      </footer>
    </main>
  );
}
