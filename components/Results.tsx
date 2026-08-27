"use client";

import { useState } from "react";
import {
  STATUS_MARK,
  STATUS_WORD,
  TIER_COLOUR,
  type MatchResponse,
  type Ranked,
} from "@/lib/api";

function Bar({ percent }: { percent: number }) {
  const tone =
    percent >= 80 ? "bg-good" : percent >= 50 ? "bg-warn" : "bg-muted/50";
  return (
    <div className="h-1.5 w-24 overflow-hidden rounded-full bg-line">
      <div className={`h-full ${tone}`} style={{ width: `${percent}%` }} />
    </div>
  );
}

function Card({ entry }: { entry: Ranked }) {
  const [open, setOpen] = useState(entry.tier === "shortlist");

  return (
    <div className="card overflow-hidden">
      <button
        className="flex w-full items-center gap-4 px-4 py-3 text-left hover:bg-wash"
        onClick={() => setOpen(!open)}
      >
        <span className="w-14 shrink-0 text-right text-xl font-semibold tabular-nums">
          {entry.percent}%
        </span>
        <Bar percent={entry.percent} />
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
            className="shrink-0 rounded border border-warn/30 bg-warn/5 px-2 py-0.5 text-xs text-warn"
            title="Reads as possibly AI-written. Flagged for you to look at, never a rejection."
          >
            AI?
          </span>
        )}
        <span
          className={`w-28 shrink-0 rounded border px-2 py-1 text-center text-xs ${TIER_COLOUR[entry.tier]}`}
        >
          {entry.tier_label}
        </span>
        <span className="w-14 shrink-0 text-right text-sm tabular-nums text-muted">
          {entry.must_met}/{entry.must_total}
        </span>
      </button>

      {open && (
        <div className="border-t border-line bg-wash/50 px-4 py-3">
          <p className="mb-3 text-sm">{entry.reason}</p>
          <ul className="space-y-1 text-sm">
            {entry.requirements.map((result, index) => (
              <li key={`${result.requirement}-${index}`} className="flex gap-2">
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
                <span
                  className={
                    result.importance === "must_have" ? "font-medium" : "text-muted"
                  }
                >
                  {result.requirement}
                </span>
                <span className="text-xs text-muted">
                  {STATUS_WORD[result.status]}
                </span>
                {result.evidence && (
                  <span className="min-w-0 flex-1 truncate text-xs italic text-muted">
                    {result.evidence}
                  </span>
                )}
              </li>
            ))}
          </ul>
          {(entry.email || entry.phone) && (
            <p className="mt-3 text-xs text-muted">
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
    entry.percent,
    entry.tier_label,
    entry.name,
    entry.headline,
    entry.years,
    entry.must_met,
    entry.must_total,
    entry.requirements.filter((r) => r.status === "met").map((r) => r.requirement).join(" | "),
    entry.requirements
      .filter((r) => r.importance === "must_have" && r.status !== "met")
      .map((r) => r.requirement)
      .join(" | "),
    entry.email,
    entry.phone,
    entry.possibly_ai ? "yes" : "",
    entry.filename,
  ]);
  return [head, ...rows]
    .map((row) =>
      row.map((cell) => `"${String(cell ?? "").replace(/"/g, '""')}"`).join(",")
    )
    .join("\n");
}

export default function Results({ data }: { data: MatchResponse }) {
  const [showAll, setShowAll] = useState(false);
  const counts = data.counts;

  const visible = data.results.filter(
    (entry) =>
      entry.tier !== "not_a_cv" && (showAll || entry.tier !== "not_a_match")
  );

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
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">3. The shortlist</h2>
          <p className="text-sm text-muted">
            {data.job_title} · {data.must_total} must-have,{" "}
            {data.nice_total} nice-to-have
          </p>
        </div>
        <button className="btn-ghost" onClick={download}>
          Download CSV
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Shortlist", counts.shortlist ?? 0],
          ["Worth a look", counts.review ?? 0],
          ["Not a match", counts.not_a_match ?? 0],
          ["Candidates", (counts.total ?? 0) - (counts.not_a_cv ?? 0)],
        ].map(([label, value]) => (
          <div key={label as string} className="muted-card px-4 py-3">
            <div className="text-2xl font-semibold tabular-nums">{value}</div>
            <div className="text-xs text-muted">{label}</div>
          </div>
        ))}
      </div>

      {(counts.flagged_ai ?? 0) > 0 && (
        <p className="rounded-md border border-line bg-wash px-4 py-2 text-sm text-muted">
          {counts.flagged_ai} CV{counts.flagged_ai === 1 ? "" : "s"} read as possibly
          AI-written. They are marked, not rejected — the check is not reliable enough
          to end an application on its own.
        </p>
      )}

      <label className="flex items-center gap-2 text-sm text-muted">
        <input
          type="checkbox"
          checked={showAll}
          onChange={(e) => setShowAll(e.target.checked)}
        />
        Show the candidates who are not a match
      </label>

      <div className="space-y-2">
        {visible.map((entry) => (
          <Card key={entry.filename + entry.name} entry={entry} />
        ))}
      </div>
    </section>
  );
}
