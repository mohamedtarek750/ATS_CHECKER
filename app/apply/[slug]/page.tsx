"use client";

import { useEffect, useState } from "react";
import { use } from "react";
import Link from "next/link";
import { AcudMark } from "@/components/AcudMark";
import { CvField } from "@/components/CvField";
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
      <div className="mb-8">
        <p className="eyebrow">Now hiring</p>
        <h1 className="display mt-2">{posting.title}</h1>
        {posting.summary && (
          <p className="mt-3 max-w-[52ch] text-[15px] leading-relaxed text-muted">
            {posting.summary}
          </p>
        )}
      </div>

      <form onSubmit={submit} className="card animate-rise space-y-5 px-6 py-7">
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

/**
 * The frame both applicant pages sit in.
 *
 * A header band carrying the logo, the page itself, and a line saying who is
 * asking. A candidate arriving from a link has no other context, so the page
 * has to establish whose it is before it asks for their CV.
 */
function Centered({ children }: { children: React.ReactNode }) {
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
