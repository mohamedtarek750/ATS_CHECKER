"""Copy the workforce forecast out of lib/workforce.ts into ats/workforce.py.

The forecast is authored in TypeScript because seven pages read it there. The
alert engine that emails people is Python, and it needs the same rows.

A JSON file both sides load would be the obvious answer and is the wrong one
here: the Python function is bundled for Vercel on its own, and a data file
sitting outside it is a file that works locally and is missing in production.
So the rows are copied into a Python module, and tests/test_alerts.py parses
BOTH files and fails if they have drifted. Generated, checked, and never edited
by hand.

Run after changing ROLES or TURNOVER in lib/workforce.ts:

    python scripts/sync_workforce_data.py
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "lib" / "workforce.ts"
TARGET = ROOT / "ats" / "workforce.py"


def rows(after: str) -> list[dict]:
    """Every object literal in one exported array."""
    raw = SOURCE.read_text(encoding="utf-8").split(after)[1].split("];")[0]
    found = []
    for line in raw.splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        found.append(json.loads(re.sub(r"(\w+):", r'"\1":', line)))
    return found


def main() -> None:
    roles = rows("export const ROLES: RoleForecast[] = [")
    turnover = rows("export const TURNOVER: TurnoverRow[] = [")
    costs = rows("export const COST_ROLES: CostRole[] = [")
    level = {c["role"]: c["level"] for c in costs}

    lines = [
        '"""The workforce forecast, as the alert engine sees it.',
        "",
        "GENERATED. Do not edit by hand - lib/workforce.ts is where these rows are",
        "authored, and scripts/sync_workforce_data.py copies them here. A test",
        "parses both files and fails if they have drifted apart.",
        "",
        "Why a copy rather than one shared JSON file: the Python function is",
        "bundled for deployment on its own, and a data file outside it is a file",
        "that works on a laptop and is missing in production.",
        "",
        "Like everything derived from it, these numbers are a FROZEN FORECAST -",
        "produced once by a Lasso regression trained on quarterly staffing records",
        "for 2020-2026, and unchanged since. Nothing in the running system updates",
        "them and no applicant affects them.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "",
        "",
        "@dataclass(frozen=True)",
        "class Role:",
        '    """One role\'s headcount today and what the model says it needs."""',
        "",
        "    department: str",
        "    role: str",
        "    current: int",
        "    demand: int",
        "    gap: int",
        "    #: Measured annual turnover as a percentage. 0.0 where none was recorded,",
        "    #: which is not the same as a role nobody leaves - it is a role nobody",
        "    #: measured, and inventing a rate for it would put a made-up number into",
        "    #: every total downstream.",
        "    turnover: float = 0.0",
        '    #: high / medium / low, or "" where turnover was never measured.',
        '    turnover_risk: str = ""',
        "    people_lost: int = 0",
        '    level: str = "Mid"',
        "",
        "",
        "ROLES: list[Role] = [",
    ]

    churn = {t["role"]: t for t in turnover}
    for role in roles:
        name = role["Job_Role"]
        seen = churn.get(name)
        lines.append(
            "    Role("
            f"department={json.dumps(role['Department'])}, "
            f"role={json.dumps(name)}, "
            f"current={role['Current_Employees']}, "
            f"demand={role['Predicted_Workforce_Demand']}, "
            f"gap={role['Predicted_Workforce_Gap']}, "
            f"turnover={float(seen['turnover_rate']) if seen else 0.0}, "
            f"turnover_risk={json.dumps(seen['risk'] if seen else '')}, "
            f"people_lost={seen['employees_lost'] if seen else 0}, "
            f"level={json.dumps(level.get(name, 'Mid'))}"
            "),"
        )

    lines += [
        "]",
        "",
        "",
        "def by_role(name: str) -> Role | None:",
        '    """Exact lookup. Fuzzy matching against a job advert lives in alerts.py."""',
        "    return next((r for r in ROLES if r.role == name), None)",
        "",
    ]

    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)} with {len(roles)} roles")


if __name__ == "__main__":
    main()
