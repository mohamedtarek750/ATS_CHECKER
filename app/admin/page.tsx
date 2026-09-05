"use client";

import Link from "next/link";
import { AcudMark } from "@/components/AcudMark";
import { useEffect, useState } from "react";
import JobStep from "@/components/JobStep";
import { Note } from "@/components/Shell";
import {
  createPosting,
  deletePosting,
  health,
  listPostings,
  mailStatus,
  setPostingStatus,
  type Health,
  type JobProfile,
  type MailStatus,
  type Posting,
} from "@/lib/api";

/** Every vacancy, and the link people apply through. */
export default function AdminPage() {
  const [postings, setPostings] = useState<Posting[] | null>(null);
  const [server, setServer] = useState<Health | null>(null);
  const [mail, setMail] = useState<MailStatus | null>(null);
  const [job, setJob] = useState<JobProfile | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    listPostings().then(setPostings).catch(() => setPostings([]));
    health().then(setServer).catch(() => setServer(null));
    mailStatus().then(setMail).catch(() => setMail(null));
  }, []);

  async function open() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const created = await createPosting(job);
      setPostings((current) => [created, ...(current ?? [])]);
      setCreating(false);
      setJob(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open the vacancy.");
    }
    setBusy(false);
  }

  async function toggle(posting: Posting) {
    const next = posting.status === "open" ? "closed" : "open";
    const updated = await setPostingStatus(posting.slug, next);
    setPostings((current) =>
      (current ?? []).map((p) => (p.slug === updated.slug ? updated : p))
    );
  }

  async function remove(posting: Posting) {
    await deletePosting(posting.slug, posting.applications > 0);
    setPostings((current) =>
      (current ?? []).filter((p) => p.slug !== posting.slug)
    );
  }

  return (
    <div className="min-h-dvh">
      <header className="page-header">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-6 py-3.5">
          <AcudMark subtitle="Jobs and applicants" />
          <div className="flex shrink-0 gap-2">
            {/* The other half of the same system: workforce planning says how
                many people a role is short, this is where they arrive. */}
            <Link href="/workforce" className="btn-ghost text-sm">
              Planning
            </Link>
            <Link href="/admin/screen" className="btn-ghost text-sm">
              Quick check
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl space-y-6 px-6 py-8">
        {/* Only when it is off. A banner saying email works would be on every
            page load forever, and this one is here to be acted on. */}
        {mail && !mail.configured && (
          <Note>
            <strong className="text-ink">
              Applicants are not being sent a thank-you.
            </strong>{" "}
            Their CV still arrives and everything here still works — nobody is
            told it was received. Set <code>RESEND_API_KEY</code> and{" "}
            <code>ATS_MAIL_FROM</code> in the deployment&rsquo;s environment to
            switch it on.
          </Note>
        )}

        {!creating && (
          <button className="btn-primary" onClick={() => setCreating(true)}>
            Add a job
          </button>
        )}

        {creating && (
          <div className="card space-y-4 px-5 py-5">
            <div className="flex items-center justify-between">
              <h2 className="font-medium">Add a job</h2>
              <button
                className="btn-ghost text-sm"
                onClick={() => {
                  setCreating(false);
                  setJob(null);
                }}
              >
                Cancel
              </button>
            </div>
            <p className="text-sm text-muted">
              Paste the advert and check the must-haves. They are frozen onto the
              vacancy when it opens, so every applicant is measured against the
              same list.
            </p>
            <JobStep
              job={job}
              setJob={setJob}
              provider={server?.provider ?? "offline"}
              canReadJobs={server?.can_read_jobs ?? false}
              jobModel={server?.job_model ?? null}
            />
            {error && <Note tone="bad">{error}</Note>}
            {job && (
              <button className="btn-primary" onClick={open} disabled={busy}>
                {busy ? "Publishing…" : "Publish this job"}
              </button>
            )}
          </div>
        )}

        {postings === null && <p className="text-sm text-muted">Loading…</p>}

        {postings !== null && postings.length === 0 && !creating && (
          <div className="empty">
            <p className="text-[15px] font-semibold">No jobs yet</p>
            <p className="mx-auto mt-1.5 max-w-[46ch] text-sm text-muted">
              Add one, paste its description, and you will get a link to share
              with candidates.
            </p>
          </div>
        )}

        <div className="space-y-3">
          {(postings ?? []).map((posting) => (
            <PostingCard
              key={posting.slug}
              posting={posting}
              onToggle={toggle}
              onDelete={remove}
            />
          ))}
        </div>
      </main>
    </div>
  );
}

