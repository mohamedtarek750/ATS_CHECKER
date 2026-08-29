"""Stage 6 - does this CV present its owner's qualifications well for this job?

A different question from stage 4. Stage 4 asks whether the candidate is qualified;
this asks whether the document says so effectively. Conflating the two costs good
engineers who write badly and rewards weak candidates who write well, so the two
scores stay separate and are never added together.

Entirely deterministic. Everything here is countable — which sections exist, in
what order, whether bullets carry outcomes, where the required skills actually
appear — so there is no model call, no variance between runs, and every point of
the score can be pointed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ..blueprint import CVBlueprint, SectionSpec
from ..models import CandidateProfile
from ..skills import mentions
from .match import MatchResult

SectionStatus = Literal["excellent", "good", "partial", "weak", "missing", "not_relevant"]
Priority = Literal["high", "medium", "low"]

#: A bullet that reports an outcome nearly always carries a number.
_METRIC = re.compile(
    r"\d+\s*%|\d+\s*(?:x|times)\b|[\$€£]\s*\d|\b\d{2,}\b|\bby \d|\bfrom \d+\s*(?:to|-)\s*\d+",
    re.IGNORECASE,
)
#: Openings that describe duties rather than what the person actually did.
_DUTY_OPENERS = (
    "responsible for", "duties included", "tasked with", "in charge of",
    "worked on", "helped with", "assisted with", "involved in", "participated in",
)
_ACTION_VERBS = (
    "built", "designed", "led", "shipped", "migrated", "automated", "rewrote",
    "reduced", "increased", "cut", "delivered", "owned", "launched", "scaled",
    "implemented", "developed", "created", "improved", "optimised", "optimized",
    "introduced", "established", "wrote", "trained", "deployed",
)


@dataclass
class SectionFinding:
    key: str
    label: str
    weight: str
    status: SectionStatus
    detail: str

    @property
    def is_gap(self) -> bool:
        return self.status in {"missing", "weak", "partial"}


@dataclass
class Recommendation:
    priority: Priority
    text: str


@dataclass
class TemplateReport:
    """How well this CV is built for this job, and what to change."""

    job_title: str
    percent: int
    sections: list[SectionFinding] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    ideal_order: list[str] = field(default_factory=list)
    candidate_order: list[str] = field(default_factory=list)
    #: Where each priority skill is evidenced: skills list, or actual work.
    skill_placement: dict[str, str] = field(default_factory=dict)

    @property
    def band(self) -> str:
        if self.percent >= 80:
            return "Well built for this role"
        if self.percent >= 60:
            return "Workable, with clear gaps"
        if self.percent >= 40:
            return "Poorly targeted at this role"
        return "Not written for this role"


# --------------------------------------------------------------------------
# The individual checks
# --------------------------------------------------------------------------
def _has_section(profile: CandidateProfile, key: str) -> bool:
    """A section counts as present when it has content, not just a heading."""
    if key == "contact":
        return bool(profile.email or profile.phone)
    if key == "summary":
        return bool(profile.summary_text.strip())
    if key == "skills":
        return bool(profile.skills)
    if key == "experience":
        return bool(profile.experience)
    if key == "projects":
        return bool(profile.projects)
    if key == "education":
        return bool(profile.education)
    if key == "certifications":
        return bool(profile.certifications)
    if key == "languages":
        return bool(profile.languages)
    return key in profile.sections_found


def _bullets(profile: CandidateProfile) -> list[str]:
    return [line for job in profile.experience for line in job.highlights]


def _achievement_ratio(profile: CandidateProfile) -> tuple[float, int, int]:
    """How many experience bullets report an outcome rather than a duty."""
    bullets = _bullets(profile)
    if not bullets:
        return (0.0, 0, 0)
    with_metric = sum(1 for b in bullets if _METRIC.search(b))
    return (with_metric / len(bullets), with_metric, len(bullets))


def _duty_bullets(profile: CandidateProfile) -> list[str]:
    return [
        bullet
        for bullet in _bullets(profile)
        if bullet.lower().startswith(_DUTY_OPENERS)
        or not any(bullet.lower().startswith(v) for v in _ACTION_VERBS)
    ]


def _summary_finding(profile: CandidateProfile, blueprint: CVBlueprint,
                     spec: SectionSpec) -> SectionFinding:
    """A summary is judged on whether it positions the candidate, not its length."""
    text = profile.summary_text.strip()
    if not text:
        return SectionFinding(
            "summary", spec.label, spec.weight, "missing",
            f"No summary. For a {blueprint.seniority.lower()} {blueprint.job_title} "
            f"this is the first thing read.",
        )

    hits = [
        item for item in blueprint.summary_should_mention if mentions(text, item)
    ]
    has_years = bool(re.search(r"\d+\+?\s*(?:years|yrs)", text, re.IGNORECASE))
    score = len(hits) + (1 if has_years else 0)

    if score >= 3:
        return SectionFinding(
            "summary", spec.label, spec.weight, "excellent",
            f"Positions for the role and names {', '.join(hits[:3])}.",
        )
    if score >= 1:
        missing = [m for m in blueprint.summary_should_mention if m not in hits][:2]
        return SectionFinding(
            "summary", spec.label, spec.weight, "partial",
            "Present, but does not mention " + " or ".join(missing) + "."
            if missing
            else "Present, but thin on what matters for this role.",
        )
    return SectionFinding(
        "summary", spec.label, spec.weight, "weak",
        "Generic - it does not mention the target role, the years, or any of the "
        "technologies this job asks for.",
    )


def _experience_finding(profile: CandidateProfile, blueprint: CVBlueprint,
                        spec: SectionSpec) -> SectionFinding:
    if not profile.experience:
        return SectionFinding(
            "experience", spec.label, spec.weight,
            "missing" if spec.weight == "required" else "not_relevant",
            "No professional experience found in the CV.",
        )

    bullets = _bullets(profile)
    if not bullets:
        return SectionFinding(
            "experience", spec.label, spec.weight, "weak",
            f"{len(profile.experience)} role(s) listed with no description of what "
            f"was done in them. Titles and dates alone are not evidence.",
        )

    ratio, with_metric, total = _achievement_ratio(profile)
    duties = len(_duty_bullets(profile))

    if blueprint.wants_metrics and ratio < 0.2:
        return SectionFinding(
            "experience", spec.label, spec.weight, "partial",
            f"{total} bullet(s), {with_metric} with a measurable outcome. A "
            f"{blueprint.seniority.lower()} application is read for impact.",
        )
    if duties > total * 0.6:
        return SectionFinding(
            "experience", spec.label, spec.weight, "partial",
            f"{duties} of {total} bullets describe duties rather than what was "
            f"achieved.",
        )
    return SectionFinding(
        "experience", spec.label, spec.weight,
        "excellent" if ratio >= 0.3 else "good",
        f"{len(profile.experience)} role(s), {total} bullet(s)"
        + (f", {with_metric} with measurable outcomes." if with_metric else "."),
    )


def _skills_finding(profile: CandidateProfile, blueprint: CVBlueprint,
                    spec: SectionSpec) -> SectionFinding:
    """Counting skills rewards the wrong thing.

    Thirty keywords with nothing behind them is not a better skills section than
    nine that the CV goes on to prove - it is a worse one, and scoring by length
    is precisely how an ATS ends up ranking a stuffer alongside an engineer.
    """
    if not profile.skills:
        return SectionFinding(
            spec.key, spec.label, spec.weight,
            "missing" if spec.weight == "required" else "weak",
            f"No skills section. This job names {len(blueprint.priority_skills)} "
            f"technologies a reader will look for.",
        )

    wanted = blueprint.priority_skills
    evidence = profile.evidence_text()
    shown = [s for s in wanted if mentions(evidence, s)]
    listed = [
        s for s in wanted
        if s not in shown and any(mentions(skill, s) for skill in profile.skills)
    ]
    total_listed = len(profile.skills)
    relevant = len(shown) + len(listed)
    noise = total_listed - relevant

    if not wanted:
        return SectionFinding(spec.key, spec.label, spec.weight, "good",
                              f"{total_listed} skill(s) listed.")

    coverage = relevant / len(wanted)

    # A long list where almost nothing is evidenced is the stuffing signature.
    if total_listed >= 20 and not shown:
        return SectionFinding(
            spec.key, spec.label, spec.weight, "weak",
            f"{total_listed} skills listed and none of the {len(wanted)} this job "
            f"asks for appear anywhere else in the CV. A long list with no "
            f"supporting work reads as padding.",
        )
    if not shown and listed:
        return SectionFinding(
            spec.key, spec.label, spec.weight, "partial",
            f"{len(listed)} of {len(wanted)} required technologies are listed, but "
            f"none is shown in a role or project.",
        )
    if coverage >= 0.75 and len(shown) >= len(listed):
        detail = (
            f"{len(shown)} of {len(wanted)} required technologies are shown in "
            f"actual work"
        )
        if noise > 12:
            return SectionFinding(
                spec.key, spec.label, spec.weight, "good",
                f"{detail}, though {noise} listed skills are not relevant to this role.",
            )
        return SectionFinding(spec.key, spec.label, spec.weight, "excellent",
                              detail + ".")
    if coverage >= 0.5:
        return SectionFinding(
            spec.key, spec.label, spec.weight, "good",
            f"{relevant} of {len(wanted)} required technologies present "
            f"({len(shown)} shown in work).",
        )
    return SectionFinding(
        spec.key, spec.label, spec.weight, "partial",
        f"Only {relevant} of {len(wanted)} required technologies appear.",
    )


def _focus_ratio(profile: CandidateProfile, blueprint: CVBlueprint) -> tuple[float, int, int]:
    """How much of the experience section is about work relevant to this job."""
    bullets = _bullets(profile)
    if not bullets or not blueprint.priority_skills:
        return (1.0, 0, 0)
    relevant = sum(
        1
        for bullet in bullets
        if any(mentions(bullet, skill) for skill in blueprint.priority_skills)
    )
    return (relevant / len(bullets), relevant, len(bullets))


def _plain_finding(profile: CandidateProfile, spec: SectionSpec) -> SectionFinding:
    present = _has_section(profile, spec.key)
    if present:
        detail = {
            "contact": "Reachable.",
            "skills": f"{len(profile.skills)} skill(s) listed.",
            "projects": f"{len(profile.projects)} project(s).",
            "education": "Present.",
            "certifications": f"{len(profile.certifications)} listed.",
            "languages": f"{len(profile.languages)} listed.",
        }.get(spec.key, "Present.")
        return SectionFinding(spec.key, spec.label, spec.weight, "good", detail)

    if spec.weight == "required":
        return SectionFinding(spec.key, spec.label, spec.weight, "missing", spec.why)
    if spec.weight == "recommended":
        return SectionFinding(
            spec.key, spec.label, spec.weight, "weak",
            f"Not present. {spec.why}",
        )
    return SectionFinding(
        spec.key, spec.label, spec.weight, "not_relevant",
        "Not present, and not important for this role.",
    )


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
#: Fixed in code, like the ranking weights, and for the same reason.
_STATUS_CREDIT = {
    "excellent": 1.0, "good": 0.85, "partial": 0.5,
    "weak": 0.25, "missing": 0.0, "not_relevant": None,
}
_WEIGHT_VALUE = {"required": 3.0, "recommended": 1.5, "optional": 0.5, "low_value": 0.2}


def evaluate(
    profile: CandidateProfile,
    blueprint: CVBlueprint,
    job_match: MatchResult | None = None,
) -> TemplateReport:
    """Compare one CV against the ideal for this job."""
    findings: list[SectionFinding] = []

    for spec in blueprint.sections:
        if spec.key == "summary":
            findings.append(_summary_finding(profile, blueprint, spec))
        elif spec.key == "experience":
            findings.append(_experience_finding(profile, blueprint, spec))
        elif spec.key == "skills":
            findings.append(_skills_finding(profile, blueprint, spec))
        else:
            findings.append(_plain_finding(profile, spec))

    # --- score -----------------------------------------------------------
    earned = possible = 0.0
    for finding in findings:
        credit = _STATUS_CREDIT[finding.status]
        if credit is None:
            continue
        value = _WEIGHT_VALUE[finding.weight]
        earned += credit * value
        possible += value

    # Order counts too, but lightly: it is a real problem and a cheap fix.
    order_penalty, order_note = _order_penalty(profile, blueprint)
    percent = int(round((earned / possible if possible else 0) * 100)) - order_penalty
    percent = max(0, min(100, percent))

    # --- where the priority skills actually appear (§12) -------------------
    placement: dict[str, str] = {}
    evidence = profile.evidence_text()
    for skill in blueprint.priority_skills:
        if mentions(evidence, skill):
            placement[skill] = "shown in work"
        elif any(mentions(s, skill) for s in profile.skills):
            placement[skill] = "skills list only"
        else:
            placement[skill] = "absent"

    report = TemplateReport(
        job_title=blueprint.job_title,
        percent=percent,
        sections=findings,
        ideal_order=blueprint.order,
        candidate_order=profile.sections_found,
        skill_placement=placement,
    )

    # --- what is strong, what is not --------------------------------------
    for finding in findings:
        if finding.status in {"excellent", "good"}:
            report.strengths.append(f"{finding.label}: {finding.detail}")
        elif finding.status != "not_relevant":
            report.improvements.append(f"{finding.label}: {finding.detail}")
    if order_note:
        report.improvements.append(order_note)

    focus, relevant, total_bullets = _focus_ratio(profile, blueprint)
    if total_bullets >= 4 and focus < 0.34:
        report.improvements.append(
            f"Content priority: only {relevant} of {total_bullets} experience "
            f"bullets relate to what this job asks for. The relevant work is being "
            f"crowded out by the rest."
        )

    report.recommendations = _recommendations(
        profile, blueprint, findings, placement, order_note, focus, relevant,
        total_bullets,
    )
    return report


def _order_penalty(profile: CandidateProfile, blueprint: CVBlueprint) -> tuple[int, str]:
    """Is the most important section buried?

    Only checked where the CV actually declares its sections; a CV whose headings
    we could not read is not penalised for a layout we never saw.
    """
    order = profile.sections_found
    if not order or "experience" not in order or "education" not in order:
        return (0, "")

    senior_ish = blueprint.rank_of("experience") is not None and blueprint.rank_of(
        "education"
    ) is not None
    if not senior_ish:
        return (0, "")

    ideal_experience = blueprint.order.index("experience")
    ideal_education = blueprint.order.index("education")
    if ideal_experience < ideal_education and order.index("education") < order.index(
        "experience"
    ):
        return (
            8,
            "Section order: education appears before professional experience. For "
            f"a {blueprint.seniority.lower()} {blueprint.job_title} the work is the "
            "stronger evidence and should be read first.",
        )
    return (0, "")


def _recommendations(
    profile: CandidateProfile,
    blueprint: CVBlueprint,
    findings: list[SectionFinding],
    placement: dict[str, str],
    order_note: str,
    focus: float = 1.0,
    relevant: int = 0,
    total_bullets: int = 0,
) -> list[Recommendation]:
    """Specific, checkable changes. Never "improve your resume"."""
    out: list[Recommendation] = []

    if order_note:
        out.append(Recommendation("high", order_note))

    for finding in findings:
        if finding.status == "missing" and finding.weight == "required":
            out.append(Recommendation(
                "high",
                f"Add a {finding.label} section. {finding.detail}",
            ))

    # A skill the job requires that is only claimed, never shown. This is the most
    # actionable thing the system can say: the candidate may well have it.
    listed_only = [s for s, where in placement.items() if where == "skills list only"]
    for skill in listed_only[:3]:
        out.append(Recommendation(
            "high",
            f"'{skill}' appears in your skills list but nowhere in your experience "
            f"or projects. If you have used it, say where and what you built with "
            f"it - a skill shown in a role counts for far more than one listed.",
        ))

    absent = [s for s, where in placement.items() if where == "absent"]
    for skill in absent[:2]:
        out.append(Recommendation(
            "high",
            f"The job asks for '{skill}' and the CV does not mention it. If you have "
            f"used it, add it to your skills and describe where you used it.",
        ))

    summary = next((f for f in findings if f.key == "summary"), None)
    if summary and summary.status in {"weak", "missing", "partial"}:
        out.append(Recommendation(
            "medium",
            f"Rewrite the summary around this role: {blueprint.summary_formula}. "
            f"It should mention {', '.join(blueprint.summary_should_mention[:3])}.",
        ))

    ratio, with_metric, total = _achievement_ratio(profile)
    if blueprint.wants_metrics and total and ratio < 0.3:
        out.append(Recommendation(
            "medium",
            f"Only {with_metric} of {total} experience bullets carry a measurable "
            f"result. Add numbers where they are true - never invent them. The "
            f"pattern that works is: {blueprint.bullet_pattern}.",
        ))

    duties = _duty_bullets(profile)
    if duties and len(duties) > len(_bullets(profile)) * 0.5:
        out.append(Recommendation(
            "medium",
            f"{len(duties)} bullets read as duties rather than achievements, e.g. "
            f"\"{duties[0][:70]}\". Start with what you did and what changed.",
        ))

    projects = next((f for f in findings if f.key == "projects"), None)
    if projects and projects.status in {"missing", "weak"} and blueprint.priority_skills:
        out.append(Recommendation(
            "medium" if projects.weight == "recommended" else "high",
            f"Add two or three projects using {', '.join(blueprint.priority_skills[:3])}. "
            f"For this role they are where a reader looks for proof.",
        ))

    if total_bullets >= 4 and focus < 0.34:
        shown = [s for s, where in placement.items() if where == "shown in work"]
        out.append(Recommendation(
            "high" if focus < 0.2 else "medium",
            f"Only {relevant} of {total_bullets} experience bullets touch what this "
            f"job asks for"
            + (
                f". Move your {shown[0]} work higher and give it more space than the "
                f"unrelated responsibilities."
                if shown
                else ", so the relevant work is hard to find. Lead each role with the "
                     "part that matters for this job."
            ),
        ))

    for finding in findings:
        if finding.status == "weak" and finding.weight == "recommended":
            out.append(Recommendation("low", f"{finding.label}: {finding.detail}"))

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda r: order[r.priority])
    return out[:10]
