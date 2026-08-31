"use client";

import { useState } from "react";
import {
  STATUS_MARK,
  STATUS_WORD,
  type MatchResponse,
  type Ranked,
  type RequirementResult,
} from "@/lib/api";
import { Note, Score, Stat } from "./Shell";
import { TemplateBlock } from "./TemplatePanel";

const TIER_CHIP: Record<string, string> = {
  shortlist: "bg-good-wash text-good",
  review: "bg-warn-wash text-warn",
  not_a_match: "raised text-muted",
  not_a_cv: "raised text-muted",
};

const STRENGTH_TONE: Record<string, string> = {
  strong: "bg-good-wash text-good",
  valid: "bg-good-wash text-good",
  partial: "bg-warn-wash text-warn",
  none: "raised text-muted",
};

const STRENGTH_WORD: Record<string, string> = {
  strong: "Demonstrated",
  valid: "Stated",
  partial: "Partial",
  none: "",
};

function RequirementList({
  label,
  results,
}: {
  label: string;
  results: RequirementResult[];
}) {
  if (results.length === 0) return null;

  return (
    <div className="mb-3">
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">
        {label}
      </p>
      <ul className="space-y-2 text-sm">
        {results.map((result, index) => (
          <li key={`${result.requirement}-${index}`}>
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span
                className={`w-4 shrink-0 text-center ${
                  result.status === "met"
                    ? "text-good"
                    : result.status === "not_met"
                      ? "text-muted"
                      : "text-warn"
                }`}
              >
                {STATUS_MARK[result.status]}
              </span>
              <span className="font-medium">{result.requirement}</span>
              <span className="text-xs text-muted">
                {STATUS_WORD[result.status]}
              </span>
              {STRENGTH_WORD[result.strength] && (
                <span
                  className={`chip ${STRENGTH_TONE[result.strength]}`}
                  title={`Evidence found in: ${result.source}`}
                >
                  {STRENGTH_WORD[result.strength]} · {result.source}
                </span>
              )}
            </div>

            {result.evidence && result.evidence !== "None found" && (
              <p className="ml-6 text-xs italic text-muted">{result.evidence}</p>
            )}
            {result.explanation && (
              <p className="ml-6 text-xs text-muted">{result.explanation}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Row({ entry }: { entry: Ranked }) {
  const [open, setOpen] = useState(entry.tier === "shortlist");

  return (
    <div className="card animate-rise overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-4 px-4 py-3 text-left transition hover:bg-raised"
      >
        <Score percent={entry.percent} />

        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">
            {entry.name || entry.filename}
          </span>
          <span className="block truncate text-sm text-muted">
            {entry.headline || entry.filename}
            {entry.years > 0 && ` · ${entry.years} yrs`}
          </span>
        </span>

        {entry.possibly_ai && (
          <span
            className="chip shrink-0 bg-warn-wash text-warn"
            title="Reads as possibly AI-written. Flagged for a human to look at, never a rejection."
          >
            AI?
          </span>
        )}

        {entry.template && (
          <span
            className="hidden shrink-0 text-right text-xs text-muted sm:block"
            title="How well this CV is written for this job - a separate question from whether the candidate is qualified"
          >
            CV {entry.template.percent}%
          </span>
        )}

        <span className={`chip w-28 shrink-0 justify-center ${TIER_CHIP[entry.tier]}`}>
          {entry.tier_label}
        </span>

        <span className="hidden w-14 shrink-0 text-right text-sm tabular-nums text-muted sm:block">
          {entry.must_met}/{entry.must_total}
        </span>

        <span className={`shrink-0 text-muted transition ${open ? "rotate-90" : ""}`}>
          ›
        </span>
      </button>

      {open && (
        <div className="border-t raised px-4 py-3">
          <p className="mb-3 text-sm">{entry.reason}</p>

          <div className="mb-3 flex flex-wrap gap-4 text-sm">
            <span>
              <span className="text-muted">Required requirements match </span>
              <span className="font-medium tabular-nums">
                {entry.required_percent}%
              </span>
            </span>
            <span>
              <span className="text-muted">Preferred requirements match </span>
              <span className="font-medium tabular-nums">
                {entry.preferred_percent}%
              </span>
            </span>
          </div>

          <RequirementList
            label="Required"
            results={entry.requirements.filter(
              (r) => r.importance === "must_have",
            )}
          />
          <RequirementList
            label="Preferred"
            results={entry.requirements.filter(
              (r) => r.importance !== "must_have",
            )}
          />

          {entry.template && <TemplateBlock report={entry.template} />}

          {(entry.email || entry.phone) && (
            <p className="mt-3 border-t pt-3 text-xs text-muted">
              {[entry.email, entry.phone].filter(Boolean).join("  ·  ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function toCSV(response: MatchResponse): string {
  const head = [
    "percent", "tier", "name", "headline", "years", "must_met", "must_total",
    "meets", "missing", "email", "phone", "possibly_ai", "file",
  ];
  const rows = response.results.map((entry) => [
    entry.percent, entry.tier_label, entry.name, entry.headline, entry.years,
    entry.must_met, entry.must_total,
    entry.requirements.filter((r) => r.status === "met").map((r) => r.requirement).join(" | "),
    entry.requirements
      .filter((r) => r.importance === "must_have" && r.status !== "met")
      .map((r) => r.requirement)
      .join(" | "),
    entry.email, entry.phone, entry.possibly_ai ? "yes" : "", entry.filename,
  ]);
  return [head, ...rows]
    .map((row) => row.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(","))
    .join("\n");
}

export default function Results({ data }: { data: MatchResponse }) {
  const [showAll, setShowAll] = useState(false);
  const counts = data.counts;

  const visible = data.results.filter(
    (e) => e.tier !== "not_a_cv" && (showAll || e.tier !== "not_a_match")
  );
  const hidden = data.results.filter(
    (e) => e.tier === "not_a_match" || e.tier === "not_a_cv"
  ).length;

  function download() {
    const blob = new Blob([toCSV(data)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${data.job_title.replace(/[^A-Za-z0-9]+/g, "_")}_ranking.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat value={counts.shortlist ?? 0} label="Shortlist" tone="good" />
        <Stat value={counts.review ?? 0} label="Worth a look" tone="warn" />
        <Stat value={counts.not_a_match ?? 0} label="Not a match" />
        <Stat
          value={(counts.total ?? 0) - (counts.not_a_cv ?? 0)}
          label="Candidates"
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          {data.job_title} · {data.must_total} must-have, {data.nice_total} nice-to-have
        </p>
        <button className="btn-ghost" onClick={download}>
          Download CSV
        </button>
      </div>

      {(counts.flagged_ai ?? 0) > 0 && (
        <Note>
          {counts.flagged_ai} CV{counts.flagged_ai === 1 ? "" : "s"} read as possibly
          AI-written. They are marked, not rejected — the check is not reliable enough
          to end an application on its own.
        </Note>
      )}

      <div className="space-y-2">
        {visible.map((entry) => (
          <Row key={entry.filename + entry.name} entry={entry} />
        ))}
      </div>

      {hidden > 0 && (
        <label className="flex items-center gap-2 text-sm text-muted">
          <input
            type="checkbox"
            checked={showAll}
            onChange={(e) => setShowAll(e.target.checked)}
          />
          Show the {hidden} who are not a match
        </label>
      )}
    </div>
  );
}
