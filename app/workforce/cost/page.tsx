"use client";

import { useState } from "react";
import { Note, Stat } from "@/components/Shell";
import { WorkforceShell } from "@/components/WorkforceShell";
import { COST_ROLES, DEFAULT_COST_PER_HIRE, type CostRole } from "@/lib/workforce";

const LEVELS: CostRole["level"][] = ["Junior", "Mid", "Senior", "Expert"];

export default function CostPage() {
  const [rates, setRates] = useState<Record<string, number>>({
    ...DEFAULT_COST_PER_HIRE,
  });
  const [search, setSearch] = useState("");

  const priced = COST_ROLES.map((role) => ({
    ...role,
    perHire: rates[role.level] ?? 0,
    total: (rates[role.level] ?? 0) * role.gap,
  }));
  const grandTotal = priced.reduce((sum, r) => sum + r.total, 0);

  const byDepartment = Object.entries(
    priced.reduce<Record<string, number>>((acc, r) => {
      acc[r.department] = (acc[r.department] ?? 0) + r.total;
      return acc;
    }, {})
  ).sort((a, b) => b[1] - a[1]);
  const widest = Math.max(1, ...byDepartment.map(([, total]) => total));

  const needle = search.trim().toLowerCase();
  const visible = priced.filter(
    (r) =>
      !needle ||
      r.role.toLowerCase().includes(needle) ||
      r.department.toLowerCase().includes(needle)
  );

  const money = (n: number) => `$${n.toLocaleString("en-US")}`;

  return (
    <WorkforceShell
      title="What filling the gap would cost"
      intro="Cost per hire multiplied by the number of positions each role is short."
    >
      <Note tone="warn">
        <strong className="text-ink">
          These rates are placeholders, not ACUD&rsquo;s figures.
        </strong>{" "}
        The dataset carries no cost data at all, so the numbers below start from
        illustrative rates by seniority. Put your real average cost per hire in
        the four boxes and every total on this page recalculates — until you do,
        treat the total as a shape, not a budget.
      </Note>

      <div className="card flex flex-wrap items-end gap-3 px-4 py-3">
        {LEVELS.map((level) => (
          <label key={level} className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-muted">
              {level}
            </span>
            <input
              type="number"
              min={0}
              className="field w-28"
              value={rates[level]}
              onChange={(e) =>
                setRates({ ...rates, [level]: Math.max(0, Number(e.target.value) || 0) })
              }
            />
          </label>
        ))}
        <span className="pb-2 text-xs text-muted">$ per hire, by seniority</span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat value={money(grandTotal)} label="Total to fill every gap" tone="warn" />
        <Stat value={COST_ROLES.length} label="Roles with a gap" />
        <Stat
          value={COST_ROLES.reduce((n, r) => n + r.gap, 0)}
          label="Positions to fill"
        />
      </div>

      <section>
        <h3 className="mb-2 text-sm font-medium">By department</h3>
        <div className="space-y-1.5">
          {byDepartment.map(([department, total]) => (
            <div key={department} className="flex items-center gap-3">
              <span className="w-40 shrink-0 truncate text-sm">{department}</span>
              <span className="h-2 min-w-0 flex-1 overflow-hidden rounded-full raised">
                <span
                  className="block h-full rounded-full bg-warn"
                  style={{ width: `${(total / widest) * 100}%` }}
                />
              </span>
              <span className="w-24 shrink-0 text-right text-xs tabular-nums text-muted">
                {money(total)}
              </span>
            </div>
          ))}
        </div>
      </section>

      <input
        className="field"
        placeholder="Search role or department…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2.5 text-left font-medium">Role</th>
              <th className="px-4 py-2.5 text-left font-medium">Department</th>
              <th className="px-4 py-2.5 text-right font-medium">Short by</th>
              <th className="px-4 py-2.5 text-left font-medium">Level</th>
              <th className="px-4 py-2.5 text-right font-medium">Per hire</th>
              <th className="px-4 py-2.5 text-right font-medium">Total</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={`${row.department}-${row.role}`} className="border-b last:border-0">
                <td className="px-4 py-2.5 font-medium">{row.role}</td>
                <td className="px-4 py-2.5 text-muted">{row.department}</td>
                <td className="px-4 py-2.5 text-right tabular-nums">{row.gap}</td>
                <td className="px-4 py-2.5 text-muted">{row.level}</td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                  {money(row.perHire)}
                </td>
                <td className="px-4 py-2.5 text-right font-medium tabular-nums">
                  {money(row.total)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </WorkforceShell>
  );
}
