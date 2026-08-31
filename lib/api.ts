// Everything the browser knows about the server, in one place.
//
// Parsed CVs are held in the browser, not on the server: a serverless filesystem
// does not survive between invocations anyway, and keeping applicants' CVs in a
// database nobody asked for is a liability rather than a feature.

export type Importance = "must_have" | "nice_to_have";
export type Status = "met" | "partial" | "unclear" | "not_met";
export type Tier = "shortlist" | "review" | "not_a_match" | "not_a_cv";

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

export async function matchAll(
  job: JobProfile,
  candidates: { filename: string; profile: CandidateProfile }[]
): Promise<MatchResponse> {
  return unwrap<MatchResponse>(
    await fetch("/api/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job, candidates }),
    })
  );
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
