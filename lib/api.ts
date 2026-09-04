// Everything the browser knows about the server, in one place.
//
// Parsed CVs are held in the browser, not on the server: a serverless filesystem
// does not survive between invocations anyway, and keeping applicants' CVs in a
// database nobody asked for is a liability rather than a feature.

export type Importance = "must_have" | "nice_to_have";
export type Status = "met" | "partial" | "unclear" | "not_met";
export type Tier = "accepted" | "waiting_list" | "rejected" | "not_a_cv";

export interface Requirement {
  text: string;
  kind: string;
  importance: Importance;
}

export interface JobProfile {
  title: string;
  seniority: string;
  summary: string;
  min_years_experience: number;
  requirements: Requirement[];
  created?: string;
  source_text?: string;
}

export interface CandidateProfile {
  full_name: string;
  email: string;
  phone: string;
  location: string;
  headline: string;
  seniority: string;
  total_years_experience: number;
  skills: string[];
  certifications: string[];
  languages: string[];
  is_cv: boolean;
  document_type: string;
  ai_generated_score: number;
  [key: string]: unknown;
}

export interface ParsedCV {
  filename: string;
  key: string;
  profile: CandidateProfile;
  warnings?: string[];
}

export interface RequirementResult {
  requirement: string;
  kind: string;
  importance: Importance;
  status: Status;
  evidence: string;
  strength: "strong" | "valid" | "partial" | "none";
  source: string;
  explanation: string;
}

export interface Role {
  title: string;
  company: string;
  years: number;
  is_internship: boolean;
  relevance: "core" | "adjacent" | "unrelated" | "unclear";
  demonstrates: string[];
  has_outcomes: boolean;
  note: string;
}

export interface ExperienceReview {
  has_experience: boolean;
  total_years: number;
  relevant_years: number;
  shown_in_work: number;
  checkable: number;
  verdict: string;
  roles: Role[];
}

export interface Ranked {
  filename: string;
  name: string;
  headline: string;
  email: string;
  phone: string;
  years: number;
  percent: number;
  required_percent: number;
  preferred_percent: number;
  tier: Tier;
  score: number;
  tier_label: string;
  reason: string;
  experience: ExperienceReview;
  must_met: number;
  must_total: number;
  nice_met: number;
  nice_total: number;
  requirements: RequirementResult[];
  possibly_ai: boolean;
  /** Reported beside the job match, never folded into it: they answer different
   *  questions and adding them would hide which one a candidate failed. */
  template: TemplateReport | null;
}

export interface SectionSpec {
  key: string;
  label: string;
  weight: "required" | "recommended" | "optional" | "low_value";
  why: string;
  should_contain: string[];
}

export interface Blueprint {
  job_title: string;
  seniority: string;
  sections: SectionSpec[];
  priority_skills: string[];
  summary_formula: string;
  summary_should_mention: string[];
  bullet_pattern: string;
  wants_metrics: boolean;
  notes: string[];
  preview: string;
}

export type SectionStatus =
  | "excellent" | "good" | "partial" | "weak" | "missing" | "not_relevant";

export interface SectionFinding {
  key: string;
  label: string;
  weight: string;
  status: SectionStatus;
  detail: string;
}

export interface TemplateReport {
  percent: number;
  band: string;
  sections: SectionFinding[];
  strengths: string[];
  improvements: string[];
  recommendations: { priority: "high" | "medium" | "low"; text: string }[];
  ideal_order: string[];
  candidate_order: string[];
  skill_placement: Record<string, string>;
}

export interface MatchResponse {
  job_title: string;
  must_total: number;
  nice_total: number;
  counts: Record<string, number>;
  results: Ranked[];
}

export interface Health {
  ok: boolean;
  provider: string;
  model: string;
  providers: string[];
  needs_key: boolean;
  /** Reading an advert always needs a model, whatever CVs are read with. */
  can_read_jobs: boolean;
  job_model: string | null;
}

async function unwrap<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  // FastAPI puts the message in `detail`; anything else is shown as-is so a
  // deployment problem is legible rather than a bare status code.
  let message = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") message = body.detail;
  } catch {
    /* keep the status line */
  }
  throw new Error(message);
}

export async function health(): Promise<Health> {
  return unwrap<Health>(await fetch("/api/health"));
}

