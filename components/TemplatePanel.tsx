"use client";

import {
  PLACEMENT_DEMONSTRATED,
  PLACEMENT_LISTED,
  PRIORITY_TONE,
  SECTION_TONE,
  SECTION_WORD,
  type Blueprint,
  type TemplateReport,
} from "@/lib/api";

const SECTION_LABEL: Record<string, string> = {
  contact: "Contact",
  summary: "Summary",
  skills: "Core skills",
  experience: "Experience",
  projects: "Projects",
  education: "Education",
  certifications: "Certifications",
  languages: "Languages",
};

const WEIGHT_TONE: Record<string, string> = {
  required: "bg-accent text-accent-ink",
  recommended: "raised text-muted border border-line",
  optional: "text-muted",
  low_value: "text-muted",
};

/** The target layout for a vacancy. A blueprint, never a specimen candidate. */
export function BlueprintCard({ blueprint }: { blueprint: Blueprint }) {
  return (
    <div className="card overflow-hidden">
      <div className="border-b px-5 py-4">
        <h3 className="font-semibold">Ideal CV for {blueprint.job_title}</h3>
        <p className="mt-0.5 text-sm text-muted">
          Derived from this vacancy, not a generic template. Share it with
          candidates, or use it to read theirs.
        </p>
      </div>

      <ol className="divide-y">
        {blueprint.sections.map((section, index) => (
          <li key={section.key} className="px-5 py-3">
            <div className="flex items-center gap-3">
              <span className="w-5 shrink-0 text-right text-xs tabular-nums text-muted">
                {index + 1}
              </span>
              <span className="font-medium">{section.label}</span>
              <span className={`chip ${WEIGHT_TONE[section.weight]}`}>
                {section.weight.replace("_", " ")}
              </span>
            </div>
            <p className="ml-8 mt-1 text-sm text-muted">{section.why}</p>
            {section.should_contain.length > 0 && (
              <ul className="ml-8 mt-1.5 space-y-0.5">
                {section.should_contain.map((item) => (
                  <li key={item} className="text-sm text-muted">
                    · {item}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>

      <div className="space-y-2 border-t raised px-5 py-4 text-sm">
        <p>
          <span className="text-muted">Summary formula: </span>
          <code className="text-xs">{blueprint.summary_formula}</code>
        </p>
        <p>
          <span className="text-muted">Experience bullets: </span>
          <code className="text-xs">{blueprint.bullet_pattern}</code>
        </p>
        {blueprint.notes.map((note) => (
          <p key={note} className="text-muted">
            {note}
          </p>
        ))}
      </div>
    </div>
  );
}

/** How one CV is built for this job. Kept visually distinct from the job match. */
export function TemplateBlock({ report }: { report: TemplateReport }) {
  const misordered =
    report.candidate_order.length > 0 &&
    report.ideal_order.filter((k) => report.candidate_order.includes(k)).join() !==
      report.candidate_order.filter((k) => report.ideal_order.includes(k)).join();

  return (
    <div className="mt-3 space-y-3 border-t pt-3">
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium">CV built for this role</span>
        <span className="text-sm font-semibold tabular-nums">{report.percent}%</span>
        <span className="text-xs text-muted">{report.band}</span>
        <span className="ml-auto text-xs text-muted">
          separate from the job match — different question
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted">
            <tr>
              <th className="py-1 pr-3 font-normal">Section</th>
              <th className="py-1 pr-3 font-normal">Ideal</th>
              <th className="py-1 pr-3 font-normal">Candidate</th>
              <th className="py-1 font-normal">Detail</th>
            </tr>
          </thead>
          <tbody>
            {report.sections.map((finding) => (
              <tr key={finding.key} className="border-t">
                <td className="py-1.5 pr-3">{finding.label}</td>
                <td className="py-1.5 pr-3 text-muted">
                  {finding.weight.replace("_", " ")}
                </td>
                <td className="py-1.5 pr-3">
                  <span className={`chip ${SECTION_TONE[finding.status]}`}>
                    {SECTION_WORD[finding.status]}
                  </span>
                </td>
                <td className="py-1.5 text-muted">{finding.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {misordered && (
        <p className="text-sm text-muted">
          <span className="text-ink">Order</span> — ideal:{" "}
          {report.ideal_order.map((k) => SECTION_LABEL[k] ?? k).join(" → ")}
          <br />
          <span className="text-ink">This CV</span>:{" "}
          {report.candidate_order.map((k) => SECTION_LABEL[k] ?? k).join(" → ")}
        </p>
      )}

      {Object.keys(report.skill_placement).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(report.skill_placement).map(([skill, where]) => (
            <span
              key={skill}
              className={`chip ${
                where === PLACEMENT_DEMONSTRATED
                  ? "bg-good-wash text-good"
                  : where === PLACEMENT_LISTED
                    ? "bg-warn-wash text-warn"
                    : "raised text-muted"
              }`}
              title={`${skill}: ${where}`}
            >
              {skill} · {where}
            </span>
          ))}
        </div>
      )}

      {report.recommendations.length > 0 && (
        <div>
          <p className="mb-1.5 text-sm font-medium">What to change</p>
          <ul className="space-y-1.5">
            {report.recommendations.map((recommendation, index) => (
              <li key={index} className="flex gap-2 text-sm">
                <span className={`chip shrink-0 ${PRIORITY_TONE[recommendation.priority]}`}>
                  {recommendation.priority}
                </span>
                <span className="text-muted">{recommendation.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
