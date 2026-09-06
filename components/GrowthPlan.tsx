"use client";

import { useState } from "react";
import { Note } from "@/components/Shell";
import { fetchPlan, sendPlan, type Plan, type PlanSent } from "@/lib/api";

/**
 * What would close the gap, for somebody the engine turned down.
 *
 * A percentage on its own tells a candidate they were not good enough and
 * nothing else, which is the least useful thing a hiring system can say to the
 * person it just rejected. Every requirement they missed is already known, and
 * so is exactly what each one is worth - so the panel can say what would change
 * the outcome, in this advert's own words.
 *
 * THE SEND BUTTON IS THE POINT OF THE WHOLE PANEL BEING HERE
 *
 * This is the closest the system comes to telling somebody they did not get a
 * job, and that is why it is a button rather than a scheduled job. A plan that
 * arrives unasked IS a rejection notice however kindly it is worded, and a
 * machine has no business sending one. So it is loaded on request, read by a
 * recruiter, and sent one candidate at a time by a person who has seen it.
 */
export function GrowthPlan({
  id,
  name,
  tier,
}: {
  id: string;
  name: string;
  tier: string;
}) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<PlanSent | null>(null);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setPlan(await fetchPlan(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build the plan.");
    }
    setLoading(false);
  }

  async function send() {
    setSending(true);
    setError("");
    try {
      setSent(await sendPlan(id));
      setConfirming(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The send failed.");
    }
    setSending(false);
  }

  if (!plan) {
    return (
      <div className="mt-4 border-t pt-4">
        <button className="btn-ghost text-sm" onClick={load} disabled={loading}>
          {loading ? "Working it out…" : "What would close the gap?"}
        </button>
        {error && (
          <div className="mt-2">
            <Note tone="bad">{error}</Note>
          </div>
        )}
      </div>
    );
  }

  const must = plan.steps.filter((s) => s.importance === "must_have");
  const nice = plan.steps.filter((s) => s.importance !== "must_have");

  return (
    <div className="mt-4 space-y-3 border-t pt-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="font-medium">What would close the gap</h3>
        {plan.steps.length > 0 && (
          <span className="text-sm text-muted">
            {plan.percent_now}% → <strong className="text-ink">{plan.percent_after}%</strong>{" "}
            if every one of these were met
          </span>
        )}
      </div>

      {plan.steps.length === 0 && !plan.experience_note ? (
        <p className="text-sm text-muted">
          Nothing to suggest — this CV showed everything the advert asked for.
        </p>
      ) : (
        <>
          {/* The arithmetic is the scoring engine's own, so it can be said
              plainly rather than hedged. It is also the honest caveat: closing
              every gap on paper is not the same as getting the job. */}
          {plan.steps.length > 0 && (
            <p className="text-xs leading-relaxed text-muted">
              Worked out by re-running the same scoring, with these requirements
              met.{" "}
              {plan.reaches_bar
                ? "That clears the bar for this advert."
                : "That still would not clear the bar for this advert on its own."}
            </p>
          )}

          <Steps title="Required" steps={must} />
          <Steps title="Preferred" steps={nice} />

          {plan.experience_note && (
            <div className="rounded-lg border px-4 py-3">
              <p className="text-sm font-medium">On experience</p>
              <p className="mt-1 text-sm leading-relaxed text-muted">
                {plan.experience_note}
              </p>
            </div>
          )}

          {/* -- sending it ------------------------------------------------ */}
          <div className="border-t pt-3">
            {sent ? (
              <p className={`text-sm ${sent.sent ? "text-good" : "text-bad"}`}>
                {sent.sent
                  ? `Sent to ${sent.to}.`
                  : `Not sent: ${sent.detail}`}
              </p>
            ) : confirming ? (
              <div className="rounded-lg border border-bad/40 bg-bad-wash px-4 py-3">
                <p className="text-sm font-medium">
                  Email this to {name} at once?
                </p>
                <p className="mt-1 text-sm leading-relaxed text-muted">
                  It says their application did not go through, and then lists
                  what the advert asked for that their CV did not show. It
                  carries no score and no ranking. Nothing sends this on a
                  schedule — this is the only way it goes out.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    className="btn-danger text-sm"
                    onClick={send}
                    disabled={sending}
                  >
                    {sending ? "Sending…" : "Send it"}
                  </button>
                  <button
                    className="btn-ghost text-sm"
                    onClick={() => setConfirming(false)}
                    disabled={sending}
                  >
                    Not yet
                  </button>
                </div>
              </div>
            ) : (
              <button
                className="btn-ghost text-sm"
                onClick={() => setConfirming(true)}
              >
                Send this to {name.split(" ")[0] || "the candidate"}
                {tier === "accepted" ? " anyway" : ""}
              </button>
            )}
            {error && (
              <div className="mt-2">
                <Note tone="bad">{error}</Note>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function Steps({ title, steps }: { title: string; steps: Plan["steps"] }) {
  if (steps.length === 0) return null;
  return (
    <div>
      <p className="mb-1.5 text-xs uppercase tracking-wide text-muted">{title}</p>
      <div className="space-y-2">
        {steps.map((step) => (
          <div key={step.requirement} className="rounded-lg border px-4 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-medium">{step.requirement}</span>
              <span className="text-xs text-muted">
                worth {step.worth} point{step.worth === 1 ? "" : "s"}
              </span>
            </div>
            <p className="mt-1 text-sm leading-relaxed text-muted">
              {step.advice}
            </p>
            {step.resources.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                {step.resources.map((resource) => (
                  <a
                    key={resource.url}
                    href={resource.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium text-brand hover:underline"
                  >
                    {resource.name} →
                  </a>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
