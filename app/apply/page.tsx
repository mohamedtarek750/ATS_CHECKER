"use client";

import { useState } from "react";
import { AcudMark } from "@/components/AcudMark";
import { CvField } from "@/components/CvField";
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
        <div className="card animate-rise px-7 py-10 text-center">
          <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-full bg-good-wash text-xl text-good">
            ✓
          </div>
          <h1 className="text-xl font-semibold">CV received</h1>
          <p className="mt-2.5 text-[15px] leading-relaxed text-muted">
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
      <div className="mb-8">
        <p className="eyebrow">Open application</p>
        <h1 className="display mt-2">Send us your CV</h1>
        <p className="mt-3 max-w-[52ch] text-[15px] leading-relaxed text-muted">
          Not applying for a particular role? Leave your CV with us and the
          hiring team will keep it on file for when something suitable opens.
        </p>
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
          {busy ? "Sending…" : "Send my CV"}
        </button>
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
        <div className="mx-auto w-full max-w-2xl px-6 py-3.5">
          <AcudMark subtitle="Careers" />
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
