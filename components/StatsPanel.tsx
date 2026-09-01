"use client";

import { useEffect, useState } from "react";
import { Note } from "./Shell";
import { vacancyStats, type VacancyStats } from "@/lib/api";

/**
 * What a vacancy's applications add up to.
 *
 * The counts are the easy half. The half worth having is "what nobody meets":
 * a must-have that none of two hundred applicants satisfies is usually not a
 * shortage of talent, it is an advert asking for the wrong thing, or asking for
 * a tool by a name nobody writes on a CV. Nothing else here can tell a
 * recruiter that, and it is the difference between "we got no good candidates"
 * and "we asked the wrong question".
 */
export function StatsPanel({ slug }: { slug: string }) {
  const [stats, setStats] = useState<VacancyStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    vacancyStats(slug)
      .then((s) => live && setStats(s))
      .catch(
        (e) => live && setError(e instanceof Error ? e.message : "Could not load.")
      );
    return () => {
      live = false;
    };
  }, [slug]);

  if (error) return <Note tone="warn">{error}</Note>;
  if (!stats) return <p className="text-sm text-muted">Working it out…</p>;
  if (stats.total === 0) {
    return <Note>Nothing to summarise until somebody applies.</Note>;
  }

  const peak = Math.max(1, ...stats.per_day.map(([, n]) => n));
  const unmet = stats.hardest.filter((d) => d.importance === "must_have" && d.percent === 0);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-x-8 gap-y-3 text-sm">
        <Figure label="Applied" value={stats.total} />
        <Figure label="Read" value={stats.read} />
        {stats.pending > 0 && <Figure label="Not read yet" value={stats.pending} />}
        {stats.unreadable > 0 && (
          <Figure label="Not a readable CV" value={stats.unreadable} />
        )}
        {stats.read > 0 && (
          <>
            <Figure label="Average match" value={`${stats.average_percent}%`} />
            <Figure label="Median match" value={`${stats.median_percent}%`} />
          </>
        )}
      </div>

      {stats.per_day.length > 1 && (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
            Applications by day
          </p>
          <div className="flex items-end gap-1" style={{ height: "3.5rem" }}>
            {stats.per_day.map(([day, count]) => (
              <div
                key={day}
                className="min-w-[0.5rem] flex-1 rounded-t bg-accent/70"
                style={{ height: `${Math.max(8, (count / peak) * 100)}%` }}
                title={`${day}: ${count}`}
              />
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-muted">
            <span>{stats.per_day[0][0]}</span>
            <span>{stats.per_day[stats.per_day.length - 1][0]}</span>
          </div>
        </div>
      )}

      {stats.hardest.length > 0 && stats.sampled > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted">
            What applicants meet
          </p>

          {unmet.length > 0 && (
            <Note tone="warn">
              {unmet.length === 1 ? "One requirement is" : `${unmet.length} requirements are`}{" "}
              met by nobody who applied:{" "}
              <strong>{unmet.map((d) => d.requirement).join(", ")}</strong>. Worth
              asking whether the advert is describing it the way candidates would.
            </Note>
          )}

          <ul className="mt-2 space-y-1.5 text-sm">
            {stats.hardest.map((demand) => (
              <li key={demand.requirement} className="flex items-center gap-3">
                <span
                  className={`w-28 shrink-0 text-xs ${
                    demand.importance === "must_have" ? "text-ink" : "text-muted"
                  }`}
                >
                  {demand.importance === "must_have" ? "Required" : "Preferred"}
                </span>
                <span className="min-w-0 flex-1 truncate">{demand.requirement}</span>
                <span className="h-1.5 w-24 shrink-0 overflow-hidden rounded-full raised">
                  <span
                    className={`block h-full ${
                      demand.percent === 0
                        ? "bg-bad"
                        : demand.percent < 40
                          ? "bg-warn"
                          : "bg-good"
                    }`}
                    style={{ width: `${demand.percent}%` }}
                  />
                </span>
                <span className="w-20 shrink-0 text-right text-xs tabular-nums text-muted">
                  {demand.met}/{demand.total}
                </span>
              </li>
            ))}
          </ul>

          <p className="mt-2 text-xs text-muted">
            {stats.sample_capped
              ? `Measured over the first ${stats.sampled} applications that were read.`
              : `Measured over all ${stats.sampled} applications that were read.`}
          </p>
        </div>
      )}
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string | number }) {
  return (
    <span>
      <span className="block text-xl font-semibold tabular-nums">{value}</span>
      <span className="block text-xs text-muted">{label}</span>
    </span>
  );
}
