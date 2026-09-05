/**
 * Pay equity: the questions an average salary cannot answer.
 *
 * "Average salary by role" is a fact, not a finding. Every number on a
 * compensation page is one until something compares it to something else, and
 * the comparisons that matter are these four:
 *
 *   1. Spread   - two people doing the same job on very different money.
 *   2. Band     - a whole role sitting below what its grade is worth.
 *   3. Compression - a senior grade paid what the grade below it is paid, so
 *                    promotion buys nothing and the people who took it notice.
 *   4. Experience - one role paid less than another at the same grade despite
 *                   carrying more years.
 *
 * WHAT THIS DOES NOT CLAIM
 * ------------------------
 * It reports a shape, never a cause. A wide spread can be a pay problem or it
 * can be one job title covering two different jobs; the finding says which
 * numbers are unusual and leaves the reason to somebody who knows the team. It
 * also has nothing to say about people - the data is per role, and pay equity
 * between individuals is not a thing this can see or should guess at.
 *
 * The thresholds are constants at the top rather than magic numbers inline,
 * because they are judgement calls and somebody will want to argue with them.
 */

import type { Alert, AlertLevel } from "./alerts";
import type { PayRow, PayLevel } from "./pay";

/**
 * Above this, the same job title is paying very different money.
 *
 * Measured across the middle half of the role, not end to end. A min-to-max
 * range widens with headcount for reasons that have nothing to do with pay -
 * more people means more chance of drawing an extreme - so it reported large
 * teams and stayed quiet about small ones. The interquartile range is the same
 * width whether there are five people in the role or fifty.
 */
const WIDE_SPREAD = 0.3;
/** How far under the band's floor before a role counts as underpaid. */
const BELOW_BAND = 0.95;
/** The uplift a single grade is expected to be worth. Below it, pay is compressed. */
const COMPRESSION_PER_GRADE = 1.12;
/** Years of extra experience before a pay difference is worth remarking on. */
const EXPERIENCE_YEARS = 1.5;
/** A role smaller than this cannot show a spread worth reading. */
const MIN_TEAM = 4;

const RANK: Record<PayLevel, number> = {
  Junior: 0,
  Mid: 1,
  Senior: 2,
  Expert: 3,
};

const money = (n: number) => `${Math.round(n).toLocaleString("en-US")} EGP`;
const percent = (n: number) => `${Math.round(n * 100)}%`;

/**
 * How far apart the same job's pay runs, as a fraction of its median.
 *
 * The middle half - 25th to 75th percentile - rather than lowest to highest.
 * See WIDE_SPREAD: the end-to-end range is a measure of team size as much as
 * of pay policy.
 */
export function spreadOf(row: PayRow): number {
  return row.median > 0 ? (row.p75 - row.p25) / row.median : 0;
}

function worse(a: AlertLevel, b: AlertLevel): AlertLevel {
  const order: AlertLevel[] = ["critical", "warning", "info"];
  return order.indexOf(a) <= order.indexOf(b) ? a : b;
}

/**
 * Every pay finding, most serious first.
 *
 * Returns the same shape the workforce alerts use, so the panel that renders
 * those renders these - a pay problem and a staffing problem are both "a thing
 * a person has to decide about", and two different-looking lists of them would
 * be two places to remember to look.
 */
