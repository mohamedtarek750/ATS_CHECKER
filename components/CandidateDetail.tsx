"use client";

import { useEffect, useState } from "react";
import { ExperienceBlock, RequirementList } from "./Results";
import { Note } from "./Shell";
import { TemplateBlock } from "./TemplatePanel";
import { applicationDetail, type Ranked } from "@/lib/api";

/**
 * Every requirement with its evidence, for one stored application.
 *
 * Fetched rather than stored. The reasoning behind a decision is about seven
 * kilobytes of prose per candidate; recomputing it from the saved profile takes
 * milliseconds, and keeping it would put megabytes of text into the recruiter's
 * own spreadsheet and make it unopenable. The decision itself IS stored - the
 * percentage, the tier and the reason - because that is what somebody acted on.
 */
export function CandidateDetail({ id }: { id: string }) {
  const [entry, setEntry] = useState<Ranked | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    applicationDetail(id)
      .then((r) => live && setEntry(r))
      .catch(
        (e) =>
          live &&
          setError(e instanceof Error ? e.message : "Could not load the detail.")
      );
    return () => {
      live = false;
    };
  }, [id]);

  if (error) return <Note tone="warn">{error}</Note>;
  if (!entry) return <p className="text-xs text-muted">Loading the evidence…</p>;

  return (
    <div className="border-t pt-3">
      <div className="mb-3 flex flex-wrap gap-4 text-sm">
        <span>
          <span className="text-muted">Required requirements match </span>
          <span className="font-medium tabular-nums">
            {entry.required_percent}%
          </span>
        </span>
        <span>
          <span className="text-muted">Preferred requirements match </span>
          <span className="font-medium tabular-nums">
            {entry.preferred_percent}%
          </span>
        </span>
      </div>

      <ExperienceBlock review={entry.experience} />

      <RequirementList
        label="Required"
        results={entry.requirements.filter((r) => r.importance === "must_have")}
      />
      <RequirementList
        label="Preferred"
        results={entry.requirements.filter((r) => r.importance !== "must_have")}
      />

      {entry.template && <TemplateBlock report={entry.template} />}
    </div>
  );
}