export async function parseCV(file: File, provider?: string): Promise<ParsedCV> {
  const body = new FormData();
  body.append("file", file);
  const query = provider ? `?provider=${encodeURIComponent(provider)}` : "";
  return unwrap<ParsedCV>(await fetch(`/api/cv${query}`, { method: "POST", body }));
}

// The server picks the model for this one: turning an advert into must-have and
// nice-to-have needs comprehension, so it uses a key whenever one exists,
// independently of what CVs are being read with.
export async function parseJob(text: string): Promise<JobProfile> {
  return unwrap<JobProfile>(
    await fetch("/api/job", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    })
  );
}

export async function jobFromCV(
  profile: CandidateProfile,
  strict = false
): Promise<JobProfile> {
  return unwrap<JobProfile>(
    await fetch("/api/job-from-cv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile, strict }),
    })
  );
}

// How many candidates go in one /api/match request.
//
// Not a tuning knob - a platform limit. A serverless function may return at most
// 4.5 MB, and a ranked candidate with its template report is around 7 KB of
// JSON, so one request carrying a thousand CVs comes back at roughly 7.4 MB and
// is rejected outright. Measured with audit/load_test.py. The batch also keeps
// each request well inside the function's execution timeout.
export const MATCH_BATCH = 150;

const TIER_ORDER: Record<Tier, number> = {
  accepted: 0,
  waiting_list: 1,
  rejected: 2,
  not_a_cv: 3,
};

/** Exactly the server's ordering, so a merged pool reads as one ranking. */
function byRank(a: Ranked, b: Ranked): number {
  const tier = TIER_ORDER[a.tier] - TIER_ORDER[b.tier];
  if (tier !== 0) return tier;
  if (a.score !== b.score) return b.score - a.score;
  return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
}

export async function matchAll(
  job: JobProfile,
  candidates: { filename: string; profile: CandidateProfile }[],
  onProgress?: (done: number, total: number) => void
): Promise<MatchResponse> {
  const batches: (typeof candidates)[] = [];
  for (let i = 0; i < candidates.length; i += MATCH_BATCH) {
    batches.push(candidates.slice(i, i + MATCH_BATCH));
  }

  const results: Ranked[] = [];
  const counts: Record<string, number> = {};
  let head: MatchResponse | null = null;
  let done = 0;

  for (const batch of batches) {
    const response = await unwrap<MatchResponse>(
      await fetch("/api/match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job, candidates: batch }),
      })
    );
    head ??= response;
    results.push(...response.results);
    // Tiers are decided per candidate, never relative to the pool, so the
    // batches' counts add up to the whole pool's counts.
    for (const [key, value] of Object.entries(response.counts)) {
      counts[key] = (counts[key] ?? 0) + value;
    }
    done += batch.length;
    onProgress?.(done, candidates.length);
  }

  if (!head) {
    return { job_title: job.title, must_total: 0, nice_total: 0, counts: {}, results: [] };
  }
  return { ...head, counts, results: results.sort(byRank) };
}