export function payFindings(
  rows: PayRow[],
  bands: Record<PayLevel, { low: number; high: number }>
): Alert[] {
  const found: Alert[] = [];

  for (const row of rows) {
    // 1. Spread within one role.
    const spread = spreadOf(row);
    if (row.employees >= MIN_TEAM && spread >= WIDE_SPREAD) {
      found.push({
        id: `spread:${row.department}:${row.role}`,
        level: spread >= WIDE_SPREAD * 1.4 ? "critical" : "warning",
        department: row.department,
        source: "payroll",
        title: `${row.role} pay runs from ${money(row.min)} to ${money(row.max)}`,
        detail:
          `The middle half of the role spans ${money(row.p25)} to ` +
          `${money(row.p75)} — ${percent(spread)} of the median, across ` +
          `${row.employees} people. That is not two outliers at the ends; it ` +
          `is most of the team on visibly different money for the same title. ` +
          `Worth knowing whether this is one job or two.`,
      });
    }

    // 2. The whole role below its grade.
    const band = bands[row.level];
    if (band && row.median < band.low * BELOW_BAND) {
      const under = (band.low - row.median) / band.low;
      found.push({
        id: `band:${row.department}:${row.role}`,
        level: under >= 0.15 ? "critical" : "warning",
        department: row.department,
        source: "payroll",
        title: `${row.role} is paid below the ${row.level} band`,
        detail:
          `The median is ${money(row.median)} against a band starting at ` +
          `${money(band.low)} — ${percent(under)} under the floor, across ` +
          `${row.employees} people averaging ${row.avgExperience} years. ` +
          `A role under its band is a role that loses people to whoever pays it.`,
      });
    }
  }

  // 3. Compression: a senior grade paid what the grade below it is paid.
  const byDepartment = new Map<string, PayRow[]>();
  for (const row of rows) {
    byDepartment.set(row.department, [...(byDepartment.get(row.department) ?? []), row]);
  }

  for (const [department, team] of byDepartment) {
    for (const upper of team) {
      for (const lower of team) {
        const grades = RANK[upper.level] - RANK[lower.level];
        if (grades < 1 || lower.median <= 0) continue;

        // Held to the standard for the distance actually being crossed: two
        // grades should be worth about twice what one grade is worth.
        const expected = COMPRESSION_PER_GRADE ** grades;
        if (upper.median > lower.median * expected) continue;

        const step = (upper.median - lower.median) / lower.median;
        found.push({
          id: `compression:${department}:${upper.role}:${lower.role}`,
          level: step <= 0 ? "critical" : "warning",
          department,
          source: "payroll",
          title:
            step <= 0
              ? `${upper.role} is paid less than ${lower.role}, ${grades} ` +
                `grade${grades === 1 ? "" : "s"} below it`
              : `${upper.role} pays only ${percent(step)} more than ${lower.role}`,
          detail:
            `${upper.role} (${upper.level}, ${upper.avgExperience} years on ` +
            `average) has a median of ${money(upper.median)}; ${lower.role} ` +
            `(${lower.level}, ${lower.avgExperience} years) has ` +
            `${money(lower.median)} — ${grades} grade` +
            `${grades === 1 ? "" : "s"} lower. Promotion between the two is ` +
            `worth ${step <= 0 ? "nothing" : percent(step)}, which the people ` +
            `who took it can work out for themselves.`,
        });
      }
    }
  }

  // 4. Same grade, more experience, less money.
  const byLevel = new Map<PayLevel, PayRow[]>();
  for (const row of rows) {
    byLevel.set(row.level, [...(byLevel.get(row.level) ?? []), row]);
  }

  for (const [level, peers] of byLevel) {
    for (const a of peers) {
      // One finding per role, against the peer it is furthest behind. Comparing
      // against all of them produced eight lines about the same role, which is
      // one fact reported eight times.
      let worstPeer: PayRow | null = null;
      let worstBehind = 0;

      for (const b of peers) {
        if (a === b) continue;
        if (a.avgExperience < b.avgExperience + EXPERIENCE_YEARS) continue;
        if (a.median >= b.median) continue;

        const behind = (b.median - a.median) / b.median;
        if (behind < 0.1 || behind <= worstBehind) continue;
        worstPeer = b;
        worstBehind = behind;
      }

      if (!worstPeer) continue;
      found.push({
        id: `experience:${a.department}:${a.role}`,
        level: "info",
        department: a.department,
        source: "payroll",
        title: `${a.role} carries more experience than ${worstPeer.role} and is paid less`,
        detail:
          `Both are graded ${level}. ${a.role} averages ` +
          `${a.avgExperience} years on a median of ${money(a.median)}; ` +
          `${worstPeer.role} averages ${worstPeer.avgExperience} on ` +
          `${money(worstPeer.median)} — ${percent(worstBehind)} more. ` +
          `Different markets can explain this; it is here so somebody checks ` +
          `that one does.`,
      });
    }
  }

  const ORDER: Record<AlertLevel, number> = { critical: 0, warning: 1, info: 2 };
  return found.sort(
    (a, b) => ORDER[a.level] - ORDER[b.level] || a.title.localeCompare(b.title)
  );
}

/** Headline numbers for the top of the page. */
export function paySummary(rows: PayRow[]) {
  const people = rows.reduce((n, r) => n + r.employees, 0);
  // Weighted by team size: a three-person role must not move the company
  // average as much as a thirty-four-person one.
  const bill = rows.reduce((n, r) => n + r.median * r.employees, 0);
  const ranked = [...rows].sort((a, b) => b.median - a.median);
  const spread = [...rows]
    .filter((r) => r.employees >= MIN_TEAM)
    .sort((a, b) => spreadOf(b) - spreadOf(a));

  return {
    people,
    roles: rows.length,
    averageMedian: people > 0 ? Math.round(bill / people) : 0,
    monthlyBill: bill,
    highest: ranked[0] ?? null,
    lowest: ranked[ranked.length - 1] ?? null,
    widest: spread[0] ?? null,
  };
}

/** Median pay by grade, weighted by how many people sit at each. */
export function byLevel(rows: PayRow[], levels: PayLevel[]) {
  return levels.map((level) => {
    const here = rows.filter((r) => r.level === level);
    const people = here.reduce((n, r) => n + r.employees, 0);
    const bill = here.reduce((n, r) => n + r.median * r.employees, 0);
    return {
      level,
      people,
      roles: here.length,
      median: people > 0 ? Math.round(bill / people) : 0,
      low: here.length ? Math.min(...here.map((r) => r.min)) : 0,
      high: here.length ? Math.max(...here.map((r) => r.max)) : 0,
    };
  });
}

export { worse };