function PostingCard({
  posting,
  onToggle,
  onDelete,
}: {
  posting: Posting;
  onToggle: (p: Posting) => void;
  onDelete: (p: Posting) => Promise<void>;
}) {
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);
  // Not a vacancy: it is where CVs sent without one are kept, and the API
  // refuses to delete it for the same reason.
  const isHoldingPen = posting.slug === "unassigned";
  const [deleting, setDeleting] = useState(false);
  const [failed, setFailed] = useState("");
  const link =
    typeof window === "undefined"
      ? `/apply/${posting.slug}`
      : `${window.location.origin}/apply/${posting.slug}`;

  return (
    <div className="card animate-rise px-4 py-3.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Link
          href={`/admin/jobs/${posting.slug}`}
          className="font-medium hover:underline"
        >
          {posting.title}
        </Link>
        <span
          className={`chip ${
            posting.status === "open"
              ? "bg-good-wash text-good"
              : "raised text-muted"
          }`}
        >
          {posting.status === "open" ? "Open" : "Closed"}
        </span>
        <span className="text-sm text-muted">
          {posting.applications} applicant
          {posting.applications === 1 ? "" : "s"}
        </span>
        <span className="ml-auto text-xs text-muted">
          {posting.must_total} must-have · {posting.nice_total} nice-to-have
        </span>
      </div>

      {/* The split, on the list itself. Otherwise "how is this vacancy doing"
          means opening every vacancy in turn to find out. */}
      {posting.applications > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="chip bg-good-wash text-good">
            {posting.accepted} accepted
          </span>
          <span className="chip bg-warn-wash text-warn">
            {posting.waiting_list} waiting list
          </span>
          <span className="chip raised text-muted">
            {posting.rejected} rejected
          </span>
          {posting.unread > 0 && (
            <span className="chip raised text-muted">
              {posting.unread} not read yet
            </span>
          )}
        </div>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded bg-raised px-2 py-1 text-xs text-muted">
          {link}
        </code>
        <button
          className="btn-ghost text-sm"
          onClick={() => {
            navigator.clipboard?.writeText(link);
            setCopied(true);
            setTimeout(() => setCopied(false), 1600);
          }}
        >
          {copied ? "Copied" : "Copy link"}
        </button>
        <button className="btn-ghost text-sm" onClick={() => onToggle(posting)}>
          {posting.status === "open" ? "Close" : "Reopen"}
        </button>
        <Link href={`/admin/jobs/${posting.slug}`} className="btn-ghost text-sm">
          Open
        </Link>
        {!isHoldingPen && (
          <button
            className="btn-ghost text-sm text-bad"
            onClick={() => setConfirming(true)}
          >
            Delete
          </button>
        )}
      </div>

      {/* Asked here rather than in a window.confirm, so the count is on the
          screen next to the button that acts on it. A job with people in it is
          usually one somebody wants to CLOSE, and that is offered first. */}
      {confirming && (
        <div className="mt-3 rounded-lg border border-bad/40 bg-bad-wash px-4 py-3">
          <p className="text-sm font-medium">Delete {posting.title}?</p>
          <p className="mt-1 text-sm text-muted">
            {posting.applications > 0 ? (
              <>
                This also deletes {posting.applications} application
                {posting.applications === 1 ? "" : "s"} and the CV
                {posting.applications === 1 ? "" : "s"} sent with{" "}
                {posting.applications === 1 ? "it" : "them"}. Nothing here can
                be brought back. To stop new applications without losing these,
                close the job instead.
              </>
            ) : (
              <>Nobody has applied to it. Nothing else is lost.</>
            )}
          </p>

          {failed && (
            <p className="mt-2 text-sm text-bad">{failed}</p>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className="btn-danger text-sm"
              disabled={deleting}
              onClick={async () => {
                setDeleting(true);
                setFailed("");
                try {
                  await onDelete(posting);
                } catch (e) {
                  setFailed(
                    e instanceof Error ? e.message : "Could not delete it."
                  );
                  setDeleting(false);
                }
              }}
            >
              {deleting
                ? "Deleting…"
                : posting.applications > 0
                  ? `Delete the job and ${posting.applications} application${
                      posting.applications === 1 ? "" : "s"
                    }`
                  : "Delete the job"}
            </button>
            <button
              className="btn-ghost text-sm"
              disabled={deleting}
              onClick={() => {
                setConfirming(false);
                setFailed("");
              }}
            >
              Keep it
            </button>
            {posting.applications > 0 && posting.status === "open" && (
              <button
                className="btn-ghost text-sm"
                disabled={deleting}
                onClick={() => {
                  setConfirming(false);
                  onToggle(posting);
                }}
              >
                Close it instead
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
