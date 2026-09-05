"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AcudMark } from "@/components/AcudMark";
import { Alerts } from "@/components/Alerts";
import { Note } from "@/components/Shell";
import {
  fetchAlerts,
  fetchSchedule,
  fetchSettings,
  sendAlerts,
  setSchedule,
  type AlertsResponse,
  type Schedule,
  type SendResult,
  type Setting,
} from "@/lib/alerts";

/** Each route, named for what it actually is rather than for its setting. */
const ROUTE: Record<string, string> = {
  resend: "Resend",
  smtp: "your own mailbox, over SMTP",
  script: "the Google Sheet's own Apps Script",
};

/** Midnight to 11pm, written the way somebody says a time out loud. */
const HOURS = Array.from({ length: 24 }, (_, hour) => ({
  hour,
  label:
    hour === 0
      ? "12 midnight"
      : hour === 12
        ? "12 noon"
        : hour < 12
          ? `${hour} in the morning`
          : `${hour - 12} in the ${hour < 18 ? "afternoon" : "evening"}`,
}));

/**
 * The notification centre, and the console for proving it works.
 *
 * Two things a person needs from an alerting system, and neither is the alerts
 * themselves. First: is anybody actually being told? A digest that silently
 * goes nowhere looks exactly like one that arrives, and the only person who
 * finds out is whoever needed to know. Second: can I make it fire on demand?
 * An alert you cannot test is one you find out about the first time it matters.
 *
 * So the addresses are on the page, the Send button uses the same code path and
 * the same message as the scheduled digest, and what the provider said comes
 * back verbatim rather than as a tick.
 */
