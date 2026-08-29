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
}

export interface Ranked {
  filename: string;
  name: string;
  headline: string;
  email: string;
  phone: string;
  years: number;
  percent: number;
  tier: Tier;
  tier_label: string;
  reason: string;
  must_met: number;
  must_total: number;
  nice_met: number;
  nice_total: number;
  requirements: RequirementResult[];
  possibly_ai: boolean;
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
