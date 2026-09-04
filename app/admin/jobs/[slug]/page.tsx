"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { CandidateDetail } from "@/components/CandidateDetail";
import { Note, Score, Stat } from "@/components/Shell";
import { StatsPanel } from "@/components/StatsPanel";
import { assignToVacancy, listPostings, UNASSIGNED_SLUG, type Posting } from "@/lib/api";
import { downloadCSV, toCSV } from "@/lib/csv";
import {
  DECISIONS,
  DECISION_TONE,
  SignedOutError,
  cvObjectUrl,
  listApplications,
  readPending,
  saveDecision,
  type ApplicationRow,
  type ApplicationsResponse,
  type DecisionValue,
} from "@/lib/api";

const TIER_CHIP: Record<string, string> = {
  accepted: "bg-good-wash text-good",
  waiting_list: "bg-warn-wash text-warn",
  rejected: "raised text-muted",
  not_a_cv: "raised text-muted",
};

/** Everyone who applied to one vacancy, best fit first. */
export default function JobDashboard({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const [data, setData] = useState<ApplicationsResponse | null>(null);
  const [error, setError] = useState("");
  const [signedOut, setSignedOut] = useState(false);
  const [reading, setReading] = useState(false);
  const [showRejected, setShowRejected] = useState(false);
  const [decisionFilter, setDecisionFilter] = useState<DecisionValue | "all">("all");
  const [search, setSearch] = useState("");
  const [showStats, setShowStats] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await listApplications(slug));
    } catch (e) {
      setSignedOut(e instanceof SignedOutError);
      setError(e instanceof Error ? e.message : "Could not load this vacancy.");
    }
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  async function readNew() {
    setReading(true);
    setError("");
    try {
      setData(await readPending(slug));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reading failed.");
    }
    setReading(false);
  }

  function patch(row: ApplicationRow) {
    setData((current) =>
      current
        ? {
            ...current,
            results: current.results.map((r) => (r.id === row.id ? row : r)),
          }
        : current
    );
  }

  if (error) {
    return (
      <Frame slug={slug}>
        <Note tone="bad">{error}</Note>
        {signedOut && (
          <button className="btn-primary mt-3" onClick={() => location.reload()}>
            Sign in again
          </button>
        )}
      </Frame>
    );
  }
  if (!data) {
    return (
      <Frame slug={slug}>
        <p className="text-sm text-muted">Loading…</p>
      </Frame>
    );
  }

  const { posting, counts } = data;
  const unread = counts.pending ?? 0;

  // How many sit at each stage of the human process, which is a different
  // question from how the engine scored them.
  const funnel: Record<string, number> = {};
  for (const row of data.results) {
    funnel[row.decision] = (funnel[row.decision] ?? 0) + 1;
  }

  const needle = search.trim().toLowerCase();
  const matchesSearch = (r: ApplicationRow) =>
    !needle ||
    r.full_name.toLowerCase().includes(needle) ||
    r.email.toLowerCase().includes(needle) ||
    r.phone.toLowerCase().includes(needle);

  const visible = data.results.filter(
    (r) =>
      matchesSearch(r) &&
      (decisionFilter === "all" || r.decision === decisionFilter) &&
      // The rejected are folded away by default, unless a filter asked for
      // them specifically - hiding what somebody just searched for would be
      // the system arguing with them.
      (showRejected ||
        decisionFilter !== "all" ||
        !!needle ||
        !(r.status === "read" && r.tier === "rejected"))
  );
  const hidden = data.results.length - visible.length;
  const filtering = decisionFilter !== "all" || !!needle;

  /** Exactly what is on screen, in the order it is on screen. */
  function exportVisible() {
    const rows = visible.map((r) => [
      r.full_name, r.email, r.phone,
      r.status === "read" ? r.percent : "",
      r.status === "read" ? r.tier_label : statusWord(r),
      r.required_percent, r.preferred_percent,
      r.decision_label, r.decided_by, r.decided_at,
      r.note, r.reason,
      r.applied_at, r.cv_filename, r.engine_version,
    ]);
    downloadCSV(
      `${posting.slug}_applicants.csv`,
      toCSV(
        [
          "name", "email", "phone", "percent", "outcome",
          "required_percent", "preferred_percent",
          "decision", "decided_by", "decided_at",
          "note", "reason", "applied_at", "cv_file", "engine_version",
        ],
        rows
      )
    );
  }

  return (
    <Frame slug={slug} title={posting.title}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat value={counts.total ?? 0} label="Applicants" />
        <Stat value={counts.accepted ?? 0} label="Accepted" tone="good" />
        <Stat value={counts.waiting_list ?? 0} label="Waiting list" tone="warn" />
        <Stat value={counts.rejected ?? 0} label="Rejected" />
      </div>

      {unread > 0 && (
        <div className="card flex flex-wrap items-center gap-3 px-4 py-3">
          <p className="min-w-0 flex-1 text-sm">
            <strong>{unread}</strong> application{unread === 1 ? " has" : "s have"}{" "}
            arrived and {unread === 1 ? "has" : "have"} not been read yet.
          </p>
          <button className="btn-primary" onClick={readNew} disabled={reading}>
            {reading ? "Reading…" : `Read ${unread > 25 ? "the next 25 CVs" : "the new CVs"}`}
          </button>
        </div>
      )}

      {data.results.length > 0 && (
        <div className="card px-4 py-3">
          <button
            className="flex w-full items-center justify-between text-left"
            onClick={() => setShowStats(!showStats)}
          >
            <span className="text-sm font-medium">
              How this vacancy is doing
            </span>
            <span className={`text-muted transition ${showStats ? "rotate-90" : ""}`}>
              &rsaquo;
            </span>
          </button>
          {showStats && (
            <div className="mt-4 border-t pt-4">
              <StatsPanel slug={slug} />
            </div>
          )}
        </div>
      )}

      {data.results.length > 0 && (
        <div className="card space-y-3 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-muted">
              Stage
            </span>
            <button
              onClick={() => setDecisionFilter("all")}
              className={`chip ${
                decisionFilter === "all"
                  ? "bg-accent text-accent-ink"
                  : "raised text-muted hover:text-ink"
              }`}
            >
              All {data.results.length}
            </button>
            {DECISIONS.filter((d) => funnel[d]).map((value) => (
              <button
                key={value}
                onClick={() =>
                  setDecisionFilter(decisionFilter === value ? "all" : value)
                }
                className={`chip ${
                  decisionFilter === value
                    ? "bg-accent text-accent-ink"
                    : DECISION_TONE[value]
                }`}
              >
                {value === "new" ? "New" : value[0].toUpperCase() + value.slice(1)}{" "}
                {funnel[value]}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <input
              className="field min-w-0 flex-1"
              placeholder="Search name, email or phone…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button
              className="btn-ghost shrink-0"
              onClick={exportVisible}
              disabled={visible.length === 0}
            >
              Export {filtering ? `these ${visible.length}` : "CSV"}
            </button>
          </div>

          {filtering && (
            <p className="text-xs text-muted">
              Showing {visible.length} of {data.results.length}.{" "}
              <button
                className="underline"
                onClick={() => {
                  setDecisionFilter("all");
                  setSearch("");
                }}
              >
                Clear
              </button>
            </p>
          )}
        </div>
      )}

      {data.results.length > 0 && visible.length === 0 && (
        <Note>
          {filtering
            ? "Nobody matches that. Clear the filter to see everyone again."
            : /* Not a filter - every applicant is below the bar, and the
                 rejected are folded away by default. Telling somebody to clear
                 a filter they never set sends them looking for a control that
                 is not there. */
              `Nobody cleared the bar. All ${data.results.length} applications ` +
              "are below 70%, and are folded away below."}
        </Note>
      )}

      {data.results.length === 0 && (
        <Note>
          Nobody has applied yet. Share the link from the{" "}
          <Link href="/admin" className="underline">
            vacancies page
          </Link>
          .
        </Note>
      )}

      <div className="space-y-2">
        {visible.map((row) => (
          <Row key={row.id} row={row} onChange={patch} reload={load} />
        ))}
      </div>

      {hidden > 0 && !filtering && (
        <label className="flex items-center gap-2 text-sm text-muted">
          <input
            type="checkbox"
            checked={showRejected}
            onChange={(e) => setShowRejected(e.target.checked)}
          />
          Also show the {hidden} rejected
        </label>
      )}
    </Frame>
  );
}

function AssignControl({
  row,
  onAssigned,
}: {
  row: ApplicationRow;
  onAssigned: () => void;
}) {
  const [vacancies, setVacancies] = useState<Posting[] | null>(null);
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    listPostings()
      .then((all) =>
        // Only somewhere with a checklist to measure against. Moving a CV to
        // another empty pile would change nothing.
        setVacancies(all.filter((p) => p.slug !== UNASSIGNED_SLUG && p.must_total > 0))
      )
      .catch(() => setVacancies([]));
  }, []);

  async function assign() {
    if (!target) return;
    setBusy(true);
    setError("");
    try {
      await assignToVacancy(row.id, target);
      onAssigned();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not move this application.");
    }
    setBusy(false);
  }

  if (vacancies !== null && vacancies.length === 0) {
    return (
      <Note>
        Add a job with some requirements and this CV can be measured
        against it.
      </Note>
    );
  }

  return (
    <div className="mb-3">
      <p className="mb-1.5 text-xs uppercase tracking-wide text-muted">
        Measure against a vacancy
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="field min-w-0 flex-1"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          disabled={busy || vacancies === null}
        >
          <option value="">Choose a vacancy…</option>
          {(vacancies ?? []).map((p) => (
            <option key={p.slug} value={p.slug}>
              {p.title}
            </option>
          ))}
        </select>
        <button
          className="btn-primary shrink-0"
          onClick={assign}
          disabled={busy || !target}
        >
          {busy ? "Adding…" : "Add to this job"}
        </button>
      </div>
      {error && (
        <div className="mt-2">
          <Note tone="bad">{error}</Note>
        </div>
      )}
    </div>
  );
}

