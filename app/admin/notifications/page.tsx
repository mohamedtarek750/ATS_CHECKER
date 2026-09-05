"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AcudMark } from "@/components/AcudMark";
import { Alerts } from "@/components/Alerts";
import { Note } from "@/components/Shell";
import {
  fetchAlerts,
  sendAlerts,
  type AlertsResponse,
  type SendResult,
} from "@/lib/alerts";

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
  }, [load]);

  async function send(test: boolean) {
    setBusy(true);
    setError("");
    setSent(null);
    try {
      const result = await sendAlerts(test);
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

          {state && !state.mail_configured && (
            <Note tone="bad">
              <strong className="text-ink">No mail provider is configured</strong>
              , so nothing can be sent to anybody. Set{" "}
              <code>RESEND_API_KEY</code> and <code>ATS_MAIL_FROM</code>. Until
              then this page still shows every finding — it just cannot post one.
            </Note>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t pt-4">
            <button
              className="btn-primary"
              disabled={busy || !state}
              onClick={() => send(true)}
            >
              {busy ? "Sending…" : "Send a test now"}
            </button>
            <button
              className="btn-ghost"
              disabled={busy || !state}
              onClick={() => send(false)}
            >
              Send for real
            </button>
            <button className="btn-ghost ml-auto text-sm" onClick={load}>
              Refresh
            </button>
          </div>

          <p className="text-xs leading-relaxed text-muted">
            The test and the real send build the identical message from the
            identical data; the only difference is <code>[test]</code> in front
            of the subject line, so a trial is distinguishable in an inbox. A
            test that sent something different would prove nothing about what
            the system sends.
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
