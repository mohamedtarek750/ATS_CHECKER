"use client";

import { useMemo, useState } from "react";
import { Alerts } from "@/components/Alerts";
import { Note, Stat } from "@/components/Shell";
import { WorkforceShell } from "@/components/WorkforceShell";
import { byLevel, paySummary, payFindings, spreadOf } from "@/lib/equity";
import { BANDS, PAY, type PayLevel, type PayRow } from "@/lib/pay";

const LEVELS: PayLevel[] = ["Junior", "Mid", "Senior", "Expert"];

/**
 * Pay, and the questions an average cannot answer.
 *
 * The averages are here because people ask for them, but they are the least
 * useful thing on the page: every figure in a compensation report is a fact
 * until something compares it to something else. The findings panel at the top
 * is the comparison, and it is deliberately first.
 */
export default function CompensationPage() {
  const [level, setLevel] = useState<PayLevel | "all">("all");
  const [search, setSearch] = useState("");

  const findings = useMemo(() => payFindings(PAY, BANDS), []);
  const summary = useMemo(() => paySummary(PAY), []);
  const grades = useMemo(() => byLevel(PAY, LEVELS), []);

  const needle = search.trim().toLowerCase();
  const rows = PAY.filter(
    (r) =>
      (level === "all" || r.level === level) &&
      (!needle ||
        r.role.toLowerCase().includes(needle) ||
        r.department.toLowerCase().includes(needle))
  ).sort((a, b) => b.median - a.median);

  const money = (n: number) => `${Math.round(n).toLocaleString("en-US")}`;
  const ceiling = Math.max(...PAY.map((r) => r.max));

  return (
    <WorkforceShell
      title="Compensation"
      intro="What each role is paid, and where the pay stops making sense next to itself."
    >
      <Note tone="warn">
        <strong className="text-ink">
          These salaries are simulated. They are not ACUD&rsquo;s payroll.
        </strong>{" "}
        The workforce dataset behind this system carries no pay data at all, so
        this page runs on a generated table with bands that follow seniority.
        The analysis is real and the numbers are not — replace{" "}
        <code>lib/pay.ts</code> with a payroll export of the same shape and
        every figure here becomes true without another line changing.
      </Note>

      {/* First, because it is the only part that is analysis rather than record. */}
      <Alerts alerts={findings} title="Pay equity" limit={4} />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          value={money(summary.averageMedian)}
          label="Average pay, weighted by team size"
          note="EGP per month"
        />
        <Stat
          value={money(summary.monthlyBill)}
          label="Monthly bill across every role"
          note="EGP"
        />
        <Stat
          value={summary.highest?.role ?? "—"}
          label="Highest paid role"
          note={summary.highest ? `${money(summary.highest.median)} median` : undefined}
        />
        <Stat
          value={summary.widest?.role ?? "—"}
          label="Widest spread in one role"
          tone="warn"
          note={
            summary.widest
              ? `middle half spans ${Math.round(spreadOf(summary.widest) * 100)}% of median`
              : undefined
          }
        />
      </div>

      {/* -- the grades ----------------------------------------------------- */}
      <section className="space-y-2">
        <h2 className="font-medium">What each grade pays</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {grades.map((grade) => {
            const band = BANDS[grade.level];
            const inside =
              grade.median >= band.low && grade.median <= band.high;
            return (
              <div key={grade.level} className="card px-4 py-3.5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">{grade.level}</span>
                  <span className="text-xs text-muted">
                    {grade.people} people · {grade.roles} roles
                  </span>
                </div>
                <p className="mt-2 text-xl font-semibold tabular-nums leading-none">
                  {money(grade.median)}
                </p>
                <p className="mt-1 text-xs text-muted">median, EGP per month</p>

                {/* Where the grade actually sits inside its own band. */}
                <div className="mt-3">
                  <Band
                    low={band.low}
                    high={band.high}
                    min={grade.low}
                    max={grade.high}
                    median={grade.median}
                  />
                  <p className="mt-1.5 text-xs text-muted">
                    Band {money(band.low)}–{money(band.high)}.{" "}
                    {inside ? (
                      "The median sits inside it."
                    ) : (
                      <span className="text-bad">
                        The median sits{" "}
                        {grade.median < band.low ? "below" : "above"} it.
                      </span>
                    )}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* -- every role ----------------------------------------------------- */}
      <section className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="mr-auto font-medium">Every role</h2>
          <button
            onClick={() => setLevel("all")}
            className={`chip ${
              level === "all" ? "bg-accent text-accent-ink" : "raised text-muted"
            }`}
          >
            All
          </button>
          {LEVELS.map((one) => (
            <button
              key={one}
              onClick={() => setLevel(one)}
              className={`chip ${
                level === one ? "bg-accent text-accent-ink" : "raised text-muted"
              }`}
            >
              {one}
            </button>
          ))}
        </div>

        <input
          className="field w-full"
          placeholder="Search a role or a department…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2.5 font-medium">Role</th>
                <th className="px-3 py-2.5 text-right font-medium">People</th>
                <th className="px-3 py-2.5 text-right font-medium">Years</th>
                <th className="px-3 py-2.5 text-right font-medium">Median</th>
                <th className="w-52 px-4 py-2.5 font-medium">Range</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.department}:${row.role}`} className="border-b last:border-0">
                  <td className="px-4 py-2.5">
                    <span className="font-medium">{row.role}</span>
                    <span className="mt-0.5 block text-xs text-muted">
                      {row.department} · {row.level}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {row.employees}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-muted">
                    {row.avgExperience}
                  </td>
                  <td className="px-3 py-2.5 text-right font-medium tabular-nums">
                    {money(row.median)}
                  </td>
                  <td className="px-4 py-2.5">
                    <Spread row={row} ceiling={ceiling} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && (
            <p className="px-4 py-6 text-center text-sm text-muted">
              Nothing matches that.
            </p>
          )}
        </div>
        <p className="text-xs leading-relaxed text-muted">
          The bar runs from the lowest to the highest paid person in the role;
          the solid part is the middle half, between the 25th and 75th
          percentile, and the notch is the median. A long bar with a short solid
          middle is one or two people a long way from everybody else.
        </p>
      </section>
    </WorkforceShell>
  );
}

/** One role's pay, drawn on the same scale as every other role's. */
function Spread({ row, ceiling }: { row: PayRow; ceiling: number }) {
  const at = (value: number) => `${(value / ceiling) * 100}%`;
  const wide = spreadOf(row) >= 0.6;

  return (
    <div className="relative h-4 w-full rounded bg-raised" title={`${row.min}–${row.max}`}>
      <div
        className="absolute top-1.5 h-1 rounded"
        style={{
          left: at(row.min),
          width: at(row.max - row.min),
          background: wide ? "rgb(var(--bad) / 0.35)" : "rgb(var(--line))",
        }}
      />
      <div
        className="absolute top-0.5 h-3 rounded"
        style={{
          left: at(row.p25),
          width: at(row.p75 - row.p25),
          background: wide ? "rgb(var(--bad) / 0.5)" : "rgb(var(--muted) / 0.35)",
        }}
      />
      <div
        className="absolute top-0 h-4 w-0.5"
        style={{ left: at(row.median), background: "rgb(var(--ink))" }}
      />
    </div>
  );
}

/** A grade's own range against the band it is supposed to sit in. */
function Band({
  low,
  high,
  min,
  max,
  median,
}: {
  low: number;
  high: number;
  min: number;
  max: number;
  median: number;
}) {
  const from = Math.min(low, min);
  const to = Math.max(high, max);
  const at = (value: number) => `${((value - from) / (to - from)) * 100}%`;

  return (
    <div className="relative h-4 w-full rounded bg-raised">
      {/* The band, as the reference. */}
      <div
        className="absolute top-0 h-4 rounded"
        style={{
          left: at(low),
          width: at(high) === at(low) ? "2px" : `${((high - low) / (to - from)) * 100}%`,
          background: "rgb(var(--good) / 0.16)",
        }}
      />
      <div
        className="absolute top-1.5 h-1 rounded"
        style={{
          left: at(min),
          width: `${((max - min) / (to - from)) * 100}%`,
          background: "rgb(var(--muted) / 0.45)",
        }}
      />
      <div
        className="absolute top-0 h-4 w-0.5"
        style={{ left: at(median), background: "rgb(var(--ink))" }}
      />
    </div>
  );
}
