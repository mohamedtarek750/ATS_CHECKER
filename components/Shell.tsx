"use client";

import type { ReactNode } from "react";

/** A numbered section. The rail makes the three steps readable at a glance. */
export function Step({
  index,
  title,
  hint,
  done,
  active,
  children,
}: {
  index: number;
  title: string;
  hint?: string;
  done?: boolean;
  active?: boolean;
  children: ReactNode;
}) {
  return (
    <section className="relative animate-rise">
      <div className="mb-4 flex items-center gap-3">
        <span
          className={`step-num border ${
            done
              ? "border-good/30 bg-good-wash text-good"
              : active
                ? "border-transparent bg-accent text-accent-ink"
                : "border-line text-muted"
          }`}
        >
          {done ? "✓" : index}
        </span>
        <div className="min-w-0">
          <h2 className="text-base font-semibold leading-tight">{title}</h2>
          {hint && <p className="text-sm text-muted">{hint}</p>}
        </div>
      </div>
      <div className="pl-0 sm:pl-10">{children}</div>
    </section>
  );
}

export function Stat({
  value,
  label,
  tone = "plain",
}: {
  value: number | string;
  label: string;
  tone?: "plain" | "good" | "warn";
}) {
  const tint =
    tone === "good"
      ? "border-good/25 bg-good-wash"
      : tone === "warn"
        ? "border-warn/25 bg-warn-wash"
        : "border-line raised";
  return (
    <div className={`rounded-lg border px-4 py-3 ${tint}`}>
      <div className="text-2xl font-semibold tabular-nums leading-none">{value}</div>
      <div className="mt-1 text-xs text-muted">{label}</div>
    </div>
  );
}

/** A percentage that also shows how it was reached. */
export function Score({ percent }: { percent: number }) {
  const tone =
    percent >= 80 ? "text-good" : percent >= 50 ? "text-warn" : "text-muted";
  const track =
    percent >= 80 ? "bg-good" : percent >= 50 ? "bg-warn" : "bg-muted/40";
  return (
    <div className="flex shrink-0 items-center gap-3">
      <span className={`w-12 text-right text-lg font-semibold tabular-nums ${tone}`}>
        {percent}%
      </span>
      <span className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-line sm:block">
        <span
          className={`block h-full rounded-full ${track} transition-[width] duration-500`}
          style={{ width: `${percent}%` }}
        />
      </span>
    </div>
  );
}

export function Note({
  tone = "muted",
  children,
}: {
  tone?: "muted" | "warn" | "bad";
  children: ReactNode;
}) {
  const style =
    tone === "warn"
      ? "border-warn/30 bg-warn-wash text-warn"
      : tone === "bad"
        ? "border-bad/30 bg-bad-wash text-bad"
        : "border-line raised text-muted";
  return (
    <p className={`rounded-lg border px-4 py-3 text-sm ${style}`}>{children}</p>
  );
}
