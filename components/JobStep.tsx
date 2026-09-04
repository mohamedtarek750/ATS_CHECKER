"use client";

import { useRef, useState } from "react";
import {
  fetchBlueprint,
  jobFromCV,
  parseCV,
  parseJob,
  type Blueprint,
  type JobProfile,
  type Requirement,
} from "@/lib/api";
import { Note } from "./Shell";
import { BlueprintCard } from "./TemplatePanel";

type Mode = "text" | "cv";

export default function JobStep({
  job,
  setJob,
  provider,
  canReadJobs,
  jobModel,
}: {
  job: JobProfile | null;
  setJob: (job: JobProfile | null) => void;
  provider: string;
  canReadJobs: boolean;
  jobModel: string | null;
}) {
  const [mode, setMode] = useState<Mode>("text");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [blueprint, setBlueprint] = useState<Blueprint | null>(null);
  const reference = useRef<HTMLInputElement>(null);

  async function fromText() {
    setBusy(true);
    setError("");
    try {
      setJob(await parseJob(text));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read that.");
    }
    setBusy(false);
  }

  async function fromReferenceCV(file: File) {
    setBusy(true);
    setError("");
    try {
      const parsed = await parseCV(file, provider);
      if (!parsed.profile.is_cv) {
        setError("That file is not a CV, so there is nothing to match against.");
      } else {
        setJob(await jobFromCV(parsed.profile, false));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read that CV.");
    }
    setBusy(false);
  }

  async function showBlueprint() {
    if (!job) return;
    setBusy(true);
    try {
      setBlueprint(await fetchBlueprint(job));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build the template.");
    }
    setBusy(false);
  }

  function toggle(index: number) {
    if (!job) return;
    // Editing the requirements changes the ideal CV, so the old one is stale.
    setBlueprint(null);
    const requirements: Requirement[] = job.requirements.map((r, i) =>
      i === index
        ? {
            ...r,
            importance: r.importance === "must_have" ? "nice_to_have" : "must_have",
          }
        : r
    );
    setJob({ ...job, requirements });
  }

  const must = job?.requirements.filter((r) => r.importance === "must_have").length ?? 0;

  return (
    <div className="space-y-4">
      <div className="inline-flex rounded-lg border p-1">
        {(
          [
            ["text", "Paste a job description"],
            ["cv", "Use a reference CV"],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            onClick={() => setMode(value)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
              mode === value ? "bg-accent text-accent-ink" : "text-muted hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {mode === "text" ? (
        <div className="space-y-3">
          <textarea
            className="field h-56 resize-y leading-relaxed"
            placeholder="Paste the whole advert. The requirements are read out of it and split into must-have and nice-to-have."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {!canReadJobs && (
            <Note tone="warn">
              Reading an advert needs a model — turning prose into must-have and
              nice-to-have is the one judgement rules cannot make. Add{" "}
              <code className="rounded bg-warn/10 px-1">GEMINI_API_KEY</code> to the
              deployment, or use a reference CV, which needs no key.
            </Note>
          )}
          <div className="flex items-center gap-3">
            <button
              className="btn-primary"
              onClick={fromText}
              disabled={busy || !text.trim() || !canReadJobs}
            >
              {busy ? "Reading…" : "Read this job"}
            </button>
            {canReadJobs && jobModel && (
              <span className="text-xs text-muted">using {jobModel}</span>
            )}
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <Note>
            Upload one CV that looks like what you want. The requirements come from
            what that CV <em>demonstrates</em> — skills, degree level, years — and
            never from its university, employer, or the language it was written in.
            Those track where someone came from rather than what they can do.
          </Note>
          <button
            className="btn-ghost"
            onClick={() => reference.current?.click()}
            disabled={busy}
          >
            {busy ? "Reading…" : "Choose the reference CV"}
          </button>
          <input
            ref={reference}
            type="file"
            accept=".pdf,.docx,.txt,.md,.rtf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void fromReferenceCV(file);
            }}
          />
        </div>
      )}

      {error && <Note tone="bad">{error}</Note>}

      {job && (
        <div className="card animate-rise overflow-hidden">
          <div className="border-b px-5 py-4">
            <h3 className="font-semibold">{job.title}</h3>
            <p className="mt-0.5 text-sm text-muted">{job.summary}</p>
          </div>

          <div className="border-b bg-warn-wash px-5 py-3 text-sm text-warn">
            <strong>Check the must-haves before you match.</strong> Each one removes
            every applicant who lacks it, and nobody reviews who was removed. Click a
            row to move it between must-have and nice-to-have.
          </div>

          <ul className="divide-y">
            {job.requirements.map((requirement, index) => {
              const isMust = requirement.importance === "must_have";
              return (
                <li key={`${requirement.text}-${index}`}>
                  <button
                    onClick={() => toggle(index)}
                    className="flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm transition hover:bg-raised"
                  >
                    <span
                      className={`chip w-24 shrink-0 justify-center border ${
                        isMust
                          ? "border-transparent bg-accent text-accent-ink"
                          : "border-line text-muted"
                      }`}
                    >
                      {isMust ? "Must have" : "Nice to have"}
                    </span>
                    <span className={`flex-1 ${isMust ? "" : "text-muted"}`}>
                      {requirement.text}
                    </span>
                    <span className="shrink-0 text-xs text-muted">{requirement.kind}</span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm text-muted">
            <span>
              {must} must-have · {job.requirements.length - must} nice-to-have
            </span>
            <button
              className="btn-ghost ml-auto"
              onClick={blueprint ? () => setBlueprint(null) : showBlueprint}
              disabled={busy}
            >
              {blueprint ? "Hide the ideal CV" : "Show the ideal CV"}
            </button>
          </div>
        </div>
      )}

      {blueprint && <BlueprintCard blueprint={blueprint} />}
    </div>
  );
}
