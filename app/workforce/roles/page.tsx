"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ForecastNote, WorkforceShell } from "@/components/WorkforceShell";
import { DEPARTMENTS, ROLES } from "@/lib/workforce";

export default function RolesPage() {
  return (
    <Suspense fallback={null}>
      <Roles />
    </Suspense>
  );
}

function Roles() {
  const params = useSearchParams();
  const [dept, setDept] = useState(params.get("dept") ?? "");
  const [search, setSearch] = useState("");

  const needle = search.trim().toLowerCase();
  const visible = ROLES.filter(
    (role) =>
      (!dept || role.Department === dept) &&
      (!needle ||
        role.Job_Role.toLowerCase().includes(needle) ||
        role.Department.toLowerCase().includes(needle))
  );
  const shortfall = visible.reduce((n, r) => n + r.Predicted_Workforce_Gap, 0);

  return (
    <WorkforceShell
      title="Roles"
      intro="Every role the forecast covers, and how far short of demand it is. The gap is what the ATS next door is there to fill."
    >
      <ForecastNote />

      <div className="flex flex-wrap items-center gap-2">
        <input
          className="field min-w-0 flex-1"
          placeholder="Search role or department…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="field shrink-0"
          value={dept}
          onChange={(e) => setDept(e.target.value)}
        >
          <option value="">All departments</option>
          {DEPARTMENTS.map((d) => (
            <option key={d.Department} value={d.Department}>
              {d.Department}
            </option>
          ))}
        </select>
      </div>

      <p className="text-xs text-muted">
        {visible.length} role{visible.length === 1 ? "" : "s"} · {shortfall}{" "}
        position{shortfall === 1 ? "" : "s"} to fill
        {(dept || needle) && (
          <>
            {" · "}
            <button
              className="underline"
              onClick={() => {
                setDept("");
                setSearch("");
              }}
            >
              Clear
            </button>
          </>
        )}
      </p>

      {visible.length === 0 ? (
        <p className="text-sm text-muted">Nothing matches that.</p>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2.5 text-left font-medium">Role</th>
                <th className="px-4 py-2.5 text-left font-medium">Department</th>
                <th className="px-4 py-2.5 text-right font-medium">Now</th>
                <th className="px-4 py-2.5 text-right font-medium">Needed</th>
                <th className="px-4 py-2.5 text-right font-medium">Short by</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((role) => (
                <tr
                  key={`${role.Department}-${role.Job_Role}`}
                  className="border-b last:border-0"
                >
                  <td className="px-4 py-2.5 font-medium">{role.Job_Role}</td>
                  <td className="px-4 py-2.5 text-muted">{role.Department}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {role.Current_Employees}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {role.Predicted_Workforce_Demand}
                  </td>
                  <td className="px-4 py-2.5 text-right font-medium tabular-nums text-bad">
                    +{role.Predicted_Workforce_Gap}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-sm text-muted">
        A gap here is a job waiting to be advertised.{" "}
        <Link href="/admin" className="underline hover:text-ink">
          Add it as a job and share its link →
        </Link>
      </p>
    </WorkforceShell>
  );
}