function Row({
  row,
  onChange,
  reload,
}: {
  row: ApplicationRow;
  onChange: (r: ApplicationRow) => void;
  /** After a move the applicant is on another vacancy, so this list is stale. */
  reload: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState(row.note);
  const [saving, setSaving] = useState(false);
  const [opening, setOpening] = useState(false);
  const unread = row.status !== "read";

  /**
   * The CV endpoint needs the signed-in token, and a plain link cannot send
   * one. Leaving it open instead would put a stranger's CV behind nothing but
   * an unguessable id, so the bytes are fetched and handed to a blob URL.
   */
  async function openCv() {
    setOpening(true);
    try {
      const url = await cvObjectUrl(row.id);
      window.open(url, "_blank", "noopener");
      // Released once the new tab has taken it. Revoking immediately would
      // pull the document out from under the tab that is loading it.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      alert(e instanceof Error ? e.message : "The CV could not be opened.");
    }
    setOpening(false);
  }

  async function change(decision: DecisionValue) {
    setSaving(true);
    onChange(await saveDecision(row.id, { decision }));
    setSaving(false);
  }

  const noteChanged = note !== row.note;

  async function commitNote() {
    if (!noteChanged) return;
    setSaving(true);
    onChange(await saveDecision(row.id, { note }));
    setSaving(false);
  }

  return (
    <div className="card animate-rise overflow-hidden">
      <div className="flex items-center transition hover:bg-raised">
        <button
          onClick={() => setOpen(!open)}
          className="flex min-w-0 flex-1 items-center gap-4 px-4 py-3 text-left"
        >
          {unread ? (
            <span className="chip w-12 shrink-0 justify-center raised text-muted">
              —
            </span>
          ) : (
            <Score percent={row.percent} />
          )}

          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">{row.full_name}</span>
            <span className="block truncate text-sm text-muted">
              {row.email}
              {row.phone && ` · ${row.phone}`}
            </span>
          </span>

          <span
            className={`chip w-28 shrink-0 justify-center ${
              unread ? "raised text-muted" : TIER_CHIP[row.tier]
            }`}
          >
            {unread ? statusWord(row) : row.tier_label}
          </span>

          <span
            className={`chip hidden w-24 shrink-0 justify-center sm:flex ${
              DECISION_TONE[row.decision]
            }`}
          >
            {row.decision_label}
          </span>

          <span className={`shrink-0 text-muted transition ${open ? "rotate-90" : ""}`}>
            ›
          </span>
        </button>

        {row.security_flags.length > 0 && (
          <span
            className="chip mr-2 shrink-0 bg-bad-wash text-bad"
            title="This CV contains text aimed at the reader. Open it and look."
          >
            Check CV
          </span>
        )}

        <button
          onClick={openCv}
          disabled={opening}
          className="chip mr-3 shrink-0 raised text-muted hover:text-ink"
          title={`Open ${row.cv_filename}`}
        >
          {opening ? "Opening…" : "Open CV"}
        </button>
      </div>

      {open && (
        <div className="border-t raised px-4 py-3">
          {row.reason && <p className="mb-3 text-sm">{row.reason}</p>}
          {row.detail && unread && (
            <Note tone="warn">
              {row.status === "not_a_cv"
                ? `This file reads as a ${row.detail}, not a CV.`
                : row.detail}
            </Note>
          )}
          {row.stale && (
            <Note tone="warn">
              Scored under an older version of the matching rules, so this
              percentage may not match what the engine would produce today.
            </Note>
          )}

          {row.security_flags.length > 0 && (
            <div className="mb-3">
              <Note tone="bad">
                <strong className="text-ink">
                  This CV contains text written at the reader, not at you.
                </strong>
                <span className="mt-1.5 block">
                  Flagged, not rejected — the wording can appear innocently and
                  no application is ended by a pattern match. Anything the
                  document does not actually support has already been struck off
                  the record below.
                </span>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {row.security_flags.map((flag, index) => (
                    <li key={index} className="text-xs">
                      {flag}
                    </li>
                  ))}
                </ul>
              </Note>
            </div>
          )}

          {row.tier === "unscored" && (
            <AssignControl row={row} onAssigned={reload} />
          )}

          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-muted">
              Decision
            </span>
            {DECISIONS.map((value) => (
              <button
                key={value}
                onClick={() => change(value)}
                disabled={saving}
                className={`chip ${
                  row.decision === value
                    ? DECISION_TONE[value]
                    : "raised text-muted hover:text-ink"
                }`}
              >
                {value === "new" ? "New" : value[0].toUpperCase() + value.slice(1)}
              </button>
            ))}
          </div>

          {/* Saved on a button, not only on blur. A note that writes itself
              when focus happens to leave is a note that goes missing when the
              recruiter closes the tab, and they never find out it went. */}
          <div className="mb-3">
            {row.decided_by && (
            <p className="mb-3 text-xs text-muted">
              Last changed by {row.decided_by}
              {row.decided_at && ` · ${row.decided_at.replace("T", " ").slice(0, 16)}`}
            </p>
          )}

          <textarea
              className="field min-h-[4rem] text-sm"
              placeholder="Notes for the hiring team…"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              onBlur={commitNote}
            />
            <div className="mt-1.5 flex items-center gap-2">
              <button
                className="btn-ghost text-sm"
                onClick={commitNote}
                disabled={!noteChanged || saving}
              >
                {saving ? "Saving…" : "Save note"}
              </button>
              {noteChanged && !saving && (
                <span className="text-xs text-warn">Not saved yet</span>
              )}
              {!noteChanged && row.note && (
                <span className="text-xs text-muted">Saved</span>
              )}
            </div>
          </div>

          {row.status === "read" && <CandidateDetail id={row.id} />}
        </div>
      )}
    </div>
  );
}

function statusWord(row: ApplicationRow): string {
  if (row.status === "pending") return "Not read";
  if (row.status === "not_a_cv") return "Not a CV";
  return "Failed";
}

function Frame({
  slug,
  title,
  children,
}: {
  slug: string;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-dvh">
      <header className="rule-brand sticky top-0 z-10 bg-bg/90 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-6 py-3.5">
          <div className="min-w-0">
            <h1 className="truncate text-[15px] font-semibold tracking-tight">
              {title ?? slug}
            </h1>
            <p className="truncate text-xs text-muted">
              Accepted at 80% and above, waiting list from 70%, rejected below
            </p>
          </div>
          <Link href="/admin" className="btn-ghost shrink-0 text-sm">
            All vacancies
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-4xl space-y-5 px-6 py-8">{children}</main>
    </div>
  );
}
