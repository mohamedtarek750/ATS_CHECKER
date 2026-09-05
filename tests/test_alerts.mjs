/**
 * The alerts engine.
 *
 * What is being tested is judgement, not arithmetic. An alerts panel earns its
 * place by being right about when to stay quiet - one that always has something
 * in it is one people learn to scroll past - so most of these check that
 * nothing is said rather than that something is.
 *
 * lib/alerts.ts is TypeScript with no runtime imports (the forecast rows are
 * arguments, not imports), so node loads it directly and strips the types.
 *
 * Run: node tests/test_alerts.mjs
 */

import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const load = (name) =>
  import("file://" + join(here, "..", "lib", name).replace(/\\/g, "/"));

const { buildAlerts, matchRole, levelFor } = await load("alerts.ts");
// The shipped forecast. Pure data with no imports of its own, so it loads here
// exactly as the pages load it.
const { ROLES } = await load("workforce.ts");

// -- fixtures ---------------------------------------------------------------
const role = (over = {}) => ({
  Department: "Information Technology",
  Job_Role: "Data Analyst",
  Current_Employees: 12,
  Predicted_Workforce_Demand: 14,
  Predicted_Workforce_Gap: 2,
  ...over,
});

const job = (over = {}) => ({
  slug: "data-analyst",
  title: "Data Analyst",
  status: "open",
  applications: 0,
  accepted: 0,
  unread: 0,
  ...over,
});

const churn = (over = {}) => ({
  department: "Information Technology",
  role: "Data Analyst",
  turnover_rate: 20.0,
  employees_lost: 2,
  net_change: -2,
  current_employees: 12,
  risk: "high",
  ...over,
});

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

// -- matching ---------------------------------------------------------------
test("a vacancy titled the way people title vacancies still matches", () => {
  const roles = [role(), role({ Job_Role: "Software Engineer" })];
  for (const title of [
    "Data Analyst",
    "Senior Data Analyst",
    "data analyst",
    "Data Analyst (Reporting)",
    "Lead Data Analyst II",
  ]) {
    assert.equal(matchRole(title, roles)?.Job_Role, "Data Analyst", title);
  }
});

test("a longer role wins the overlap it actually belongs to", () => {
  const roles = [
    role({ Job_Role: "Data Analyst" }),
    role({ Job_Role: "Digital Marketing Analyst" }),
  ];
  assert.equal(
    matchRole("Digital Marketing Analyst", roles)?.Job_Role,
    "Digital Marketing Analyst"
  );
});

test("a vacancy the forecast knows nothing about matches nothing", () => {
  // Guessing here would attach real headcount numbers to the wrong role.
  assert.equal(matchRole("Falconry Instructor", [role()]), null);
  assert.equal(matchRole("", [role()]), null);
});

test("how loud the alert is scales with the size of the team", () => {
  assert.equal(levelFor(3, 10), "critical");
  assert.equal(levelFor(3, 20), "warning");
  assert.equal(levelFor(3, 100), "info");
});

// -- staying quiet ----------------------------------------------------------
test("a fully staffed role with a job open says nothing", () => {
  const alerts = buildAlerts(
    [job()],
    [role({ Predicted_Workforce_Demand: 12, Predicted_Workforce_Gap: 0 })],
    []
  );
  assert.deepEqual(alerts, []);
});

test("a closed vacancy is not chased", () => {
  const alerts = buildAlerts([job({ status: "closed" })], [role()], []);
  // The role is short and now unclaimed, so the "nothing is open" finding is
  // the right one - but nothing is said about the closed vacancy itself.
  assert.equal(alerts.length, 1);
  assert.match(alerts[0].title, /No vacancy is open/);
});

test("a shortfall of one is not worth interrupting anybody for", () => {
  const alerts = buildAlerts([], [role({ Predicted_Workforce_Gap: 1 })], []);
  assert.deepEqual(alerts, []);
});

