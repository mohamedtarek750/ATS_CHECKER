"use client";

import { useState } from "react";
import { AcudMark } from "@/components/AcudMark";
import { Note } from "@/components/Shell";
import { requestRead, submitOpenApplication } from "@/lib/api";

/**
 * Sending a CV in without applying to anything in particular.
 *
 * Somebody who wants to work here before a suitable vacancy exists is not an
 * error to turn away, and a CV with nowhere to sit is how an application
 * quietly disappears. These are stored and read like any other and land in
 * their own pile for the team to look through.
 *
 * Like the per-vacancy page, this shows the applicant nothing about how they
 * were assessed - and here there is genuinely nothing to show, because with no
 * job description there is nothing to measure against yet.
 */
export default function OpenApplyPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("Attach your CV.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const receipt = await submitOpenApplication(
        { full_name: fullName, email, phone },
        file
      );
      setSent(true);
      // Stored and acknowledged already; the reading happens after, and the
      // applicant never waits for it.
      requestRead(receipt.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong. Try again.");
    }
    setBusy(false);
  }

  if (sent) {
    return (
      <Centered>
        <div className="card animate-rise px-6 py-8 text-center">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-good-wash text-good">
            ✓
          </div>
          <h1 className="text-lg font-semibold">CV received</h1>
          <p className="mt-2 text-sm text-muted">
            Thank you, {fullName.split(" ")[0] || "and good luck"}. Your CV is
            with the team. It will be kept on file, and if something opens up
            that fits, somebody will be in touch on {email}.
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
        <p className="text-xs uppercase tracking-wide text-brand">
          Open application
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">
          Send us your CV
        </h1>
        <p className="mt-2 text-sm text-muted">
          Not applying for a particular role? Leave your CV here and the team
          will keep it on file for when something suitable opens.
        </p>
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

        <Field
          label="Your CV"
          required
          hint="PDF, DOCX, TXT, MD or RTF · up to 8 MB."
        >
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
          {busy ? "Sending…" : "Send my CV"}
        </button>

        <p className="text-xs text-muted">
          Your CV is read so the team can see your experience. It is kept only
          for hiring, and only the hiring team can open it.
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
