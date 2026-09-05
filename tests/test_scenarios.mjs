/**
 * The scenario model and the pay-equity analysis.
 *
 * Both take assumptions and produce numbers a planner would act on, which makes
 * them the two places in this project where a plausible-looking wrong answer
 * would do the most damage. The tests are about the properties that make the
 * output trustworthy rather than about specific figures:
 *
 *   - Neutral levers reproduce the dashboard's own numbers. If they do not,
 *     nothing else the model says is worth reading.
 *   - Every lever moves the total in the direction it claims to.
 *   - A budget is never overspent, and what it cannot reach is reported rather
 *     than quietly dropped.
 *   - The equity checks find the problems planted in the data, and stay quiet
 *     about roles that do not have one.
 *
 * Run: node tests/test_scenarios.mjs
 */

import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const load = (name) =>
  import("file://" + join(here, "..", "lib", name).replace(/\\/g, "/"));

const { runScenario, urgencyOf, NEUTRAL } = await load("scenarios.ts");
const { payFindings, paySummary, byLevel, spreadOf } = await load("equity.ts");
const { PAY, BANDS } = await load("pay.ts");

const PRICES = { Junior: 3000, Mid: 5000, Senior: 8000, Expert: 12000 };

const team = [
  {
    department: "Engineering",
    role: "Civil Engineer",
    current: 34,
    demand: 37,
    turnoverRate: 6,
    level: "Mid",
  },
  {
    department: "Finance",
    role: "Auditor",
    current: 17,
    demand: 20,
    turnoverRate: 17.6,
    level: "Expert",
  },
  {
    department: "Legal",
    role: "Legal Counsel",
    current: 4,
    demand: 6,
    turnoverRate: 0,
    level: "Mid",
  },
];

let failures = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`  PASS  ${name}`);
  } catch (error) {
    failures += 1;
    console.log(`  FAIL  ${name}: ${error.message}`);
  }
}

const run = (levers = {}) =>
  runScenario(team, { ...NEUTRAL, ...levers }, PRICES);

// -- the property everything else rests on ----------------------------------
test("with every lever at zero and no time passing, nothing changes", () => {
  // The model has to agree with the dashboard before it is allowed to disagree
  // with it. Zero months means no attrition, so this is the forecast exactly.
  const result = runScenario(team, { ...NEUTRAL, months: 0 }, PRICES);
  assert.equal(result.totals.current, 55);
  assert.equal(result.totals.leavers, 0);
  assert.equal(result.totals.headcount, 55);
  assert.equal(result.totals.demand, 63);
  assert.equal(result.totals.gap, 8); // 3 + 3 + 2, the forecast's own gaps
});

test("an untouched budget funds exactly the gap it was sized for", () => {
  const result = run({ months: 0 });
  assert.equal(result.totals.deferred, 0);
  assert.equal(result.totals.funded, result.totals.gap);
  assert.equal(result.totals.spend, result.totals.cost);
});

// -- each lever moves what it says it moves ---------------------------------
test("more turnover means more leavers and a bigger gap", () => {
  const before = run();
  const after = run({ turnoverDelta: 50 });
  assert.ok(after.totals.leavers > before.totals.leavers);
  assert.ok(after.totals.gap > before.totals.gap);
  assert.ok(after.totals.headcount < before.totals.headcount);
});

test("turnover is applied relatively, not as percentage points", () => {
  // "+10%" on a 17.6% rate is 19.36%, not 27.6%. The label on the slider says
  // so, and this is what holds it to that.
  const after = run({ turnoverDelta: 10 });
  const auditor = after.roles.find((r) => r.role === "Auditor");
  assert.equal(auditor.rateAfter, 19.36);
});

test("attrition scales with the horizon", () => {
  const half = run({ months: 6 }).totals.leavers;
  const full = run({ months: 12 }).totals.leavers;
  assert.ok(full > half, `${full} should exceed ${half}`);
  assert.ok(half > 0, "six months of attrition should not round to nobody");
});

test("a role nobody leaves loses nobody, however long the horizon", () => {
  const result = run({ months: 24, turnoverDelta: 100 });
  const counsel = result.roles.find((r) => r.role === "Legal Counsel");
  assert.equal(counsel.leavers, 0);
  // And its gap is still the forecast's, untouched by a lever that cannot
  // apply to it. A rate of zero times anything is zero.
  assert.equal(counsel.gap, 2);
});

test("more workload means more demand and a bigger gap", () => {
  const after = run({ workloadDelta: 20 });
  assert.ok(after.totals.demand > run().totals.demand);
  assert.ok(after.totals.gap > run().totals.gap);
});

