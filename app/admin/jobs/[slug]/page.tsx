"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { CandidateDetail } from "@/components/CandidateDetail";
import { Note, Score, Stat } from "@/components/Shell";
import {
  DECISIONS,
  DECISION_TONE,
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
  const [reading, setReading] = useState(false);
  const [showRejected, setShowRejected] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await listApplications(slug));
    } catch (e) {
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
  const visible = data.results.filter(
    (r) => showRejected || !(r.status === "read" && r.tier === "rejected")
  );
  const hidden = data.results.length - visible.length;

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
            {reading ? "Reading…" : `Read ${unread > 25 ? "the next 25" : "them"}`}
          </button>
        </div>
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
          <Row key={row.id} row={row} onChange={patch} />
        ))}
      </div>

      {hidden > 0 && (
        <label className="flex items-center gap-2 text-sm text-muted">
          <input
            type="checkbox"
            checked={showRejected}
            onChange={(e) => setShowRejected(e.target.checked)}
          />
          Show the {hidden} rejected
        </label>
      )}
    </Frame>
  );
}

function Row({
  row,
  onChange,
}: {
  row: ApplicationRow;
  onChange: (r: ApplicationRow) => void;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState(row.note);
  const [saving, setSaving] = useState(false);
  const unread = row.status !== "read";

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

        <a
          href={row.cv_url}
          target="_blank"
          rel="noopener noreferrer"
          className="chip mr-3 shrink-0 raised text-muted hover:text-ink"
          title={`Open ${row.cv_filename}`}
        >
          Open CV
        </a>
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

          <div className="mb-3 flex flex-wrap items-center gap-2">
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
      <header className="sticky top-0 z-10 border-b bg-bg/85 backdrop-blur">
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
