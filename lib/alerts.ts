/**
 * Alerts: where the workforce forecast and the live ATS disagree with each other.
 *
 * Each side is useless alone. The forecast says Information Technology will be
 * two Cybersecurity Specialists short and has said so since it was exported;
 * the ATS knows which vacancies are open and who has cleared the bar on them.
 * Neither notices that the shortfall has no vacancy against it, because neither
 * can see the other. That gap is what this produces.
 *
 * TWO KINDS OF NUMBER, AND THE RULE ABOUT SAYING WHICH
 * ----------------------------------------------------
 * Every alert carries a `source`. "forecast" numbers come from a frozen model
 * exported once and unchanged since; "live" numbers change the moment somebody
 * applies. An alert built on both is marked "forecast" - the weaker claim wins,
 * because a reader who trusts a stale number as though it were current is worse
 * off than one who distrusts a fresh one.
 *
 * NO DATASET IN HERE
 * ------------------
 * The rows are arguments, not imports. The frozen forecast is what the
 * demonstration runs on; the day it is replaced by live HR data, that is a
 * different argument and not a different engine.
 */

import type { RoleForecast, TurnoverRow } from "./workforce";

export type AlertLevel = "critical" | "warning" | "info";

/** What a vacancy looks like to this module. A subset of the admin's Posting. */
export interface PostingLike {
  slug: string;
  title: string;
  status: string;
  applications: number;
  accepted: number;
  unread: number;
}

export interface Alert {
  id: string;
  level: AlertLevel;
  /** One line. The finding itself, with the number in it. */
  title: string;
  /** Why it is being said, and what it is based on. */
  detail: string;
  /** "forecast" = frozen model. "live" = the ATS, current as of this page. */
  source: "forecast" | "live";
  /** The department the finding is about, when it is about one. */
  department?: string;
  /** Set when the alert belongs to one vacancy, so its page can show it. */
  jobSlug?: string;
  action?: { label: string; href: string };
}

const LEVEL_ORDER: Record<AlertLevel, number> = {
  critical: 0,
  warning: 1,
  info: 2,
};

/**
 * Titles as people actually write them, reduced to something comparable.
 *
 * A vacancy is called "Senior Data Analyst (Reporting)" and the forecast row is
 * called "Data Analyst". Neither spelling is wrong, and an alert that fires
 * only on an exact string match would never fire at all.
 */
function normalise(title: string): string {
  return title
    .toLowerCase()
    .replace(/\(.*?\)/g, " ")
    .replace(/[^a-z0-9 ]/g, " ")
    .replace(
      /\b(senior|junior|lead|principal|staff|mid|midlevel|level|i|ii|iii|sr|jr)\b/g,
      " "
    )
    .replace(/\s+/g, " ")
    .trim();
}

/** The forecast row this vacancy is hiring for, or null if none fits. */
export function matchRole(
  title: string,
  roles: RoleForecast[]
): RoleForecast | null {
  const wanted = normalise(title);
  if (!wanted) return null;

  const exact = roles.find((r) => normalise(r.Job_Role) === wanted);
  if (exact) return exact;

  // Containment either way, longest first: "Data Analyst" should lose to
  // "Digital Marketing Analyst" when the vacancy says the latter.
  const near = roles
    .filter((r) => {
      const role = normalise(r.Job_Role);
      return role.includes(wanted) || wanted.includes(role);
    })
    .sort((a, b) => normalise(b.Job_Role).length - normalise(a.Job_Role).length);

  return near[0] ?? null;
}

/** How loudly a shortfall should be said, relative to the size of the team. */
export function levelFor(gap: number, current: number): AlertLevel {
  const share = current > 0 ? gap / current : 1;
  if (share >= 0.2) return "critical";
  if (share >= 0.12) return "warning";
  return "info";
}

/** "1 person", "3 people". The irregular one is the one this module needs most. */
const IRREGULAR: Record<string, string> = { person: "people" };

function plural(n: number, word: string): string {
  if (n === 1) return `${n} ${word}`;
  return `${n} ${IRREGULAR[word] ?? word + "s"}`;
}

/**
 * Every finding worth a recruiter's attention, most serious first.
 *
 * Deliberately silent about anything it has no evidence for: a vacancy whose
 * title matches no forecast row produces nothing rather than a guess, and a
 * role the forecast says is fully staffed produces nothing rather than
 * congratulation. An alerts panel that always has something in it is one people
 * learn to scroll past.
 */