export async function fetchBlueprint(job: JobProfile): Promise<Blueprint> {
  return unwrap<Blueprint>(
    await fetch("/api/blueprint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    })
  );
}

export const SECTION_TONE: Record<SectionStatus, string> = {
  excellent: "bg-good-wash text-good",
  good: "bg-good-wash text-good",
  partial: "bg-warn-wash text-warn",
  weak: "bg-warn-wash text-warn",
  missing: "bg-bad-wash text-bad",
  not_relevant: "raised text-muted",
};

export const SECTION_WORD: Record<SectionStatus, string> = {
  excellent: "Excellent",
  good: "Good",
  partial: "Partial",
  weak: "Weak",
  missing: "Missing",
  not_relevant: "Not relevant",
};

// Must stay identical to the PLACEMENT_ constants in ats/stages/template_match.py.
export const PLACEMENT_DEMONSTRATED = "Demonstrated in experience or projects";
export const PLACEMENT_LISTED = "Present in Skills, limited supporting evidence";
export const PLACEMENT_MISSING = "Not mentioned anywhere in the CV";

// How relevant a single role is to the vacancy.
export const RELEVANCE_TONE: Record<string, string> = {
  core: "bg-good-wash text-good",
  adjacent: "bg-warn-wash text-warn",
  unclear: "raised text-muted",
  unrelated: "raised text-muted",
};

export const RELEVANCE_WORD: Record<string, string> = {
  core: "Directly relevant",
  adjacent: "Partly relevant",
  unclear: "Not described",
  unrelated: "Unrelated",
};

export const PRIORITY_TONE: Record<string, string> = {
  high: "bg-bad-wash text-bad",
  medium: "bg-warn-wash text-warn",
  low: "raised text-muted",
};

export const STATUS_MARK: Record<Status, string> = {
  met: "✓",
  partial: "~",
  unclear: "?",
  not_met: "✗",
};

export const STATUS_WORD: Record<Status, string> = {
  met: "Met",
  partial: "Close",
  unclear: "Needs a look",
  not_met: "Not found",
};

// --------------------------------------------------------------------------
// Postings and applications
//
// Everything above is stateless: the browser holds the CVs. These endpoints
// persist, because a public application link means the person who applies and
// the person who reads are not in the same session, or the same week.
// --------------------------------------------------------------------------
export interface Posting {
  slug: string;
  title: string;
  summary: string;
  status: "open" | "closed";
  created: string;
  must_total: number;
  nice_total: number;
  applications: number;
  unread: number;
  accepted: number;
  waiting_list: number;
  rejected: number;
}

export interface PublicPosting {
  slug: string;
  title: string;
  summary: string;
  is_open: boolean;
}

export type ApplicationStatus = "pending" | "read" | "failed" | "not_a_cv";
export type DecisionValue =
  | "new" | "shortlisted" | "interviewing" | "offered" | "hired" | "rejected";

export interface ApplicationRow {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  applied_at: string;
  cv_filename: string;
  cv_url: string;
  status: ApplicationStatus;
  detail: string;
  read_at: string;
  percent: number;
  required_percent: number;
  preferred_percent: number;
  tier: string;
  tier_label: string;
  reason: string;
  engine_version: string;
  decision: DecisionValue;
  decision_label: string;
  decided_by: string;
  decided_at: string;
  /** What the CV tried on the reader. Shown to a person, never acted on. */
  security_flags: string[];
  note: string;
  /** Scored under an older engine, so the number may not be reproducible. */
  stale: boolean;
}

export interface ApplicationsResponse {
  posting: Posting;
  counts: Record<string, number>;
  results: ApplicationRow[];
}

export const DECISIONS: DecisionValue[] = [
  "new", "shortlisted", "interviewing", "offered", "hired", "rejected",
];

export const DECISION_TONE: Record<string, string> = {
  new: "raised text-muted",
  shortlisted: "bg-good-wash text-good",
  interviewing: "bg-good-wash text-good",
  offered: "bg-good-wash text-good",
  hired: "bg-good-wash text-good",
  rejected: "raised text-muted",
};

// --------------------------------------------------------------------------
// Signing in
//
// The browser gets an ID token from Google and hands it to the API, which
// verifies it against Google's keys and checks the address against an
// allow-list. Nothing is shared between this app and the Python function except
// a token Google signed, so there is no session store to keep warm.
//
// Held in sessionStorage rather than localStorage: it expires within the hour
// anyway, and this way closing the tab ends the session on a shared machine,
// which is what a recruiter looking at other people's CVs should get.
// --------------------------------------------------------------------------
const TOKEN_KEY = "ats.admin.token";

export function adminToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.sessionStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAdminToken(token: string): void {
  try {
    if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
    else window.sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode, or storage disabled: the session lasts this page load */
  }
}

/** Raised when the API says the token is missing or expired. */
export class SignedOutError extends Error {}

/** A fetch that carries the signed-in identity. Admin routes only. */
async function adminFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const token = adminToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(url, { ...init, headers });
}

async function unwrapAdmin<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    // The token has expired or was never any good. Drop it so the page shows
    // the sign-in button instead of failing every call from now on.
    setAdminToken("");
    let message = "Sign in to open the dashboard.";
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") message = body.detail;
    } catch {
      /* keep the default */
    }
    throw new SignedOutError(message);
  }
  return unwrap<T>(response);
}

export interface AuthStatus {
  required: boolean;
  configured: boolean;
  client_id: string;
  admins: number;
  password: boolean;
  google: boolean;
  weak_password: boolean;
}

export interface AdminUser {
  email: string;
  name: string;
  picture: string;
}

export async function authStatus(): Promise<AuthStatus> {
  return unwrap<AuthStatus>(await fetch("/api/auth/status"));
}

/** Email and password in, a token to carry out. */
export async function signIn(email: string, password: string): Promise<string> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const { token } = await unwrap<{ token: string; email: string }>(response);
  setAdminToken(token);
  return token;
}

