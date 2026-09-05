"use client";

import { useMemo, useState } from "react";
import { Note, Stat } from "@/components/Shell";
import { WorkforceShell, ForecastNote } from "@/components/WorkforceShell";
import { NEUTRAL, runScenario, type Levers } from "@/lib/scenarios";
import { DEFAULT_COST_PER_HIRE, roleStates } from "@/lib/workforce";

const HORIZONS = [3, 6, 12, 24];

/** The ready-made questions, so the page opens with something to press. */
const PRESETS: { name: string; levers: Levers; why: string }[] = [
  {
    name: "As forecast",
    levers: { ...NEUTRAL },
    why: "Every lever at zero. Reproduces the dashboard's own numbers.",
  },
  {
    name: "Turnover +10%",
    levers: { ...NEUTRAL, turnoverDelta: 10 },
    why: "People leave a tenth faster than they do now.",
  },
  {
    name: "Budget −20%",
    levers: { ...NEUTRAL, budgetDelta: -20 },
    why: "A fifth less money to hire with. Something goes unfilled.",
  },
  {
    name: "Workload +15%",
    levers: { ...NEUTRAL, workloadDelta: 15 },
    why: "More to deliver, so every role needs more people.",
  },
  {
    name: "The bad year",
    levers: { turnoverDelta: 20, budgetDelta: -20, workloadDelta: 15, months: 12 },
    why: "All three at once, which is how they usually arrive.",
  },
];

/**
 * The scenario page.
 *
 * The forecast answers one question - how many people each role will need -
 * for the one future its training data implies. The question a planner
 * actually has is the other kind: what happens IF. This does not predict
 * anything; it does arithmetic on assumptions the user sets, and shows the
 * assumptions next to the answer so the answer can be argued with.
 */
