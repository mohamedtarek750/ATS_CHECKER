"use client";

import { useEffect, useState } from "react";
import { use } from "react";
import { AcudMark } from "@/components/AcudMark";
import { Note } from "@/components/Shell";
import {
  publicPosting,
  requestRead,
  submitApplication,
  type PublicPosting,
} from "@/lib/api";

/**
 * The page a candidate sees. Deliberately plain.
 *
 * It shows the job title and what the role does, and nothing about how anybody
 * is scored. Publishing the must-have list would tell every applicant exactly
 * which words to paste into their CV, which is the one thing the whole
 * evidence-weighted matcher exists to resist.
 */
export default function ApplyPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const [posting, setPosting] = useState<PublicPosting | null>(null);
  const [loadError, setLoadError] = useState("");

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  useEffect(() => {
    publicPosting(slug)
      .then(setPosting)
      .catch((e) =>
        setLoadError(e instanceof Error ? e.message : "This link is not valid.")
      );
  }, [slug]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Attach your CV.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const receipt = await submitApplication(
        slug, { full_name: fullName, email, phone }, file
      );
      setSent(true);
      // The CV is stored and the receipt is given. Reading it happens after,
      // and the applicant does not wait for it.
      requestRead(receipt.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong. Try again.");
    }
    setBusy(false);
  }

  if (loadError) {
    return (
      <Centered>
        <Note tone="bad">{loadError}</Note>
      </Centered>
    );
  }

  if (!posting) {
    return (
      <Centered>
        <p className="text-sm text-muted">Loading…</p>
      </Centered>
    );
  }

  if (sent) {
    return (
      <Centered>
        <div className="card animate-rise px-6 py-8 text-center">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-good-wash text-good">
            ✓
          </div>
          <h1 className="text-lg font-semibold">Application received</h1>
          <p className="mt-2 text-sm text-muted">
            Thank you, {fullName.split(" ")[0] || "and good luck"}. Your CV has
            reached the team hiring for {posting.title}. If it is a fit for the
            role, somebody will be in touch on {email}.
          </p>
        </div>
      </Centered>
    );
  }

  if (!posting.is_open) {
    return (
      <Centered>
        <div className="card px-6 py-8 text-center">
          <h1 className="text-lg font-semibold">{posting.title}</h1>
          <p className="mt-2 text-sm text-muted">
            This role is no longer accepting applications.
          </p>
        </div>
      </Centered>
    );
  }

  return (
    <Centered>
      <div className="mb-6">
        <div className="mb-6">
          <AcudMark subtitle="Careers" />
        </div>
        <p className="text-xs uppercase tracking-wide text-gold">Now hiring</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          {posting.title}
        </h1>
        {posting.summary && (
          <p className="mt-2 text-sm text-muted">{posting.summary}</p>
        )}
      </div>

      <form onSubmit={submit} className="card animate-rise space-y-4 px-5 py-5">
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

        <Field label="Your CV" required hint="PDF, DOCX, TXT, MD or RTF · up to 8 MB.">
          <input
            className="field"
            type="file"
            accept=".pdf,.docx,.doc,.txt,.md,.rtf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            required
          />
        </Field>

        {error && <Note tone="bad">{error}</Note>}

        <button className="btn-primary w-full" disabled={busy}>
          {busy ? "Sending…" : "Send application"}
        </button>

        <p className="text-xs text-muted">
          Your CV is read to check it against what this role asks for. It is kept
          for this vacancy and is not shown to anyone outside the hiring team.
        </p>
      </form>
    </Centered>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh">
      <main className="mx-auto w-full max-w-lg px-6 py-12">{children}</main>
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
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">
        {label}
        {required && <span className="ml-1 text-bad">*</span>}
      </span>
      {children}
      {hint && <span className="block text-xs text-muted">{hint}</span>}
    </label>
  );
}