// -- the budget --------------------------------------------------------------
test("a cut budget leaves positions unfunded and says which", () => {
  const result = run({ budgetDelta: -50, months: 0 });
  assert.ok(result.totals.deferred > 0, "a halved budget should not cover everything");
  assert.equal(result.totals.funded + result.totals.deferred, result.totals.gap);

  const named = result.departments.flatMap((d) => d.deferredRoles);
  assert.ok(named.length > 0, "deferred positions with no role named");
});

test("the budget is never overspent", () => {
  for (const budgetDelta of [-90, -75, -50, -25, -10, 0, 25]) {
    const result = run({ budgetDelta, months: 12 });
    assert.ok(
      result.totals.spend <= result.totals.budget,
      `spent ${result.totals.spend} of ${result.totals.budget} at ${budgetDelta}%`
    );
  }
});

test("what the budget reaches first is the most understaffed team", () => {
  // Legal is 2 short out of 4 - half the team - against Engineering's 3 out of
  // 34. Whatever is funded, Legal is funded before Engineering.
  const result = run({ budgetDelta: -80, months: 0 });
  const legal = result.roles.find((r) => r.role === "Legal Counsel");
  const engineering = result.roles.find((r) => r.role === "Civil Engineer");
  assert.ok(
    legal.funded > 0,
    "the most understaffed role went unfunded while money remained"
  );
  assert.ok(legal.funded >= engineering.funded);
});

test("a budget of nothing funds nothing and hides none of it", () => {
  const result = run({ budgetDelta: -100, months: 0 });
  assert.equal(result.totals.budget, 0);
  assert.equal(result.totals.funded, 0);
  assert.equal(result.totals.spend, 0);
  assert.equal(result.totals.deferred, result.totals.gap);
});

// -- the shape of the output -------------------------------------------------
test("a surplus is not reported as a negative gap", () => {
  const overstaffed = [
    { ...team[0], current: 40, demand: 30, turnoverRate: 0 },
  ];
  const result = runScenario(overstaffed, { ...NEUTRAL }, PRICES);
  assert.equal(result.totals.gap, 0);
  assert.equal(result.roles[0].gap, 0);
});

test("departments add up to the roles inside them", () => {
  const result = run({ turnoverDelta: 25, budgetDelta: -40 });
  for (const key of ["current", "leavers", "gap", "funded", "deferred"]) {
    const fromRoles = result.roles.reduce((n, r) => n + r[key], 0);
    const fromDepartments = result.departments.reduce((n, d) => n + d[key], 0);
    assert.equal(fromDepartments, fromRoles, key);
    assert.equal(result.totals[key], fromRoles, `totals.${key}`);
  }
});

test("the projection starts at today and ends at the horizon", () => {
  const result = run({ months: 6, turnoverDelta: 30, workloadDelta: 10 });
  const points = result.projection;

  assert.equal(points.length, 7); // month 0 through 6
  assert.equal(points[0].month, 0);
  assert.equal(points[0].headcount, result.totals.current);
  assert.equal(points[points.length - 1].month, 6);

  // Headcount only falls, demand only rises, and the gap never goes negative.
  for (let i = 1; i < points.length; i += 1) {
    assert.ok(points[i].headcount <= points[i - 1].headcount);
    assert.ok(points[i].demand >= points[i - 1].demand);
    assert.ok(points[i].gap >= 0);
  }
});

test("urgency is relative to the size of the team, not the size of the gap", () => {
  // 2 missing from a team of 4 is an emergency; 2 from 100 is a rounding error.
  assert.equal(urgencyOf(2, 4), "critical");
  assert.equal(urgencyOf(2, 100), "moderate");
  assert.equal(urgencyOf(0, 10), "moderate");
});

// -- pay equity --------------------------------------------------------------
test("the planted below-band role is found", () => {
  const findings = payFindings(PAY, BANDS);
  const found = findings.find((f) => f.id.includes("Maintenance Technician"));
  assert.ok(found, "the role paid under its band was not reported");
  assert.match(found.title, /below the Mid band/);
  assert.equal(found.source, "payroll");
});

test("the planted compression case is found, and reads as a decision", () => {
  const findings = payFindings(PAY, BANDS);
  const found = findings.find((f) =>
    f.id.startsWith("compression:Operations:Operations Manager")
  );
  assert.ok(found, "a senior grade paid like the grade below was not reported");
  assert.equal(found.level, "critical");
  // The point of the finding is what it means, not the arithmetic.
  assert.match(found.detail, /Promotion between the two is worth/);
});