export default function ScenariosPage() {
  const [levers, setLevers] = useState<Levers>({ ...NEUTRAL });
  const roles = useMemo(() => roleStates(), []);

  const base = useMemo(
    () => runScenario(roles, { ...NEUTRAL, months: levers.months }, DEFAULT_COST_PER_HIRE),
    [roles, levers.months]
  );
  const result = useMemo(
    () => runScenario(roles, levers, DEFAULT_COST_PER_HIRE),
    [roles, levers]
  );

  const set = (part: Partial<Levers>) => setLevers({ ...levers, ...part });
  const money = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;
  const delta = (now: number, before: number) => {
    const d = now - before;
    if (d === 0) return null;
    return `${d > 0 ? "+" : ""}${d.toLocaleString("en-US")}`;
  };

  return (
    <WorkforceShell
      title="What if"
      intro="Move a lever and every number below is recomputed. Nothing here is a prediction — it is arithmetic on the assumption you set, using the same forecast, turnover and cost figures as the rest of these pages."
    >
      <ForecastNote />

      {/* The questions people actually ask, one press each. */}
      <div className="flex flex-wrap gap-2">
        {PRESETS.map((preset) => {
          const active =
            preset.levers.turnoverDelta === levers.turnoverDelta &&
            preset.levers.budgetDelta === levers.budgetDelta &&
            preset.levers.workloadDelta === levers.workloadDelta;
          return (
            <button
              key={preset.name}
              title={preset.why}
              onClick={() => set({ ...preset.levers, months: levers.months })}
              className={`chip ${
                active ? "bg-accent text-accent-ink" : "raised text-muted hover:text-ink"
              }`}
            >
              {preset.name}
            </button>
          );
        })}
      </div>

      <div className="card space-y-5 px-5 py-5">
        <Slider
          label="Turnover"
          value={levers.turnoverDelta}
          onChange={(turnoverDelta) => set({ turnoverDelta })}
          min={-50}
          max={100}
          hint="Applied as a relative change: +10% means a role losing 10% a year now loses 11%."
        />
        <Slider
          label="Hiring budget"
          value={levers.budgetDelta}
          onChange={(budgetDelta) => set({ budgetDelta })}
          min={-100}
          max={100}
          hint={`Against ${money(base.totals.cost)} — what closing today's gap would cost at the rates on the hiring cost page.`}
        />
        <Slider
          label="Workload"
          value={levers.workloadDelta}
          onChange={(workloadDelta) => set({ workloadDelta })}
          min={-30}
          max={60}
          hint="Scales forecast demand. More to deliver means more people to deliver it."
        />

        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          <span className="text-sm font-medium">Over the next</span>
          {HORIZONS.map((months) => (
            <button
              key={months}
              onClick={() => set({ months })}
              className={`chip ${
                levers.months === months
                  ? "bg-accent text-accent-ink"
                  : "raised text-muted hover:text-ink"
              }`}
            >
              {months} months
            </button>
          ))}
          <button
            className="btn-ghost ml-auto text-sm"
            onClick={() => setLevers({ ...NEUTRAL, months: levers.months })}
          >
            Reset
          </button>
        </div>
      </div>

      {/* -- what falls out ------------------------------------------------ */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          value={result.totals.leavers}
          label={`Expected to leave in ${result.levers.months} months`}
          tone={result.totals.leavers > base.totals.leavers ? "warn" : undefined}
          note={delta(result.totals.leavers, base.totals.leavers) ?? undefined}
        />
        <Stat
          value={result.totals.gap}
          label="Positions short by then"
          tone={result.totals.gap > base.totals.gap ? "bad" : "warn"}
          note={delta(result.totals.gap, base.totals.gap) ?? undefined}
        />
        <Stat
          value={money(result.totals.cost)}
          label="Cost to close it"
          note={
            result.totals.cost !== base.totals.cost
              ? `${result.totals.cost > base.totals.cost ? "+" : "−"}${money(
                  Math.abs(result.totals.cost - base.totals.cost)
                )}`
              : undefined
          }
        />
        <Stat
          value={result.totals.deferred}
          label="Left unfunded"
          tone={result.totals.deferred > 0 ? "bad" : "good"}
          note={
            result.totals.deferred > 0
              ? `${money(result.totals.budget)} covers ${result.totals.funded}`
              : "the budget covers every one"
          }
        />
      </div>

      {result.totals.deferred > 0 && (
        <Note tone="bad">
          <strong className="text-ink">
            {result.totals.deferred} position
            {result.totals.deferred === 1 ? "" : "s"} would go unfilled.
          </strong>{" "}
          The budget is spent most-understaffed-first, measured against the size
          of each team, and cheaper roles break a tie because the same money
          closes more of the gap. That order is a choice, not a fact — it is
          stated here so you can disagree with it.
        </Note>
      )}

      <Projection result={result} />

      {/* -- by department -------------------------------------------------- */}
      <section className="space-y-2">
        <h2 className="font-medium">Which departments feel it</h2>
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2.5 font-medium">Department</th>
                <th className="px-3 py-2.5 text-right font-medium">In post</th>
                <th className="px-3 py-2.5 text-right font-medium">Leaving</th>
                <th className="px-3 py-2.5 text-right font-medium">Needed</th>
                <th className="px-3 py-2.5 text-right font-medium">Short</th>
                <th className="px-3 py-2.5 text-right font-medium">Funded</th>
                <th className="px-4 py-2.5 text-right font-medium">Standing</th>
              </tr>
            </thead>
            <tbody>
              {result.departments.map((row) => (
                <tr key={row.department} className="border-b last:border-0">
                  <td className="px-4 py-2.5">
                    <span className="font-medium">{row.department}</span>
                    {row.deferredRoles.length > 0 && (
                      <span className="mt-0.5 block text-xs text-muted">
                        Deferred: {row.deferredRoles.slice(0, 4).join(", ")}
                        {row.deferredRoles.length > 4 &&
                          ` and ${row.deferredRoles.length - 4} more`}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{row.current}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-muted">
                    {row.leavers > 0 ? `−${row.leavers}` : "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{row.demand}</td>
                  <td className="px-3 py-2.5 text-right font-medium tabular-nums">
                    {row.gap}
                  </td>
                  <td className="px-3 py-2.5 text-right tabular-nums">
                    {row.funded}
                    {row.deferred > 0 && (
                      <span className="text-bad"> / {row.deferred} not</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <span
                      className={`chip ${
                        row.urgency === "critical"
                          ? "bg-bad-wash text-bad"
                          : row.urgency === "high"
                            ? "bg-warn-wash text-warn"
                            : "raised text-muted"
                      }`}
                    >
                      {row.urgency === "critical"
                        ? "Critical"
                        : row.urgency === "high"
                          ? "High"
                          : "Moderate"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* -- the roles that take the hit ------------------------------------ */}
      <section className="space-y-2">
        <h2 className="font-medium">The roles that take it hardest</h2>
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2.5 font-medium">Role</th>
                <th className="px-3 py-2.5 text-right font-medium">Leaving</th>
                <th className="px-3 py-2.5 text-right font-medium">Short</th>
                <th className="px-3 py-2.5 text-right font-medium">Cost</th>
                <th className="px-4 py-2.5 text-right font-medium">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {result.roles
                .filter((r) => r.gap > 0)
                .slice(0, 12)
                .map((row) => (
                  <tr key={`${row.department}:${row.role}`} className="border-b last:border-0">
                    <td className="px-4 py-2.5">
                      <span className="font-medium">{row.role}</span>
                      <span className="mt-0.5 block text-xs text-muted">
                        {row.department} · {row.level} · {row.current} in post
                        {row.rateAfter > 0 && ` · ${row.rateAfter}% turnover`}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-muted">
                      {row.leavers > 0 ? `−${row.leavers}` : "—"}
                    </td>
                    <td className="px-3 py-2.5 text-right font-medium tabular-nums">
                      {row.gap}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-muted">
                      {money(row.costToClose)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {row.deferred === 0 ? (
                        <span className="chip bg-good-wash text-good">Funded</span>
                      ) : row.funded === 0 ? (
                        <span className="chip bg-bad-wash text-bad">Deferred</span>
                      ) : (
                        <span className="chip bg-warn-wash text-warn">
                          {row.funded} of {row.gap}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
    </WorkforceShell>
  );
}

/**
 * Headcount against demand, month by month.
 *
 * Drawn as inline SVG rather than pulled from a charting library: two lines and
 * a filled gap between them do not justify a dependency, and this way the
 * colours are the same tokens as everything else on the page.
 */
function Projection({ result }: { result: ReturnType<typeof runScenario> }) {
  const points = result.projection;
  const width = 720;
  const height = 220;
  const pad = { top: 16, right: 16, bottom: 26, left: 46 };

  const values = points.flatMap((p) => [p.headcount, p.demand]);
  const low = Math.floor(Math.min(...values) * 0.98);
  const high = Math.ceil(Math.max(...values) * 1.02);
  const span = Math.max(1, high - low);
  const last = points[points.length - 1];

  const x = (month: number) =>
    pad.left +
    (month / Math.max(1, result.levers.months)) *
      (width - pad.left - pad.right);
  const y = (value: number) =>
    pad.top + (1 - (value - low) / span) * (height - pad.top - pad.bottom);

  const line = (pick: (p: (typeof points)[number]) => number) =>
    points.map((p, i) => `${i ? "L" : "M"} ${x(p.month)} ${y(pick(p))}`).join(" ");

  const band =
    points.map((p, i) => `${i ? "L" : "M"} ${x(p.month)} ${y(p.demand)}`).join(" ") +
    " " +
    [...points]
      .reverse()
      .map((p) => `L ${x(p.month)} ${y(p.headcount)}`)
      .join(" ") +
    " Z";

  return (
    <section className="space-y-2">
      <h2 className="font-medium">
        Headcount against demand, month by month
      </h2>
      <div className="card overflow-x-auto px-4 py-4">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-auto w-full min-w-[38rem]"
          role="img"
          aria-label={`Projected headcount falling to ${last.headcount} against demand rising to ${last.demand} over ${result.levers.months} months`}
        >
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line
                x1={pad.left}
                x2={width - pad.right}
                y1={y(low + span * t)}
                y2={y(low + span * t)}
                stroke="rgb(var(--line))"
                strokeWidth={1}
              />
              <text
                x={pad.left - 8}
                y={y(low + span * t) + 4}
                textAnchor="end"
                fontSize={11}
                fill="rgb(var(--muted))"
              >
                {Math.round(low + span * t)}
              </text>
            </g>
          ))}

          {/* The gap itself, which is the thing being asked about. */}
          <path d={band} fill="rgb(var(--bad))" opacity={0.09} />
          <path
            d={line((p) => p.demand)}
            fill="none"
            stroke="rgb(var(--brand))"
            strokeWidth={2}
          />
          <path
            d={line((p) => p.headcount)}
            fill="none"
            stroke="rgb(var(--ink))"
            strokeWidth={2}
          />

          {points
            .filter((p) => p.month === 0 || p.month === result.levers.months)
            .map((p) => (
              <text
                key={p.month}
                x={x(p.month)}
                y={height - 8}
                textAnchor={p.month === 0 ? "start" : "end"}
                fontSize={11}
                fill="rgb(var(--muted))"
              >
                {p.month === 0 ? "today" : `${p.month} months`}
              </text>
            ))}
        </svg>

        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-muted">
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-0.5 w-5"
              style={{ background: "rgb(var(--brand))" }}
            />
            Demand — {last.demand} by month {result.levers.months}
          </span>
          <span className="flex items-center gap-1.5">
            <span
              className="inline-block h-0.5 w-5"
              style={{ background: "rgb(var(--ink))" }}
            />
            Headcount if nobody is hired — {last.headcount}
          </span>
          <span>Gap — {last.gap}</span>
        </div>
      </div>
      <p className="text-xs leading-relaxed text-muted">
        The headcount line is what happens with no hiring at all: attrition
        alone, at the rate you set. The workload change is ramped in across the
        horizon rather than applied on day one, because &ldquo;workload rises
        15%&rdquo; describes a year and not a Monday morning.
      </p>
    </section>
  );
}

function Slider({
  label,
  value,
  onChange,
  min,
  max,
  hint,
}: {
  label: string;
  value: number;
  onChange: (n: number) => void;
  min: number;
  max: number;
  hint: string;
}) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">{label}</span>
        <span
          className={`text-sm tabular-nums ${
            value === 0 ? "text-muted" : "font-medium"
          }`}
        >
          {value > 0 ? "+" : ""}
          {value}%
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-brand"
        aria-label={label}
      />
      <span className="mt-1 block text-xs leading-relaxed text-muted">{hint}</span>
    </label>
  );
}
