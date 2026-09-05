"use client";

import Link from "next/link";
import { useState } from "react";
import { FORECAST } from "@/lib/workforce";
import type { Alert, AlertLevel } from "@/lib/alerts";

const SOURCE_LABEL: Record<Alert["source"], string> = {
  forecast: "Forecast",
  live: "Live",
  payroll: "Payroll",
};

const TONE: Record<AlertLevel, { chip: string; label: string; edge: string }> = {
  critical: {
    chip: "bg-bad-wash text-bad",
    label: "Critical",
    edge: "rgb(var(--bad))",
  },
  warning: {
    chip: "bg-warn-wash text-warn",
    label: "Warning",
    edge: "rgb(var(--warn))",
  },
  info: { chip: "raised text-muted", label: "Note", edge: "rgb(var(--line))" },
};

/**
 * The alerts panel.
 *
 * Two things it deliberately does NOT do. It does not render when there is
 * nothing to say - an empty "no alerts" box trains people to skip the place
 * alerts appear. And it does not hide where its numbers came from: the gap
 * figures are a frozen forecast sitting next to live application counts, and a
 * reader has to be able to tell which is which without leaving the page.
 */
export function Alerts({
  alerts,
  limit = 4,
  title = "Alerts",
  href,
}: {
  alerts: Alert[];
  limit?: number;
  title?: string;
  /** Where the full feed lives, when this is a summary of it. */
  href?: string;
}) {
  const [all, setAll] = useState(false);
  if (alerts.length === 0) return null;

  const shown = all ? alerts : alerts.slice(0, limit);
  const hidden = alerts.length - shown.length;
  // Only the sources actually present are explained. A standing paragraph
  // about data this panel is not showing is a paragraph nobody finishes.
  const uses = (source: Alert["source"]) => alerts.some((a) => a.source === source);

  return (
    <section className="space-y-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="font-medium">{title}</h2>
        <span className="text-sm text-muted">
          {alerts.length} finding{alerts.length === 1 ? "" : "s"}
        </span>
        {href && (
          <Link href={href} className="ml-auto text-sm text-muted hover:text-ink">
            Notifications &rarr;
          </Link>
        )}
      </div>

      {shown.map((alert) => {
        const tone = TONE[alert.level];
        return (
          <div
            key={alert.id}
            className="card animate-rise px-4 py-3.5"
            style={{ borderLeft: `3px solid ${tone.edge}` }}
          >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className={`chip ${tone.chip}`}>{tone.label}</span>
              {alert.department && (
                <span className="chip raised text-muted">{alert.department}</span>
              )}
              {/* Which kind of number this rests on. The whole panel mixes a
                  frozen forecast with live counts, and the difference decides
                  how much weight a reader should put on it. */}
              <span className="chip raised text-muted">
                {SOURCE_LABEL[alert.source]}
              </span>
            </div>

            <p className="mt-2 font-medium">{alert.title}</p>
            <p className="mt-1 text-sm leading-relaxed text-muted">
              {alert.detail}
            </p>

            {alert.action_href && (
              <Link
                href={alert.action_href}
                className="mt-2.5 inline-block text-sm font-medium text-brand hover:underline"
              >
                {alert.action_label || "Open"} →
              </Link>
            )}
          </div>
        );
      })}

      {hidden > 0 && (
        <button className="btn-ghost text-sm" onClick={() => setAll(true)}>
          Show {hidden} more
        </button>
      )}
      {all && alerts.length > limit && (
        <button className="btn-ghost text-sm" onClick={() => setAll(false)}>
          Show fewer
        </button>
      )}

      {(uses("forecast") || uses("payroll")) && (
        <p className="pt-0.5 text-xs leading-relaxed text-muted">
          {uses("forecast") && (
            <>
              Anything marked <strong className="text-ink">Forecast</strong>{" "}
              rests on the workforce model — a {FORECAST.model} trained on{" "}
              {FORECAST.trainedOn} and unchanged since, not live HR data.{" "}
            </>
          )}
          {uses("payroll") && (
            <>
              Anything marked <strong className="text-ink">Payroll</strong> rests
              on simulated pay data, not ACUD&rsquo;s payroll.{" "}
            </>
          )}
          {uses("live") && (
            <>
              Counts marked <strong className="text-ink">Live</strong> are
              current as of this page.
            </>
          )}
        </p>
      )}
    </section>
  );
}
