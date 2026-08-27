"use client";

import { useRef, useState } from "react";
import {
  jobFromCV,
  parseCV,
  parseJob,
  type JobProfile,
  type Requirement,
} from "@/lib/api";

type Mode = "text" | "cv";

export default function JobStep({
  job,
  setJob,
  provider,
  canUseModel,
  disabled,
}: {
  job: JobProfile | null;
  setJob: (job: JobProfile | null) => void;
  provider: string;
  canUseModel: boolean;
  disabled: boolean;
}) {
  const [mode, setMode] = useState<Mode>("text");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const referenceInput = useRef<HTMLInputElement>(null);

  async function fromText() {
    setBusy(true);
    setError("");
    try {
      setJob(await parseJob(text, provider));
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

  function toggle(index: number) {
    if (!job) return;
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

  const mustCount = job?.requirements.filter((r) => r.importance === "must_have").length ?? 0;

  return (
    <section className={`space-y-4 ${disabled ? "pointer-events-none opacity-40" : ""}`}>
      <div>
        <h2 className="text-lg font-semibold">2. What are you hiring for?</h2>
        <p className="text-sm text-muted">
          Paste the advert, or point at one CV and find people like them.
        </p>
      </div>

      <div className="flex gap-2">
        <button
          className={mode === "text" ? "btn-primary" : "btn-ghost"}
          onClick={() => setMode("text")}
        >
          Paste a job description
        </button>
        <button
          className={mode === "cv" ? "btn-primary" : "btn-ghost"}
          onClick={() => setMode("cv")}
        >
          Use a reference CV
        </button>
      </div>

      {mode === "text" ? (
        <div className="space-y-3">
          <textarea
            className="field h-56 resize-y font-[inherit]"
            placeholder="Paste the whole advert — requirements are read out of it."
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {!canUseModel && (
            <p className="text-sm text-warn">
              Reading an advert needs a model. Set <code>GEMINI_API_KEY</code> on the
              deployment, or use a reference CV instead — that works with no key.
            </p>
          )}
          <button
            className="btn-primary"
            onClick={fromText}
            disabled={busy || !text.trim() || !canUseModel}
          >
            {busy ? "Reading…" : "Read the requirements"}
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="muted-card p-4 text-sm text-muted">
            Upload one CV that looks like what you want. The requirements are taken
            from what that CV <em>demonstrates</em> — skills, degree level, years.
            Never its university, employer, or the language it was written in.
          </div>
          <button
            className="btn-ghost"
            onClick={() => referenceInput.current?.click()}
            disabled={busy}
          >
            {busy ? "Reading…" : "Choose the reference CV"}
          </button>
          <input
            ref={referenceInput}
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

      {error && <p className="text-sm text-bad">{error}</p>}

      {job && (
        <div className="card space-y-3 p-5">
          <div>
            <h3 className="font-semibold">{job.title}</h3>
            <p className="text-sm text-muted">{job.summary}</p>
          </div>

          <div className="rounded-md border border-warn/30 bg-warn/5 p-3 text-sm text-warn">
            <strong>Check the must-haves before you match.</strong> Each one removes
            every applicant who lacks it, and nobody reviews who was removed. Click a
            requirement to move it between must-have and nice-to-have.
          </div>

          <ul className="divide-y divide-line">
            {job.requirements.map((requirement, index) => (
              <li key={`${requirement.text}-${index}`}>
                <button
                  className="flex w-full items-center gap-3 py-2 text-left text-sm hover:bg-wash"
                  onClick={() => toggle(index)}
                >
                  <span
                    className={`w-24 shrink-0 rounded px-2 py-0.5 text-center text-xs ${
                      requirement.importance === "must_have"
                        ? "bg-ink text-white"
                        : "border border-line text-muted"
                    }`}
                  >
                    {requirement.importance === "must_have" ? "Must have" : "Nice to have"}
                  </span>
                  <span className="flex-1">{requirement.text}</span>
                  <span className="text-xs text-muted">{requirement.kind}</span>
                </button>
              </li>
            ))}
          </ul>

          <p className="text-sm text-muted">
            {mustCount} must-have · {job.requirements.length - mustCount} nice-to-have
          </p>
        </div>
      )}
    </section>
  );
}
