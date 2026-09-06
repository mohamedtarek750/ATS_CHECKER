"use client";

import { useEffect, useState } from "react";
import JobStep from "@/components/JobStep";
import { Note } from "@/components/Shell";
import {
  editPosting,
  postingJob,
  type EditedPosting,
  type Health,
  type JobProfile,
  type Posting,
} from "@/lib/api";

/**
 * Changing what a vacancy asks for.
 *
 * The editor opens on the checklist that is actually frozen onto the job, not
 * on an empty box - most edits are a correction to one requirement, and making
 * somebody paste the whole advert again to fix one line is how the wrong
 * checklist stays in place.
 *
 * WHAT IT WARNS ABOUT, AND WHY
 * ----------------------------
 * Every applicant on this vacancy was scored against the old list. Saving a
 * new one re-scores all of them - that happens on the server, in the same
 * request, and cannot be skipped. What this panel does is say so BEFORE the
 * save rather than after, because "12 people will be measured again" is
 * information somebody wants while they still have the option not to.
 *
 * And afterwards it names who moved. "12 re-scored" is a fact about the
 * system; "Omar Hassan moved out of the shortlist" is a fact about a person,
 * and only the second one is worth interrupting somebody with.
 */
export function EditJob({
  posting,
  server,
  onSaved,
  onClose,
}: {
  posting: Posting;
  server: Health | null;
  onSaved: (updated: Posting) => void;
  onClose: () => void;
}) {
  const [job, setJob] = useState<JobProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<EditedPosting | null>(null);

  useEffect(() => {
    postingJob(posting.slug)
      .then(setJob)
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Could not read the advert.")
      )
      .finally(() => setLoading(false));
  }, [posting.slug]);

  async function save() {
    if (!job) return;
    setSaving(true);
    setError("");
    try {
      const edited = await editPosting(posting.slug, job);
      setResult(edited);
      onSaved(edited.posting);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the changes.");
    }
    setSaving(false);
  }

  if (result) {
    return (
      <div className="mt-3 rounded-lg border px-4 py-3">
        <p className="text-sm font-medium">Saved.</p>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          {result.rescored === 0
            ? "Nobody had applied yet, so there was nothing to measure again."
            : `${result.rescored} application${
                result.rescored === 1 ? " was" : "s were"
              } measured against the new checklist.`}
          {result.unreadable > 0 &&
            ` ${result.unreadable} could not be re-scored and were left as they were.`}
        </p>

        {result.moved.length > 0 ? (
          <>
            <p className="mt-3 text-sm font-medium">
              {result.moved.length} moved
            </p>
            <ul className="mt-1 space-y-1">
              {result.moved.map((one) => (
                <li key={one.id} className="text-sm text-muted">
                  <strong className="text-ink">{one.full_name}</strong>{" "}
                  {one.from_percent}% → {one.to_percent}%, {tier(one.from_tier)}{" "}
                  → <strong className="text-ink">{tier(one.to_tier)}</strong>
                </li>
              ))}
            </ul>
          </>
        ) : (
          result.rescored > 0 && (
            <p className="mt-2 text-sm text-muted">
              Nobody&rsquo;s standing changed.
            </p>
          )
        )}

        <button className="btn-ghost mt-3 text-sm" onClick={onClose}>
          Done
        </button>
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-4 rounded-lg border px-4 py-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-medium">Edit this job</h3>
        <button className="btn-ghost text-sm" onClick={onClose} disabled={saving}>
          Cancel
        </button>
      </div>

      {posting.applications > 0 && (
        <Note tone="warn">
          <strong className="text-ink">
            {posting.applications} {posting.applications === 1 ? "person has" : "people have"}{" "}
            already been scored against the current list.
          </strong>{" "}
          Saving measures {posting.applications === 1 ? "them" : "them all"}{" "}
          again — some may move between accepted, waiting list and rejected. No
          CV is read a second time, so it costs nothing but the change.
        </Note>
      )}

      {loading && <p className="text-sm text-muted">Reading the advert…</p>}

      {!loading && (
        <>
          <p className="text-sm text-muted">
            Paste a new advert to replace the list, or click any requirement
            below to move it between must-have and nice-to-have.
          </p>
          <JobStep
            job={job}
            setJob={setJob}
            provider={server?.provider ?? "offline"}
            canReadJobs={server?.can_read_jobs ?? false}
            jobModel={server?.job_model ?? null}
          />
        </>
      )}

      {error && <Note tone="bad">{error}</Note>}

      {job && (
        <button className="btn-primary" onClick={save} disabled={saving}>
          {saving
            ? "Saving and re-scoring…"
            : posting.applications > 0
              ? `Save and re-score ${posting.applications}`
              : "Save changes"}
        </button>
      )}
    </div>
  );
}

const TIERS: Record<string, string> = {
  accepted: "accepted",
  waiting_list: "waiting list",
  rejected: "rejected",
  unscored: "not scored",
};

function tier(name: string): string {
  return TIERS[name] ?? name;
}
