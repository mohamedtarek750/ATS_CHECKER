"use client";

import { useState } from "react";
import { Note, Stat } from "@/components/Shell";
import { ForecastNote, WorkforceShell } from "@/components/WorkforceShell";
import { TURNOVER } from "@/lib/workforce";

const RISK_LABEL: Record<string, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

const RISK_TONE: Record<string, string> = {
  high: "bg-bad-wash text-bad",
  medium: "bg-warn-wash text-warn",
  low: "bg-good-wash text-good",
};

export default function TurnoverPage() {
  const [risk, setRisk] = useState("");
  const [search, setSearch] = useState("");

  const counts = {
    high: TURNOVER.filter((r) => r.risk === "high").length,
    medium: TURNOVER.filter((r) => r.risk === "medium").length,
    low: TURNOVER.filter((r) => r.risk === "low").length,
  };

  const needle = search.trim().toLowerCase();
  const visible = TURNOVER.filter(
    (row) =>
      (!risk || row.risk === risk) &&
      (!needle ||
        row.role.toLowerCase().includes(needle) ||
        row.department.toLowerCase().includes(needle))
  );

  const smallest = TURNOVER.filter((r) => r.risk === "high" && r.current_employees <= 6);

  return (
    <WorkforceShell
      title="Turnover and retention risk"
      intro="People who left, over role headcount, for the latest period. A role losing people steadily is a retention problem whether or not the forecast has flagged it as short-staffed."
    >
      {smallest.length > 0 && (
        <Note tone="warn">
          <strong className="text-ink">Read the small roles carefully.</strong>{" "}
          {smallest.map((r) => r.role).join(", ")}{" "}
          {smallest.length === 1 ? "has" : "have"} very few people in{" "}
          {smallest.length === 1 ? "it" : "them"}, so one departure produces a
          dramatic percentage. Talent Acquisition&rsquo;s 33% is one person out
          of three — a real loss, but not the crisis the number implies on its
          own.
        </Note>
      )}

      <ForecastNote />

      <div className="grid grid-cols-3 gap-3">
        <Stat value={counts.high} label="High risk (15%+)" />
        <Stat value={counts.medium} label="Medium (8–15%)" tone="warn" />
        <Stat value={counts.low} label="Low (under 8%)" tone="good" />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          className="field min-w-0 flex-1"
          placeholder="Search role or department…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="field shrink-0"
          value={risk}
          onChange={(e) => setRisk(e.target.value)}
        >
          <option value="">All risk levels</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {visible.length === 0 ? (
        <p className="text-sm text-muted">Nothing matches that.</p>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2.5 text-left font-medium">Role</th>
                <th className="px-4 py-2.5 text-left font-medium">Department</th>
                <th className="px-4 py-2.5 text-right font-medium">People</th>
                <th className="px-4 py-2.5 text-right font-medium">Left</th>
                <th className="px-4 py-2.5 text-right font-medium">Rate</th>
                <th className="px-4 py-2.5 text-left font-medium">Risk</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={`${row.department}-${row.role}`} className="border-b last:border-0">
                  <td className="px-4 py-2.5 font-medium">{row.role}</td>
                  <td className="px-4 py-2.5 text-muted">{row.department}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {row.current_employees}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {row.employees_lost}
                  </td>
                  <td className="px-4 py-2.5 text-right font-medium tabular-nums">
                    {row.turnover_rate.toFixed(1)}%
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`chip ${RISK_TONE[row.risk]}`}>
                      {RISK_LABEL[row.risk]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </WorkforceShell>
  );
}