// -- the findings themselves ------------------------------------------------
test("a role that is short with a vacancy open is reported against it", () => {
  const alerts = buildAlerts([job({ applications: 4 })], [role()], []);
  const gap = alerts.find((a) => a.id.startsWith("gap:"));

  assert.ok(gap, "no shortfall alert");
  assert.equal(gap.jobSlug, "data-analyst");
  assert.equal(gap.department, "Information Technology");
  assert.match(gap.title, /needs 2 data analysts/);
  assert.match(gap.detail, /demand at 14 against 12/);
  assert.match(gap.detail, /Nobody on this vacancy has cleared the bar/);
});

test("the shortfall counts who has already been accepted", () => {
  const alerts = buildAlerts([job({ applications: 9, accepted: 1 })], [role()], []);
  const gap = alerts.find((a) => a.id.startsWith("gap:"));
  assert.match(gap.detail, /1 of the 2 could be filled/);
  assert.match(gap.detail, /1 place would still be open/);
});

test("enough accepted turns the alert into a suggestion to close the job", () => {
  const alerts = buildAlerts([job({ applications: 20, accepted: 2 })], [role()], []);
  assert.equal(alerts.filter((a) => a.id.startsWith("gap:")).length, 0);
  const filled = alerts.find((a) => a.id.startsWith("filled:"));
  assert.ok(filled);
  assert.equal(filled.level, "info");
  assert.match(filled.detail, /2 candidates accepted against a forecast gap of 2/);
});

test("a shortfall with no vacancy against it is the loudest thing here", () => {
  // Neither system can see this on its own: the forecast does not know what is
  // advertised, and the ATS does not know what is missing.
  const alerts = buildAlerts([], [role({ Predicted_Workforce_Gap: 3 })], []);
  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].id, "unopened:Information Technology");
  assert.match(alerts[0].title, /No vacancy is open for Data Analyst/);
  // One role reads as a sentence, not as a list of one.
  assert.match(alerts[0].detail, /forecast 3 people short in this role/);
  assert.doesNotMatch(alerts[0].detail, /in total/);
  assert.equal(alerts[0].action.label, "Add a job");
});

test("a department short in several roles is one alert, not one per role", () => {
  // The forecast is short somewhere in most roles most of the time. A row each
  // reproduces the forecast inside the alerts panel, which is the same as
  // having no alerts panel.
  const alerts = buildAlerts(
    [],
    [
      role({ Job_Role: "Compliance Officer", Department: "Legal", Current_Employees: 9 }),
      role({ Job_Role: "Contract Specialist", Department: "Legal", Current_Employees: 5 }),
      role({ Job_Role: "Legal Counsel", Department: "Legal", Current_Employees: 4 }),
    ],
    []
  );

  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].id, "unopened:Legal");
  assert.match(alerts[0].title, /Legal has 3 roles short with no vacancy open/);
  // Every role is still named, and with its own number.
  for (const named of ["Compliance Officer", "Contract Specialist", "Legal Counsel"]) {
    assert.match(alerts[0].detail, new RegExp(`${named} \\(2 short\\)`));
  }
  assert.match(alerts[0].detail, /6 people in total/);
  // Loudest of the three wins: 2 of 4 is critical even though 2 of 9 is not.
  assert.equal(alerts[0].level, "critical");
});

test("findings about an open vacancy come before ones about a missing vacancy", () => {
  // Same severity, and the recruiter is looking at the open jobs on this page.
  const alerts = buildAlerts(
    [job({ applications: 2 })],
    [
      role({ Predicted_Workforce_Gap: 3 }),
      role({ Job_Role: "Legal Counsel", Department: "Legal", Current_Employees: 4,
             Predicted_Workforce_Gap: 3 }),
    ],
    []
  );
  const critical = alerts.filter((a) => a.level === "critical");
  assert.ok(critical.length >= 2, "expected two critical findings");
  assert.ok(critical[0].jobSlug, `${critical[0].id} has no vacancy behind it`);
});

test("opening the vacancy silences the no-vacancy alert", () => {
  const withJob = buildAlerts([job()], [role()], []);
  assert.equal(withJob.filter((a) => a.id.startsWith("unopened:")).length, 0);
});