test("the spread check does not just report the biggest teams", () => {
  // The first version measured lowest to highest, which grows with headcount
  // for statistical reasons and nothing to do with pay: it reported the
  // 34-person role and stayed quiet about the 5-person one. The middle half
  // is the same width whatever the headcount.
  const findings = payFindings(PAY, BANDS).filter((f) =>
    f.id.startsWith("spread:")
  );
  const flagged = findings.map((f) => f.id.split(":")[2]);
  const biggest = [...PAY].sort((a, b) => b.employees - a.employees)[0];
  assert.ok(
    !flagged.includes(biggest.role) || spreadOf(biggest) >= 0.3,
    `${biggest.role} was flagged for being large, not for its pay`
  );
  assert.ok(flagged.length <= 4, `${flagged.length} spread findings is a list, not a finding`);
});

test("one role behind its peers is one finding, not one per peer", () => {
  // It produced eight lines about the same role before, which is one fact
  // reported eight times.
  const findings = payFindings(PAY, BANDS).filter((f) =>
    f.id.startsWith("experience:")
  );
  const roles = findings.map((f) => f.id);
  assert.equal(new Set(roles).size, roles.length);
  for (const role of new Set(PAY.map((r) => r.role))) {
    assert.ok(
      findings.filter((f) => f.id.endsWith(`:${role}`)).length <= 1,
      `${role} was reported more than once`
    );
  }
});

test("the planted wide spread is found", () => {
  const findings = payFindings(PAY, BANDS);
  const found = findings.find((f) => f.id.includes("Software Engineer"));
  assert.ok(found, "a role paying wildly different money was not reported");
  assert.match(found.title, /pay runs from/);
});

test("a role whose pay is unremarkable produces no finding", () => {
  // Otherwise the panel is a list of every role, which is the table below it.
  const findings = payFindings(PAY, BANDS);
  const quiet = PAY.find((r) => r.role === "Civil Engineer");
  assert.ok(quiet);
  assert.equal(
    findings.filter((f) => f.id.includes(":Civil Engineer")).length,
    0
  );
});

test("a tiny team is not accused of a wide spread", () => {
  // Three people can straddle a band for ordinary reasons. The check needs
  // enough people to mean something before it is allowed to speak.
  const tiny = [
    { department: "Legal", role: "Legal Counsel", level: "Mid", employees: 2,
      avgExperience: 5, min: 20000, p25: 20000, median: 30000, p75: 40000,
      max: 60000 },
  ];
  assert.equal(payFindings(tiny, BANDS).filter((f) => f.id.startsWith("spread:")).length, 0);
});

test("every pay finding is labelled as resting on pay data", () => {
  // The panel shows these next to forecast and live figures. A reader has to
  // be able to tell which numbers are invented.
  for (const finding of payFindings(PAY, BANDS)) {
    assert.equal(finding.source, "payroll", finding.id);
    assert.ok(finding.title.length > 0 && finding.detail.length > 0, finding.id);
    assert.ok(["critical", "warning", "info"].includes(finding.level), finding.id);
  }
});

test("the averages are weighted by how many people are in each role", () => {
  // A three-person role must not move the company average as far as a
  // thirty-four-person one.
  const summary = paySummary(PAY);
  const people = PAY.reduce((n, r) => n + r.employees, 0);
  const bill = PAY.reduce((n, r) => n + r.median * r.employees, 0);
  assert.equal(summary.people, people);
  assert.equal(summary.averageMedian, Math.round(bill / people));

  const naive =
    PAY.reduce((n, r) => n + r.median, 0) / PAY.length;
  assert.notEqual(Math.round(naive), summary.averageMedian);
});

test("pay rises with grade", () => {
  const grades = byLevel(PAY, ["Junior", "Mid", "Senior", "Expert"]);
  for (let i = 1; i < grades.length; i += 1) {
    assert.ok(
      grades[i].median > grades[i - 1].median,
      `${grades[i].level} (${grades[i].median}) is not above ${grades[i - 1].level} (${grades[i - 1].median})`
    );
  }
});

test("spread is measured against the median, so big salaries do not inflate it", () => {
  const tight = { min: 90000, max: 110000, median: 100000 };
  const loose = { min: 9000, max: 11000, median: 10000 };
  assert.equal(spreadOf(tight), spreadOf(loose));
});

console.log(
  failures ? `\nFAILED (${failures} failure(s))` : "\nALL PASSED (0 failure(s))"
);
process.exit(failures ? 1 : 0);