export function buildAlerts(
  postings: PostingLike[],
  roles: RoleForecast[],
  turnover: TurnoverRow[]
): Alert[] {
  const found: Alert[] = [];
  const open = postings.filter((p) => p.status === "open");
  const claimed = new Set<string>();

  for (const posting of open) {
    const role = matchRole(posting.title, roles);
    if (!role) continue;
    claimed.add(role.Job_Role);

    const gap = role.Predicted_Workforce_Gap;
    const short = gap - posting.accepted;

    if (gap > 0 && short > 0) {
      const level = levelFor(short, role.Current_Employees);
      found.push({
        id: `gap:${posting.slug}`,
        level,
        department: role.Department,
        jobSlug: posting.slug,
        title:
          `${role.Department} needs ${plural(gap, role.Job_Role.toLowerCase())}` +
          ` it does not have`,
        detail:
          `The forecast puts demand at ${role.Predicted_Workforce_Demand} ` +
          `against ${role.Current_Employees} in post. ` +
          (posting.accepted > 0
            ? `${posting.accepted} of the ${gap} could be filled from this ` +
              `vacancy's shortlist; ${plural(short, "place")} would still be open.`
            : posting.applications > 0
              ? `Nobody on this vacancy has cleared the bar yet, out of ` +
                `${plural(posting.applications, "applicant")}.`
              : `Nobody has applied to this vacancy yet.`),
        source: "forecast",
        action: { label: "Open the job", href: `/admin/jobs/${posting.slug}` },
      });
    }

    if (gap > 0 && short <= 0) {
      found.push({
        id: `filled:${posting.slug}`,
        level: "info",
        department: role.Department,
        jobSlug: posting.slug,
        title: `${posting.title} has enough people to close its shortfall`,
        detail:
          `${plural(posting.accepted, "candidate")} accepted against a ` +
          `forecast gap of ${gap}. Closing the vacancy would stop new ` +
          `applications arriving for a place that is spoken for.`,
        source: "forecast",
        action: { label: "Open the job", href: `/admin/jobs/${posting.slug}` },
      });
    }

    const leaving = turnover.find(
      (t) => normalise(t.role) === normalise(role.Job_Role)
    );
    if (leaving && leaving.risk === "high") {
      found.push({
        id: `turnover:${posting.slug}`,
        level: "warning",
        department: role.Department,
        jobSlug: posting.slug,
        title: `${role.Job_Role} loses ${leaving.turnover_rate}% of its people a year`,
        detail:
          `${plural(leaving.employees_lost, "person")} left in the last year ` +
          `against ${leaving.current_employees} in post. Hiring to the ` +
          `forecast gap alone leaves the team where it started.`,
        source: "forecast",
        action: { label: "See turnover", href: "/workforce/turnover" },
      });
    }
  }

  // The finding neither system can reach on its own: a shortfall with no
  // vacancy against it. Nobody is looking, and nothing says so.
  //
  // Grouped by department rather than one per role. The forecast is short in
  // most roles most of the time, so a row each turns the panel into a copy of
  // the forecast - twenty-five identical lines, which is the same as none.
  const unopened = new Map<string, RoleForecast[]>();
  for (const role of roles) {
    if (role.Predicted_Workforce_Gap < 2 || claimed.has(role.Job_Role)) continue;
    const list = unopened.get(role.Department) ?? [];
    list.push(role);
    unopened.set(role.Department, list);
  }

  for (const [department, short] of unopened) {
    short.sort((a, b) => b.Predicted_Workforce_Gap - a.Predicted_Workforce_Gap);
    const people = short.reduce((n, r) => n + r.Predicted_Workforce_Gap, 0);
    const worst = short.reduce<AlertLevel>((level, role) => {
      const here = levelFor(role.Predicted_Workforce_Gap, role.Current_Employees);
      return LEVEL_ORDER[here] < LEVEL_ORDER[level] ? here : level;
    }, "info");

    found.push({
      id: `unopened:${department}`,
      level: worst,
      department,
      title:
        short.length === 1
          ? `No vacancy is open for ${short[0].Job_Role}`
          : `${department} has ${plural(short.length, "role")} short with no vacancy open`,
      detail:
        short.length === 1
          ? `${department} is forecast ${plural(people, "person")} short in ` +
            `this role and nothing is advertised, so no applications are ` +
            `arriving for it.`
          : `${short
              .map((r) => `${r.Job_Role} (${r.Predicted_Workforce_Gap} short)`)
              .join(", ")}. ` +
            `${plural(people, "person")} in total, and nothing is advertised ` +
            `— so no applications are arriving for any of them.`,
      source: "forecast",
      action: { label: "Add a job", href: "/admin" },
    });
  }

  // Live, and about the recruiter rather than the forecast.
  for (const posting of open) {
    if (posting.unread < 5) continue;
    found.push({
      id: `unread:${posting.slug}`,
      level: posting.unread >= 20 ? "warning" : "info",
      jobSlug: posting.slug,
      title: `${plural(posting.unread, "application")} on ${posting.title} have not been read`,
      detail:
        `They are stored and will be read on the next sweep. Until then they ` +
        `are not counted in the split above.`,
      source: "live",
      action: { label: "Open the job", href: `/admin/jobs/${posting.slug}` },
    });
  }

  // Severity first. Then anything about a vacancy that is actually open, ahead
  // of anything about one that is not - the recruiter reading this is looking
  // at the jobs on the same page, and those are the ones they can act on now.
  return found.sort(
    (a, b) =>
      LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level] ||
      Number(!a.jobSlug) - Number(!b.jobSlug) ||
      a.title.localeCompare(b.title)
  );
}
