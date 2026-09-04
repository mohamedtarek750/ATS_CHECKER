"use client";

import { useState } from "react";
import { Note, Stat } from "@/components/Shell";
import { ForecastNote, WorkforceShell } from "@/components/WorkforceShell";
import { PERFORMANCE_TIERS } from "@/lib/workforce";

const TIER_LABEL: Record<string, string> = {
  bonus: "Bonus eligible",
  normal: "On track",
  improve: "Needs improvement",
};

const TIER_TONE: Record<string, string> = {
  bonus: "bg-good-wash text-good",
  normal: "bg-warn-wash text-warn",
  improve: "bg-bad-wash text-bad",
};

export default function PerformancePage() {
  const [tier, setTier] = useState("");
  const [search, setSearch] = useState("");

  const counts = {
    bonus: PERFORMANCE_TIERS.filter((r) => r.tier === "bonus").length,
    normal: PERFORMANCE_TIERS.filter((r) => r.tier === "normal").length,
    improve: PERFORMANCE_TIERS.filter((r) => r.tier === "improve").length,
  };

  const needle = search.trim().toLowerCase();
  const visible = PERFORMANCE_TIERS.filter(
    (row) =>
      (!tier || row.tier === tier) &&
      (!needle ||
        row.role.toLowerCase().includes(needle) ||
        row.department.toLowerCase().includes(needle))
  );

  return (
    <WorkforceShell
      title="Performance and bonus eligibility"
      intro="Each role's average performance score, out of 5."
    >
      <Note tone="warn">
        <strong className="text-ink">These are roles, not people.</strong> The
        dataset holds an average per role and does not identify anyone, so
        nothing here can say how an individual is doing — and a role scoring
        badly is a question about the role, not a verdict on whoever fills it.
      </Note>

      <ForecastNote />

      <div className="grid grid-cols-3 gap-3">
        <Stat value={counts.bonus} label="Bonus eligible" tone="good" />
        <Stat value={counts.normal} label="On track" tone="warn" />
        <Stat value={counts.improve} label="Needs improvement" />
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
          value={tier}
          onChange={(e) => setTier(e.target.value)}
        >
          <option value="">All tiers</option>
          <option value="bonus">Bonus eligible</option>
          <option value="normal">On track</option>
          <option value="improve">Needs improvement</option>
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
                <th className="px-4 py-2.5 text-right font-medium">Score</th>
                <th className="px-4 py-2.5 text-left font-medium">Standing</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={`${row.department}-${row.role}`} className="border-b last:border-0">
                  <td className="px-4 py-2.5 font-medium">{row.role}</td>
                  <td className="px-4 py-2.5 text-muted">{row.department}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">{row.employees}</td>
                  <td className="px-4 py-2.5 text-right font-medium tabular-nums">
                    {row.score.toFixed(1)}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`chip ${TIER_TONE[row.tier]}`}>
                      {TIER_LABEL[row.tier]}
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