export async function whoAmI(): Promise<AdminUser> {
  return unwrapAdmin<AdminUser>(await adminFetch("/api/auth/me"));
}

/**
 * The CV itself, fetched rather than linked.
 *
 * A plain <a href> cannot carry an Authorization header, so linking straight at
 * the endpoint would mean leaving it open - and it serves a stranger's CV. This
 * pulls the bytes with the token and hands back a blob URL, the same mechanism
 * the one-off screening page already uses for local files.
 */
export async function cvObjectUrl(applicationId: string): Promise<string> {
  const response = await adminFetch(`/api/cv-file/${applicationId}`);
  if (!response.ok) {
    if (response.status === 401) {
      setAdminToken("");
      throw new SignedOutError("Sign in to open the dashboard.");
    }
    throw new Error("The stored CV could not be opened.");
  }
  return URL.createObjectURL(await response.blob());
}

export async function listPostings(): Promise<Posting[]> {
  return unwrapAdmin<Posting[]>(await adminFetch("/api/postings"));
}

export async function createPosting(job: JobProfile): Promise<Posting> {
  return unwrapAdmin<Posting>(
    await adminFetch("/api/postings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job }),
    })
  );
}

export async function setPostingStatus(
  slug: string,
  status: "open" | "closed"
): Promise<Posting> {
  return unwrapAdmin<Posting>(
    await adminFetch(`/api/postings/${slug}/status?status=${status}`, {
      method: "POST",
    })
  );
}

export async function publicPosting(slug: string): Promise<PublicPosting> {
  return unwrap<PublicPosting>(await fetch(`/api/public/postings/${slug}`));
}

/**
 * Ask the server to read an application that has just been submitted.
 *
 * Deliberately not awaited by the applicant: their CV is already stored and
 * their receipt is already earned, so a slow or failed read must not turn into
 * an error on their screen. If it does fail, the scheduled sweep picks it up.
 */
export function requestRead(applicationId: string): void {
  void fetch(`/api/public/applications/${applicationId}/read`, {
    method: "POST",
  }).catch(() => {
    /* the daily sweep is the backstop */
  });
}

export async function submitApplication(
  slug: string,
  fields: { full_name: string; email: string; phone: string },
  file: File
): Promise<{ id: string; full_name: string; status: string }> {
  const body = new FormData();
  body.append("full_name", fields.full_name);
  body.append("email", fields.email);
  body.append("phone", fields.phone);
  body.append("file", file);
  return unwrap(
    await fetch(`/api/public/postings/${slug}/apply`, { method: "POST", body })
  );
}

export interface RequirementDemand {
  requirement: string;
  kind: string;
  importance: Importance;
  met: number;
  partial: number;
  total: number;
  percent: number;
}

export interface VacancyStats {
  total: number;
  read: number;
  pending: number;
  unreadable: number;
  by_tier: Record<string, number>;
  by_decision: Record<string, number>;
  average_percent: number;
  median_percent: number;
  /** [day, count], oldest first, only days that had applications. */
  per_day: [string, number][];
  /** Fewest-met first. The top of this list is what to question in the advert. */
  hardest: RequirementDemand[];
  sampled: number;
  sample_capped: boolean;
}

export interface MailStatus {
  configured: boolean;
  from: string;
  hr_recipients: number;
}

export async function vacancyStats(slug: string): Promise<VacancyStats> {
  return unwrapAdmin<VacancyStats>(
    await adminFetch(`/api/postings/${slug}/stats`)
  );
}

export async function mailStatus(): Promise<MailStatus> {
  return unwrapAdmin<MailStatus>(await adminFetch("/api/mail/status"));
}

export async function listApplications(slug: string): Promise<ApplicationsResponse> {
  return unwrapAdmin<ApplicationsResponse>(
    await adminFetch(`/api/postings/${slug}/applications`)
  );
}

export async function readPending(slug: string): Promise<ApplicationsResponse> {
  return unwrapAdmin<ApplicationsResponse>(
    await adminFetch(`/api/postings/${slug}/read`, { method: "POST" })
  );
}

export async function applicationDetail(id: string): Promise<Ranked> {
  return unwrapAdmin<Ranked>(await adminFetch(`/api/applications/${id}`));
}

export async function saveDecision(
  id: string,
  body: { decision?: DecisionValue; note?: string }
): Promise<ApplicationRow> {
  return unwrapAdmin<ApplicationRow>(
    await adminFetch(`/api/applications/${id}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}
