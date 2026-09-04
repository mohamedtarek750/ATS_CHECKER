"use client";

import Link from "next/link";
import { Stat } from "@/components/Shell";
import { ForecastNote, WorkforceShell } from "@/components/WorkforceShell";
import {
  DEPARTMENTS,
  DEPARTMENT_PERFORMANCE,
  TOTALS,
  urgency,
} from "@/lib/workforce";

const URGENCY_TONE: Record<string, string> = {
  critical: "bg-bad-wash text-bad",
  high: "bg-warn-wash text-warn",
  moderate: "bg-good-wash text-good",
};

export default function WorkforceOverview() {
  const best = DEPARTMENT_PERFORMANCE[0];
  const worst = DEPARTMENT_PERFORMANCE[DEPARTMENT_PERFORMANCE.length - 1];
  const widest = Math.max(...DEPARTMENTS.map((d) => d.Predicted));

  return (
    <WorkforceShell
      title={`${TOTALS.gap} more people are needed across the floor`}
      intro={`Forecast headcount for the coming quarter: ${TOTALS.predicted} positions against ${TOTALS.current} filled, across ${TOTALS.departments} departments and ${TOTALS.roles} roles. Open a department to see which of its roles the gap sits in.`}
    >
      <ForecastNote />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat value={TOTALS.current} label="Currently employed" />
        <Stat value={TOTALS.predicted} label="Forecast demand" tone="warn" />
        <Stat value={`+${TOTALS.gap}`} label="Positions to fill" tone="warn" />
        <Stat value={TOTALS.departments} label="Departments" />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat value={`${TOTALS.avgPerformance} / 5`} label="Average performance" tone="good" />
        <Stat value={`${TOTALS.avgExperience} yrs`} label="Average experience" />
        <Stat value={best.Department} label="Highest performing" tone="good" />
        <Stat value={worst.Department} label="Lowest performing" />
      </div>

      <section>
        <div className="mb-2 flex items-baseline justify-between">
          <h3 className="text-sm font-medium">Departments</h3>
          <span className="text-xs text-muted">
            Filled against forecast · open one for its roles
          </span>
        </div>

        <div className="grid gap-2.5 sm:grid-cols-2">
          {DEPARTMENTS.map((dept) => {
            const level = urgency(dept.Gap, dept.Current);
            return (
              <Link
                key={dept.Department}
                href={`/workforce/roles?dept=${encodeURIComponent(dept.Department)}`}
                className="card block px-4 py-3 transition hover:bg-raised"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{dept.Department}</div>
                    <div className="text-xs text-muted">
                      {dept.Roles} role{dept.Roles === 1 ? "" : "s"}
                    </div>
                  </div>
                  <span className={`chip shrink-0 ${URGENCY_TONE[level]}`}>
                    {level === "critical"
                      ? "Critical"
                      : level === "high"
                        ? "High"
                        : "Moderate"}
                  </span>
                </div>

                <div className="mt-3 space-y-1.5">
                  <Bar label="Now" value={dept.Current} peak={widest} tone="bg-muted" />
                  <Bar label="Needed" value={dept.Predicted} peak={widest} tone="bg-warn" />
                </div>

                <div className="mt-2.5 border-t pt-2 text-xs text-muted">
                  Short by <strong className="text-bad">{dept.Gap}</strong>
                </div>
              </Link>
            );
          })}
        </div>
      </section>
    </WorkforceShell>
  );
}

function Bar({
  label,
  value,
  peak,
  tone,
}: {
  label: string;
  value: number;
  peak: number;
  tone: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-12 shrink-0 text-[11px] text-muted">{label}</span>
      <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full raised">
        <span
          className={`block h-full rounded-full ${tone}`}
          style={{ width: `${(value / peak) * 100}%` }}
        />
      </span>
      <span className="w-8 shrink-0 text-right text-[11px] tabular-nums text-muted">
        {value}
      </span>
    </div>
  );
}