test("a role that bleeds people says so, separately from the shortfall", () => {
  const alerts = buildAlerts([job()], [role()], [churn()]);
  const leaving = alerts.find((a) => a.id.startsWith("turnover:"));
  assert.ok(leaving);
  assert.match(leaving.title, /loses 20% of its people a year/);
  assert.match(leaving.detail, /leaves the team where it started/);
  // And a role people stay in does not.
  assert.equal(
    buildAlerts([job()], [role()], [churn({ risk: "low" })]).filter((a) =>
      a.id.startsWith("turnover:")
    ).length,
    0
  );
});

test("unread applications are reported only once they are a backlog", () => {
  const quiet = buildAlerts([job({ unread: 4 })], [], []);
  assert.deepEqual(quiet, []);

  const piling = buildAlerts([job({ unread: 30, applications: 30 })], [], []);
  assert.equal(piling.length, 1);
  assert.equal(piling[0].level, "warning");
  assert.equal(piling[0].source, "live");
  assert.match(piling[0].title, /30 applications on Data Analyst/);
});

// -- the rule about which numbers are which ---------------------------------
test("anything resting on the forecast is labelled as resting on it", () => {
  const alerts = buildAlerts(
    [job({ unread: 30, applications: 30 })],
    [role()],
    [churn()]
  );
  for (const alert of alerts) {
    assert.ok(["forecast", "live"].includes(alert.source), alert.id);
  }
  // The shortfall reads the live accepted count too, and is still marked
  // "forecast" - the weaker claim has to win, or a stale number gets read as
  // a current one.
  assert.equal(alerts.find((a) => a.id.startsWith("gap:")).source, "forecast");
  assert.equal(alerts.find((a) => a.id.startsWith("unread:")).source, "live");
});

test("the most serious finding is the one at the top", () => {
  const alerts = buildAlerts(
    [
      job({ unread: 6, applications: 6 }),
      job({ slug: "auditor", title: "Auditor", accepted: 3, applications: 8 }),
    ],
    [
      role({ Predicted_Workforce_Gap: 4, Current_Employees: 12 }), // critical
      role({
        Department: "Finance",
        Job_Role: "Auditor",
        Current_Employees: 17,
        Predicted_Workforce_Demand: 20,
        Predicted_Workforce_Gap: 3,
      }),
    ],
    []
  );
  const levels = alerts.map((a) => a.level);
  const rank = { critical: 0, warning: 1, info: 2 };
  assert.deepEqual(
    levels,
    [...levels].sort((a, b) => rank[a] - rank[b]),
    `out of order: ${levels.join(", ")}`
  );
});

test("every alert can be rendered: it has all the fields the panel reads", () => {
  const alerts = buildAlerts(
    [job({ unread: 30, applications: 30 }), job({ slug: "b", title: "Auditor" })],
    [role(), role({ Job_Role: "Auditor", Department: "Finance" })],
    [churn()]
  );
  assert.ok(alerts.length >= 3);
  const seen = new Set();
  for (const alert of alerts) {
    assert.equal(typeof alert.id, "string");
    assert.ok(alert.id.length > 0);
    assert.ok(!seen.has(alert.id), `duplicate id ${alert.id}`);
    seen.add(alert.id);
    assert.ok(alert.title.length > 0, alert.id);
    assert.ok(alert.detail.length > 0, alert.id);
    assert.ok(["critical", "warning", "info"].includes(alert.level), alert.id);
  }
});

// -- against the real dataset -----------------------------------------------
test("the shipped forecast produces findings a person could act on", () => {
  // The demonstration data, read the way the page reads it. If this ever comes
  // back empty the panel is dead on the deployed site and nothing else says so.
  const alerts = buildAlerts([], ROLES, []);
  assert.ok(alerts.length > 5, `only ${alerts.length} findings`);
  assert.ok(
    alerts.every((a) => a.id.startsWith("unopened:")),
    "with no vacancies open, every finding should be that nothing is open"
  );
  assert.ok(
    alerts.some((a) => a.department === "Information Technology"),
    "IT is short in the shipped data and should appear"
  );
});

console.log(
  failures ? `\nFAILED (${failures} failure(s))` : "\nALL PASSED (0 failure(s))"
);
process.exit(failures ? 1 : 0);
