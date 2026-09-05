"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AcudMark } from "@/components/AcudMark";
import { CvField } from "@/components/CvField";
import { Note } from "@/components/Shell";
import {
  publicPostings,
  requestRead,
  submitApplication,
  submitOpenApplication,
  type PublicPosting,
} from "@/lib/api";

/**
 * The front door: where somebody applies.
 *
 * This is what anybody visiting the site sees, so it does one thing - takes a
 * person's details and their CV - and tells them nothing about how they will be
 * assessed. It used to be the recruiter's screening tool, which meant a visitor
 * could paste in a job description and watch themselves be scored against it.
 * That tool still exists, behind the sign-in at /admin/screen, where it belongs.
 *
 * The job picker is the other half of the fix. Without it a CV sent from here
 * had nowhere to go but the unassigned pile, so a recruiter who had just opened
 * a job would look at it and see no applicants.
 */
export default function ApplyHome() {
  const [jobs, setJobs] = useState<PublicPosting[] | null>(null);
  const [jobSlug, setJobSlug] = useState("");

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  useEffect(() => {
    publicPostings()
      .then((open) => {
        setJobs(open);
        // One job open is the common case at this size; choosing it for them
        // saves a decision that has only one answer.
        if (open.length === 1) setJobSlug(open[0].slug);
      })
      .catch(() => setJobs([]));
  }, []);

  const chosen = jobs?.find((j) => j.slug === jobSlug) ?? null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Attach your CV.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const fields = { full_name: fullName, email, phone };
      const receipt = jobSlug
        ? await submitApplication(jobSlug, fields, file)
        : await submitOpenApplication(fields, file);
      setSent(true);
      // Stored and acknowledged already. Reading happens after, and the
      // applicant never waits for it.
      requestRead(receipt.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong. Try again.");
    }
    setBusy(false);
  }

  if (sent) {
    return (
      <Shell>
        <div className="card animate-rise px-7 py-10 text-center">
          <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-full bg-good-wash text-xl text-good">
            ✓
          </div>
          <h1 className="text-xl font-semibold">Application received</h1>
          <p className="mt-2.5 text-[15px] leading-relaxed text-muted">
            Thank you, {fullName.split(" ")[0] || "and good luck"}.{" "}
            {chosen
              ? `Your CV has reached the team hiring for ${chosen.title}.`
              : "Your CV is with the team and will be kept on file."}{" "}
            If it is a fit, somebody will be in touch on {email}.
          </p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="mb-8">
        <p className="eyebrow">Careers</p>
        <h1 className="display mt-2">Apply to join ACUD</h1>
        <p className="mt-3 max-w-[52ch] text-[15px] leading-relaxed text-muted">
          Choose the role you are applying for, or send your CV without one and
          the hiring team will keep it on file.
        </p>
      </div>

      <form onSubmit={submit} className="card animate-rise space-y-5 px-6 py-7">
        <Field label="Which role?" required={false}>
          <select
            className="field"
            value={jobSlug}
            onChange={(e) => setJobSlug(e.target.value)}
            disabled={jobs === null}
          >
            <option value="">
              {jobs === null
                ? "Loading roles…"
                : jobs.length === 0
                  ? "No roles are open — send your CV anyway"
                  : "No particular role — keep my CV on file"}
            </option>
            {(jobs ?? []).map((job) => (
              <option key={job.slug} value={job.slug}>
                {job.title}
              </option>
            ))}
          </select>
          {chosen?.summary && (
            <span className="mt-1.5 block text-xs leading-relaxed text-muted">
              {chosen.summary}
            </span>
          )}
        </Field>

        <Field label="Your name" required>
          <input
            className="field"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
            autoComplete="name"
          />
        </Field>

        <Field label="Email" required hint="Where the team will reply.">
          <input
            className="field"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </Field>

        <Field label="Phone" hint="Optional.">
          <input
            className="field"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoComplete="tel"
          />
        </Field>

        <Field label="Your CV" required>
          <CvField file={file} onFile={setFile} />
        </Field>

        {error && <Note tone="bad">{error}</Note>}

        <button className="btn-primary w-full py-3 text-[15px]" disabled={busy}>
          {busy ? "Sending…" : "Send my application"}
        </button>
      </form>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="page-header">
        <div className="mx-auto flex w-full max-w-2xl items-center justify-between gap-3 px-6 py-3.5">
          <AcudMark subtitle="Careers" />
          {/* Named for who it is for. An applicant should be able to tell at a
              glance that this is not the button they came here to press. */}
          <Link href="/admin" className="btn-ghost shrink-0 text-sm">
            Staff sign in
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-2xl flex-1 px-6 py-10 sm:py-14">
        {children}
      </main>

      <footer className="mx-auto w-full max-w-2xl px-6 pb-10">
        <p className="border-t pt-5 text-xs leading-relaxed text-muted">
          Administrative Capital for Urban Development · العاصمة الإدارية
          للتنمية العمرانية
          <span className="mt-1 block">
            Your details are used for hiring and nothing else, and only the
            hiring team can open your CV.
          </span>
        </p>
      </footer>
    </div>
  );
}

function Field({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">
        {label}
        {required && <span className="text-bad"> *</span>}
      </span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}