export default function NotificationsPage() {
  const [state, setState] = useState<AlertsResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<SendResult | null>(null);
  const [sentAt, setSentAt] = useState("");
  const [plan, setPlan] = useState<Schedule | null>(null);
  const [settings, setSettings] = useState<Setting[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [planError, setPlanError] = useState("");

  const load = useCallback(async () => {
    try {
      setState(await fetchAlerts());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the alerts.");
    }
  }, []);

  useEffect(() => {
    load();
    fetchSchedule()
      .then(setPlan)
      .catch(() => setPlan(null));
    fetchSettings()
      .then(setSettings)
      .catch(() => setSettings(null));
  }, [load]);

  async function choose(hour: number | null) {
    setSaving(true);
    setPlanError("");
    try {
      setPlan(await setSchedule(hour));
    } catch (e) {
      setPlanError(e instanceof Error ? e.message : "Could not save that.");
    }
    setSaving(false);
  }

  async function send() {
    setBusy(true);
    setError("");
    setSent(null);
    try {
      const result = await sendAlerts();
      setSent(result);
      setSentAt(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "The send failed.");
    }
    setBusy(false);
  }

  const alerts = state?.alerts ?? [];
  const counts = {
    critical: alerts.filter((a) => a.level === "critical").length,
    warning: alerts.filter((a) => a.level === "warning").length,
    info: alerts.filter((a) => a.level === "info").length,
  };

  return (
    <div className="min-h-dvh">
      <header className="page-header">
        <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-6 py-3.5">
          <AcudMark subtitle="Notifications" />
          <div className="flex shrink-0 gap-2">
            <Link href="/workforce" className="btn-ghost text-sm">
              Planning
            </Link>
            <Link href="/admin" className="btn-ghost text-sm">
              Jobs
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-4xl space-y-6 px-6 py-8">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Alerts, and who hears about them
          </h1>
          <p className="mt-1 max-w-[70ch] text-sm text-muted">
            The same findings that appear on the dashboard, and the digest that
            carries them by email. One message a day, and none at all on a day
            when nothing is wrong.
          </p>
        </div>

        {error && <Note tone="bad">{error}</Note>}

        {/* -- who is being told ------------------------------------------- */}
        <div className="card space-y-4 px-5 py-5">
          <div>
            <h2 className="font-medium">How it goes out</h2>
            {state && state.transport !== "none" ? (
              <p className="mt-2 text-sm text-muted">
                Through{" "}
                <strong className="text-ink">{ROUTE[state.transport] ?? state.transport}</strong>
                , appearing as{" "}
                <strong className="text-ink">{state.mail_from}</strong>.
              </p>
            ) : (
              <p className="mt-2 text-sm text-bad">
                No route is configured, so nothing can reach anybody. Either{" "}
                <code>RESEND_API_KEY</code> with <code>ATS_MAIL_FROM</code>, or{" "}
                <code>ATS_SMTP_HOST</code>, <code>ATS_SMTP_USER</code> and{" "}
                <code>ATS_SMTP_PASSWORD</code> to send from an ordinary mailbox.
              </p>
            )}
          </div>

          <div className="border-t pt-4">
            <h2 className="font-medium">Recipients</h2>
            {state && state.recipients.length > 0 ? (
              <ul className="mt-2 flex flex-wrap gap-2">
                {state.recipients.map((address) => (
                  <li key={address} className="chip raised text-muted">
                    {address}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-bad">
                Nobody. Set <code>ATS_ALERT_EMAILS</code> in the
                deployment&rsquo;s environment — comma-separated — and every
                address in it receives the digest.
              </p>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 border-t pt-4">
            <button
              className="btn-primary"
              disabled={busy || !state || alerts.length === 0}
              onClick={send}
            >
              {busy ? "Sending…" : "Send now"}
            </button>
            <button className="btn-ghost ml-auto text-sm" onClick={load}>
              Refresh
            </button>
          </div>

          <p className="text-xs leading-relaxed text-muted">
            {alerts.length === 0
              ? "Nothing is open, so there is nothing to send. The scheduled run does the same: no findings, no email."
              : `Sends the ${alerts.length} finding${
                  alerts.length === 1 ? "" : "s"
                } below to everybody listed above, now — the same message the scheduled run sends.`}
          </p>

          {/* What the provider actually said, not a tick. */}
          {sent && (
            <div className="rounded-lg border px-4 py-3">
              {sent.detail ? (
                <p className="text-sm">{sent.detail}</p>
              ) : (
                <>
                  <p className="text-sm">
                    <strong>
                      {sent.sent} of {sent.results.length}
                    </strong>{" "}
                    delivered at {sentAt}, carrying {sent.alerts} finding
                    {sent.alerts === 1 ? "" : "s"}.
                  </p>
                  <ul className="mt-2 space-y-1">
                    {sent.recipients.map((address, index) => (
                      <li key={address} className="text-sm">
                        <span className="text-muted">{address}</span>{" "}
                        <span
                          className={
                            sent.results[index] === "sent"
                              ? "text-good"
                              : "text-bad"
                          }
                        >
                          {sent.results[index] ?? "no result"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </div>

        {/* -- when it goes out --------------------------------------------- */}
        <div className="card space-y-3 px-5 py-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-medium">When it goes out</h2>
            {plan?.timezone && (
              <span className="text-xs text-muted">
                on the sheet&rsquo;s clock &middot; {plan.timezone}
              </span>
            )}
          </div>

          {plan && !plan.editable ? (
            <p className="text-sm leading-relaxed text-muted">
              {plan.detail ||
                "The hour cannot be changed from here on this deployment."}
            </p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <select
                  className="field w-56"
                  value={plan?.enabled && plan.hour !== null ? plan.hour : ""}
                  disabled={saving || !plan}
                  onChange={(e) =>
                    choose(e.target.value === "" ? null : Number(e.target.value))
                  }
                >
                  <option value="">Do not send on a schedule</option>
                  {HOURS.map(({ hour, label }) => (
                    <option key={hour} value={hour}>
                      Every day at {label}
                    </option>
                  ))}
                </select>
                {saving && <span className="text-sm text-muted">Saving…</span>}
              </div>

              <p className="text-sm leading-relaxed text-muted">
                {plan?.enabled && plan.hour !== null ? (
                  <>
                    The digest goes out once a day at{" "}
                    <strong className="text-ink">
                      {HOURS[plan.hour].label}
                    </strong>
                    , and not at all on a day when nothing is open. Applications
                    are still read every morning either way.
                  </>
                ) : (
                  <>
                    Nothing is scheduled here, so the digest goes out on the
                    deployment&rsquo;s own daily run instead. Pick an hour to
                    move it.
                  </>
                )}
              </p>

              {planError && <p className="text-sm text-bad">{planError}</p>}

              <p className="text-xs leading-relaxed text-muted">
                The trigger lives in the Google Sheet&rsquo;s Apps Script,
                because that is the only part of this that can be moved without
                a redeploy — the platform&rsquo;s own cron time is fixed when
                the project is deployed. Google fires it within the chosen hour
                rather than on the minute.
              </p>
            </>
          )}
        </div>

        {/* -- what is actually set ----------------------------------------- */}
        {settings && <SettingsPanel settings={settings} />}

        {/* -- how to make one fire ---------------------------------------- */}
        <details className="card px-5 py-4">
          <summary className="cursor-pointer text-sm font-medium">
            How to make an alert fire, to check one arrives
          </summary>
          <div className="mt-3 space-y-2 text-sm leading-relaxed text-muted">
            <p>
              Every finding is computed from two things: the vacancies in this
              system, which you control, and the frozen workforce forecast,
              which you do not. So the way to move one is to change a vacancy.
            </p>
            <ol className="ml-4 list-decimal space-y-1.5">
              <li>
                <strong className="text-ink">Silence one.</strong> Open a job
                named after a forecast role — Data Analyst, Auditor, Software
                Engineer — and close it. Its shortfall alert disappears and is
                replaced by the department&rsquo;s &ldquo;no vacancy is
                open&rdquo; finding.
              </li>
              <li>
                <strong className="text-ink">Create one.</strong> Add a job
                titled after a role the forecast is short in. A shortfall alert
                appears against it, at a severity set by how short that team is.
              </li>
              <li>
                <strong className="text-ink">Make a backlog.</strong> Send five
                or more applications to one vacancy without reading them. An
                unread-backlog alert appears, marked Live rather than Forecast.
              </li>
              <li>
                <strong className="text-ink">Close a shortfall.</strong> Accept
                as many candidates as the forecast gap. The alert turns into a
                note suggesting the job be closed.
              </li>
            </ol>
            <p>
              Then press <strong className="text-ink">Refresh</strong> above to
              see the feed change, and <strong className="text-ink">Send a
              test now</strong> to put the changed feed in both inboxes.
            </p>
          </div>
        </details>

        {/* -- the feed ----------------------------------------------------- */}
        {state && (
          <div className="flex flex-wrap gap-2">
            <span className="chip bg-bad-wash text-bad">
              {counts.critical} critical
            </span>
            <span className="chip bg-warn-wash text-warn">
              {counts.warning} warning
            </span>
            <span className="chip raised text-muted">{counts.info} note</span>
          </div>
        )}

        {state && alerts.length === 0 ? (
          <div className="empty">
            <p className="text-[15px] font-semibold">Nothing is wrong</p>
            <p className="mx-auto mt-1.5 max-w-[46ch] text-sm text-muted">
              No finding is open, so no digest would go out today. This page
              having nothing on it is the system working, not the system broken.
            </p>
          </div>
        ) : (
          <Alerts alerts={alerts} title="Everything open" limit={100} />
        )}

        {!state && !error && (
          <p className="text-sm text-muted">Loading…</p>
        )}
      </main>
    </div>
  );
}

/**
 * What this deployment actually holds.
 *
 * Every failure in this area looks the same from outside - nothing arrives -
 * and the values behind it live in a hosting panel where a corrected one does
 * NOT reach the running deployment until it is redeployed. So a setting can be
 * right in the panel and wrong in the code that reads it, with no way to tell
 * by looking.
 *
 * No secret is ever shown, and none needs to be. A length answers the question
 * that actually comes up: whether a 16-character App Password arrived as 18
 * characters with quotation marks around it.
 */
function SettingsPanel({ settings }: { settings: Setting[] }) {
  const problems = settings.filter((s) => s.issue);
  const [open, setOpen] = useState(problems.length > 0);

  return (
    <div className="card px-5 py-4">
      <button
        className="flex w-full items-center justify-between gap-3 text-left"
        onClick={() => setOpen(!open)}
      >
        <span className="text-sm font-medium">
          What this deployment is actually reading
        </span>
        <span className="flex items-center gap-2">
          {problems.length > 0 && (
            <span className="chip bg-bad-wash text-bad">
              {problems.length} to fix
            </span>
          )}
          <span className={`text-muted transition ${open ? "rotate-90" : ""}`}>
            &rsaquo;
          </span>
        </span>
      </button>

      {open && (
        <div className="mt-4 space-y-2 border-t pt-4">
          {settings.map((setting) => (
            <div key={setting.name} className="text-sm">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <code className={setting.set ? "" : "text-muted"}>
                  {setting.name}
                </code>
                {setting.set ? (
                  <span className="min-w-0 break-all text-muted">
                    {setting.value ||
                      `${setting.length} characters, not shown`}
                  </span>
                ) : (
                  <span className="text-muted">not set — {setting.purpose}</span>
                )}
              </div>
              {setting.issue && (
                <p className="mt-0.5 text-sm text-bad">{setting.issue}</p>
              )}
            </div>
          ))}

          <p className="border-t pt-3 text-xs leading-relaxed text-muted">
            Passwords and keys are never shown — only how long they are, which
            is enough to spot quotation marks that came along with the value.
            If a setting here is not what you put in the hosting panel, the
            deployment has not picked it up yet: changing a variable on Vercel
            takes effect on the next deploy, not immediately.
          </p>
        </div>
      )}
    </div>
  );
}
