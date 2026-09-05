/**
 * The scenario model: what the workforce looks like under a different set of
 * assumptions from the ones the forecast was trained on.
 *
 * The forecast answers one question — how many people each role will need —
 * and answers it for one future, the one the training data implies. A planner's
 * actual question is the other kind: what happens IF people start leaving
 * faster, IF the hiring budget is cut, IF the workload grows. Those are not
 * predictions and this does not pretend they are. They are arithmetic on stated
 * assumptions, and the assumptions are the input.
 *
 * WHAT MAKES THIS HONEST RATHER THAN A RANDOM NUMBER GENERATOR
 * -----------------------------------------------------------
 * Every output traces to an input the user set or a figure already on the
 * dashboard. Nothing is invented in here: attrition comes from the measured
 * turnover rate, demand comes from the forecast, prices come from the cost
 * table the user can edit. Change a lever by nothing and the model returns the
 * dashboard's own numbers - which is the property that makes the rest of it
 * believable, and it is asserted in the tests.
 *
 * THE BUDGET IS THE ONLY PLACE THE MODEL MAKES A CHOICE
 * ----------------------------------------------------
 * Cutting the budget forces a decision the data cannot make: which positions
 * go unfilled. The rule is stated rather than hidden - most understaffed first,
 * measured against the size of the team, and cheaper roles break the tie
 * because the same money closes more of the gap. A planner who disagrees with
 * that order is disagreeing with something they can see.
 */

export type Level = "Junior" | "Mid" | "Senior" | "Expert";
export type Urgency = "critical" | "high" | "moderate";

/** One role as the dashboard already knows it, before any scenario is applied. */
export interface RoleState {
  department: string;
  role: string;
  current: number;
  /** The forecast's demand for this role, unmodified. */
  demand: number;
  /** Measured annual turnover, as a percentage. 0 where none was recorded. */
  turnoverRate: number;
  level: Level;
}

export interface Levers {
  /** Relative change to every turnover rate. +10 means a 10% rate becomes 11%. */
  turnoverDelta: number;
  /** Relative change to the budget that would close today's gap. */
  budgetDelta: number;
  /** Relative change to forecast demand. Standing in for more work to do. */
  workloadDelta: number;
  /** How far ahead to run it. Attrition is annual, so this scales it. */
  months: number;
}

export const NEUTRAL: Levers = {
  turnoverDelta: 0,
  budgetDelta: 0,
  workloadDelta: 0,
  months: 12,
};

export interface RoleOutcome extends RoleState {
  /** Demand after the workload lever. */
  demandAfter: number;
  /** Turnover rate after the turnover lever. */
  rateAfter: number;
  /** People expected to leave this role within the horizon. */
  leavers: number;
  /** Who is left if nobody is hired. */
  headcount: number;
  /** What the role is short by then. Never negative - a surplus is not a gap. */
  gap: number;
  costPerHire: number;
  costToClose: number;
  /** Positions the budget actually pays for. */
  funded: number;
  /** Positions the budget does not reach. */
  deferred: number;
  urgency: Urgency;
}

export interface DepartmentOutcome {
  department: string;
  current: number;
  leavers: number;
  headcount: number;
  demand: number;
  gap: number;
  funded: number;
  deferred: number;
  cost: number;
  urgency: Urgency;
  /** Roles the budget could not reach, worst first. Empty when all are funded. */
  deferredRoles: string[];
}

export interface ScenarioResult {
  levers: Levers;
  roles: RoleOutcome[];
  departments: DepartmentOutcome[];
  totals: {
    current: number;
    leavers: number;
    headcount: number;
    demand: number;
    gap: number;
    funded: number;
    deferred: number;
    /** What closing the whole gap would cost at the given prices. */
    cost: number;
    /** What the budget allows after the lever. */
    budget: number;
    /** The cost of the positions that get funded. */
    spend: number;
    criticalDepartments: number;
  };
  /** One point per month from now to the horizon, for the chart. */
  projection: { month: number; headcount: number; demand: number; gap: number }[];
}

/** How badly short a role is, relative to the size of the team it sits in. */
export function urgencyOf(gap: number, current: number): Urgency {
  const share = current > 0 ? gap / current : gap > 0 ? 1 : 0;
  if (share >= 0.2) return "critical";
  if (share >= 0.12) return "high";
  return "moderate";
}

const WORSE: Record<Urgency, number> = { critical: 0, high: 1, moderate: 2 };

function round(n: number): number {
  return Math.round(n * 100) / 100;
}

/**
 * Run the levers over the roles and say what falls out.
 *
 * `prices` is the same cost-per-hire table the cost page exposes, so a planner
 * who has corrected those numbers sees the correction here too.
 */
