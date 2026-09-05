/**
 * Alerts, as the browser sees them.
 *
 * The rules used to live here, in TypeScript, computed on the page. That was
 * fine while an alert only ever existed where somebody was looking at it.
 * Emailing them needs the same findings produced with nobody looking, and two
 * implementations of one set of rules in two languages is a promise that the
 * email and the dashboard will one day disagree about the same job.
 *
 * So the engine is `ats/alerts.py` and this is a typed window onto it. What is
 * left here is the vocabulary the pages need — the shape of a finding, and the
 * two rules for reading one:
 *
 *   `level`  — how loud. Critical is measured against the size of the team, so
 *              two missing from four outranks two missing from a hundred.
 *   `source` — which kind of number it rests on. Never left to the reader to
 *              work out, and a finding that reads more than one carries the
 *              weakest of them.
 */

import { adminFetch, unwrapAdmin } from "./api";

export type AlertLevel = "critical" | "warning" | "info";

/** forecast: the frozen model. live: the ATS now. payroll: pay data. */
export type AlertSource = "forecast" | "live" | "payroll";

export interface Alert {
  id: string;
  level: AlertLevel;
  /** One line. The finding itself, with the number in it. */
  title: string;
  /** Why it is being said, and what it rests on. */
  detail: string;
  source: AlertSource;
  department?: string;
  /** Set when the finding belongs to one vacancy, so its page can show it. */
  job_slug?: string;
  action_label?: string;
  action_href?: string;
}

export interface AlertsResponse {
  alerts: Alert[];
  /** Who a digest would reach. Empty is the state worth knowing about. */
  recipients: string[];
  mail_configured: boolean;
  /** "resend" | "smtp" | "none". Which route the mail actually takes. */
  transport: string;
  /** The address a recipient would see it come from. */
  mail_from: string;
}

export interface SendResult {
  sent: number;
  alerts: number;
  recipients: string[];
  /** One line per recipient: "sent", or why not. */
  results: string[];
  detail?: string;
}

export interface Schedule {
  /** False when no Apps Script holds the trigger, so the hour is fixed. */
  editable: boolean;
  enabled: boolean;
  hour: number | null;
  /** Whose clock the hour is on. An hour without one is not a time. */
  timezone: string;
  detail?: string;
}

export interface Setting {
  name: string;
  purpose: string;
  set: boolean;
  length: number;
  /** Empty for anything secret — only its length is ever reported. */
  value: string;
  issue: string;
}

/** What the deployment actually holds. Never a secret, only its shape. */
export async function fetchSettings(): Promise<Setting[]> {
  return unwrapAdmin<Setting[]>(await adminFetch("/api/mail/settings"));
}

export async function fetchSchedule(): Promise<Schedule> {
  return unwrapAdmin<Schedule>(await adminFetch("/api/schedule"));
}

/** `hour` null switches the daily send off without changing anything else. */
export async function setSchedule(hour: number | null): Promise<Schedule> {
  return unwrapAdmin<Schedule>(
    await adminFetch("/api/schedule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hour }),
    })
  );
}

export async function fetchAlerts(): Promise<AlertsResponse> {
  return unwrapAdmin<AlertsResponse>(await adminFetch("/api/alerts"));
}

/** Send the digest now — the same message the scheduled run sends. */
export async function sendAlerts(): Promise<SendResult> {
  return unwrapAdmin<SendResult>(
    await adminFetch("/api/alerts/send", { method: "POST" })
  );
}
