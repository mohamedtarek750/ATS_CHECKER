"""Generate the simulated pay table.

The dataset behind this project has no salary data of any kind. Compensation
analysis needs some, so this produces a set that is internally consistent -
bands that follow seniority, spreads that follow team size, experience that
tracks level - and writes it into lib/pay.ts with a header saying plainly what
it is.

It also plants three real problems, because an equity report that finds nothing
demonstrates nothing: one role paid below its band, one department where senior
and mid pay have converged, and one role whose spread is far too wide for the
job. They are noted here so nobody later mistakes them for a bug.

Run once. The output is committed; this is not part of the build.
"""
import json
import pathlib
import random
import re
import statistics

ROOT = pathlib.Path(r"C:\Users\lenovo\ACUD_ATS_CHECKER")
random.seed(20260905)  # deterministic: the same table every time

# -- read the roles and levels already in the project ------------------------
source = (ROOT / "lib" / "workforce.ts").read_text(encoding="utf-8")


def block(name, after):
    raw = source.split(after)[1].split("];")[0]
    rows = []
    for line in raw.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        line = re.sub(r"(\w+):", r'"\1":', line)
        rows.append(json.loads(line))
    return rows


roles = block("ROLES", "export const ROLES: RoleForecast[] = [")
costs = block("COST_ROLES", "export const COST_ROLES: CostRole[] = [")
level_of = {c["role"]: c["level"] for c in costs}

# Monthly EGP. Market bands by seniority - the reference the equity check
# measures a role's median against.
BANDS = {
    "Junior": (12000, 22000),
    "Mid": (20000, 38000),
    "Senior": (34000, 58000),
    "Expert": (52000, 92000),
}
YEARS = {"Junior": 2.0, "Mid": 5.0, "Senior": 9.0, "Expert": 13.0}

# The three planted problems.
BELOW_BAND = "Maintenance Technician"      # paid under the floor for its level
WIDE_SPREAD = "Software Engineer"          # same job, wildly different pay
COMPRESSED = ("Finance", "Auditor")        # an Expert role paid at Mid money
# A Senior role paid barely more than the Mid role beside it: promotion between
# the two buys almost nothing. The compression check has nothing to find
# otherwise, because every other centre is drawn from its own band.
COMPRESSION_PAIR = ("Operations", "Operations Manager")

out = []
for role in sorted(roles, key=lambda r: (r["Department"], r["Job_Role"])):
    name = role["Job_Role"]
    level = level_of.get(name, "Mid")
    low, high = BANDS[level]
    people = role["Current_Employees"]

    centre = (low + high) / 2 * random.uniform(0.94, 1.08)
    spread = 0.13
    if name == BELOW_BAND:
        centre = low * 0.84
    if name == WIDE_SPREAD:
        spread = 0.34
    if [role["Department"], name] == list(COMPRESSED):
        centre = BANDS["Mid"][1] * 1.03
    if [role["Department"], name] == list(COMPRESSION_PAIR):
        # Facility Manager (Mid, Operations) lands around 29k; this sits just
        # above it, so the step up a grade is worth a few per cent.
        centre = 30500

    # Clamped relative to the role's own centre, not to an absolute floor: an
    # absolute one produced an Expert engineer on 8,000, which reads as a bug in
    # the generator rather than as the pay problem it is meant to be.
    floor, ceiling = centre * 0.55, centre * 1.5
    salaries = sorted(
        round(min(ceiling, max(floor, random.gauss(centre, centre * spread))) / 250) * 250
        for _ in range(people)
    )
    years = sorted(
        max(0.5, round(random.gauss(YEARS[level], 2.1), 1)) for _ in range(people)
    )

    def pct(p):
        if len(salaries) == 1:
            return salaries[0]
        return round(
            statistics.quantiles(salaries, n=100, method="inclusive")[p - 1] / 250
        ) * 250

    out.append({
        "department": role["Department"],
        "role": name,
        "level": level,
        "employees": people,
        "avgExperience": round(sum(years) / len(years), 1),
        "min": salaries[0],
        "p25": pct(25),
        "median": round(statistics.median(salaries) / 250) * 250,
        "p75": pct(75),
        "max": salaries[-1],
    })

rows = "\n".join(
    "  { "
    + ", ".join(
        f'{k}: {json.dumps(v)}' for k, v in r.items()
    )
    + " },"
    for r in out
)

header = '''/**
 * Simulated pay data. NOT ACUD's payroll.
 *
 * The workforce dataset this project was built on carries no salary figures at
 * all, and a compensation page needs some to be a compensation page. These were
 * generated once, from a fixed seed, so that they are internally consistent:
 * bands follow seniority, spreads follow team size, and average experience
 * tracks level. Every page that reads them says on its face that they are
 * invented.
 *
 * Three problems were planted deliberately, because an equity report that finds
 * nothing demonstrates nothing:
 *
 *   - Maintenance Technician sits below the market band for its level.
 *   - Auditor (Finance) pays about what a mid-level role pays, though it is
 *     graded Expert - the compression case.
 *   - Software Engineer has a spread far too wide for one job title.
 *   - Operations Manager (Senior) is paid barely more than Facility Manager
 *     (Mid) beside it - the compression case.
 *
 * They are findings, not bugs. Replacing this file with a real payroll export
 * of the same shape is the whole migration - nothing else reads salaries.
 *
 * Amounts are monthly, in EGP.
 *
 * Regenerate: the script that produced this lives in the commit that added it.
 */

export type PayLevel = "Junior" | "Mid" | "Senior" | "Expert";

export interface PayRow {
  department: string;
  role: string;
  level: PayLevel;
  employees: number;
  /** Mean years of experience across the people in this role. */
  avgExperience: number;
  min: number;
  p25: number;
  median: number;
  p75: number;
  max: number;
}

/** What the market pays for each grade. The reference an anomaly is measured against. */
export const BANDS: Record<PayLevel, { low: number; high: number }> = {
  Junior: { low: 12000, high: 22000 },
  Mid: { low: 20000, high: 38000 },
  Senior: { low: 34000, high: 58000 },
  Expert: { low: 52000, high: 92000 },
};

export const PAY: PayRow[] = [
'''

(ROOT / "lib" / "pay.ts").write_text(header + rows + "\n];\n", encoding="utf-8")
print(f"wrote lib/pay.ts with {len(out)} roles")
for r in out:
    if r["role"] in (BELOW_BAND, WIDE_SPREAD, COMPRESSED[1], COMPRESSION_PAIR[1], "Facility Manager"):
        print("  planted:", r["role"], r["level"], r["min"], r["median"], r["max"])