export function runScenario(
  roles: RoleState[],
  levers: Levers,
  prices: Record<Level, number>
): ScenarioResult {
  const months = Math.max(1, levers.months);
  const workload = 1 + levers.workloadDelta / 100;
  const churn = 1 + levers.turnoverDelta / 100;

  // The budget being cut or raised is the one that would close TODAY's gap at
  // today's prices - a number already on the cost page, so the lever moves
  // something the planner has seen rather than an abstraction.
  const baseline = roles.reduce(
    (sum, r) => sum + Math.max(0, r.demand - r.current) * (prices[r.level] ?? 0),
    0
  );
  const budget = Math.max(0, Math.round(baseline * (1 + levers.budgetDelta / 100)));

  const outcomes: RoleOutcome[] = roles.map((role) => {
    const rateAfter = round(role.turnoverRate * churn);
    // Annual rate, scaled to the horizon. Rounded once, at the end, so a role
    // losing half a person over six months is not silently losing nobody.
    const leavers = Math.round((role.current * rateAfter) / 100 * (months / 12));
    const headcount = Math.max(0, role.current - leavers);
    const demandAfter = Math.round(role.demand * workload);
    const gap = Math.max(0, demandAfter - headcount);
    const costPerHire = prices[role.level] ?? 0;

    return {
      ...role,
      demandAfter,
      rateAfter,
      leavers,
      headcount,
      gap,
      costPerHire,
      costToClose: gap * costPerHire,
      funded: 0,
      deferred: gap,
      urgency: urgencyOf(gap, role.current),
    };
  });

  // Spend the budget. Most understaffed first; where two roles are equally
  // short, the cheaper one goes first because the same money closes more of
  // the gap. Position by position, so a role can be part-funded.
  const queue = [...outcomes].sort(
    (a, b) =>
      WORSE[a.urgency] - WORSE[b.urgency] ||
      b.gap / Math.max(1, b.current) - a.gap / Math.max(1, a.current) ||
      a.costPerHire - b.costPerHire
  );

  let left = budget;
  let spend = 0;
  for (const role of queue) {
    while (role.funded < role.gap && role.costPerHire <= left) {
      role.funded += 1;
      left -= role.costPerHire;
      spend += role.costPerHire;
    }
    // A free role (price not set) is funded outright rather than blocking.
    if (role.costPerHire === 0) role.funded = role.gap;
    role.deferred = role.gap - role.funded;
  }

  const byDepartment = new Map<string, DepartmentOutcome>();
  for (const role of outcomes) {
    const row =
      byDepartment.get(role.department) ??
      {
        department: role.department,
        current: 0, leavers: 0, headcount: 0, demand: 0,
        gap: 0, funded: 0, deferred: 0, cost: 0,
        urgency: "moderate" as Urgency,
        deferredRoles: [] as string[],
      };
    row.current += role.current;
    row.leavers += role.leavers;
    row.headcount += role.headcount;
    row.demand += role.demandAfter;
    row.gap += role.gap;
    row.funded += role.funded;
    row.deferred += role.deferred;
    row.cost += role.costToClose;
    if (role.deferred > 0) row.deferredRoles.push(role.role);
    byDepartment.set(role.department, row);
  }

  const departments = [...byDepartment.values()].map((row) => ({
    ...row,
    urgency: urgencyOf(row.gap, row.current),
  }));
  departments.sort(
    (a, b) => WORSE[a.urgency] - WORSE[b.urgency] || b.gap - a.gap
  );

  const totals = {
    current: outcomes.reduce((n, r) => n + r.current, 0),
    leavers: outcomes.reduce((n, r) => n + r.leavers, 0),
    headcount: outcomes.reduce((n, r) => n + r.headcount, 0),
    demand: outcomes.reduce((n, r) => n + r.demandAfter, 0),
    gap: outcomes.reduce((n, r) => n + r.gap, 0),
    funded: outcomes.reduce((n, r) => n + r.funded, 0),
    deferred: outcomes.reduce((n, r) => n + r.deferred, 0),
    cost: outcomes.reduce((n, r) => n + r.costToClose, 0),
    budget,
    spend,
    criticalDepartments: departments.filter((d) => d.urgency === "critical").length,
  };

  return {
    levers: { ...levers, months },
    roles: outcomes.sort(
      (a, b) => WORSE[a.urgency] - WORSE[b.urgency] || b.gap - a.gap
    ),
    departments,
    totals,
    projection: project(roles, levers, months),
  };
}

/**
 * The same arithmetic month by month, for the chart.
 *
 * Attrition accumulates smoothly; the workload change is ramped in over the
 * horizon rather than applied on day one, because "workload rises 15%"
 * describes a year, not a Monday morning.
 */
function project(
  roles: RoleState[],
  levers: Levers,
  months: number
): ScenarioResult["projection"] {
  const churn = 1 + levers.turnoverDelta / 100;
  const current = roles.reduce((n, r) => n + r.current, 0);
  const demandNow = roles.reduce((n, r) => n + r.demand, 0);
  const demandEnd = roles.reduce(
    (n, r) => n + Math.round(r.demand * (1 + levers.workloadDelta / 100)),
    0
  );
  const annualLeavers = roles.reduce(
    (n, r) => n + (r.current * r.turnoverRate * churn) / 100,
    0
  );

  const points = [];
  for (let month = 0; month <= months; month += 1) {
    const headcount = Math.round(current - (annualLeavers * month) / 12);
    const demand = Math.round(
      demandNow + ((demandEnd - demandNow) * month) / months
    );
    points.push({ month, headcount, demand, gap: Math.max(0, demand - headcount) });
  }
  return points;
}
