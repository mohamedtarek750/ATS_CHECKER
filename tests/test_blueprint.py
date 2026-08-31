"""The template feature answers a different question from the matcher.

The decisive test is one person with one set of qualifications, written up two
ways. The job match must be near-identical - the qualifications have not changed -
while the template match must separate them, because one CV presents those
qualifications for this job and the other buries them.

If both scores move together, the feature is measuring the same thing twice and is
not worth having.

Run: python tests/test_blueprint.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ats.blueprint import blueprint_for, render  # noqa: E402
from ats.job_profile import JobProfile, Requirement  # noqa: E402
from ats.stages import match as match_stage  # noqa: E402
from ats.stages import offline, parse, rank  # noqa: E402
from ats.stages import template_match as template  # noqa: E402

JOB = JobProfile(
    title="Senior Data Analyst",
    seniority="Senior",
    summary="Owns the reporting layer.",
    min_years_experience=5,
    requirements=[
        Requirement(text="5+ years of professional experience", kind="experience",
                    importance="must_have"),
        Requirement(text="SQL", kind="skill", importance="must_have"),
        Requirement(text="Power BI", kind="skill", importance="must_have"),
        Requirement(text="Python", kind="skill", importance="nice_to_have"),
        Requirement(text="Bachelor degree in Statistics or a related field",
                    kind="education", importance="must_have"),
    ],
)

# The same person. The same work. The same skills. Written well.
WELL_WRITTEN = """MONA SALEH
Cairo, Egypt | +20 100 111 2222 | mona@example.com

PROFESSIONAL SUMMARY
Senior Data Analyst with 7 years in retail reporting. SQL and Power BI across the
commercial stack, with Python for the heavier transformations.

TECHNICAL SKILLS
SQL, Power BI, Python, Excel

PROFESSIONAL EXPERIENCE
Senior Data Analyst - Alameda Retail (2018 - present)
- Rebuilt the commercial pack in Power BI, cutting reporting time by 30%.
- Rewrote the stock-cover query in SQL, from 6 minutes to 40 seconds.
- Automated the monthly close in Python, replacing 4 manual spreadsheets.

PROJECTS
- Demand forecasting model in Python for a bakery chain.

EDUCATION
Bachelor of Statistics, Cairo University, 2018
"""

# Same qualifications, presented badly: education first, no summary, duties
# instead of outcomes, and the relevant work buried under unrelated admin.
BADLY_WRITTEN = """MONA SALEH
mona@example.com | +20 100 111 2222

EDUCATION
Bachelor of Statistics, Cairo University, 2018

WORK EXPERIENCE
Senior Data Analyst - Alameda Retail (2018 - present)
- Responsible for attending the weekly commercial meeting.
- Duties included filing, printing and distributing the monthly pack.
- Worked on maintaining the shared drive and the team calendar.
- Assisted with onboarding paperwork for new joiners.
- Involved in the office relocation committee.
- Helped with reporting using SQL and Power BI when required.

SKILLS
SQL, Power BI, Python, Excel
"""


def profile_from(text: str):
    tmp = Path(tempfile.mkdtemp())
    try:
        path = tmp / "cv.txt"
        path.write_text(text, encoding="utf-8")
        return offline.extract_profile(parse.parse_one(path))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def scores(text: str) -> tuple[int, int, template.TemplateReport]:
    profile = profile_from(text)
    result = match_stage.match(profile, JOB, "cv.txt")
    job_percent = rank.rank([result])[0].percent
    report = template.evaluate(profile, blueprint_for(JOB), result)
    return job_percent, report.percent, report


# --------------------------------------------------------------------------
# The blueprint itself
# --------------------------------------------------------------------------
def test_the_blueprint_is_job_specific_not_generic():
    senior = blueprint_for(JOB)
    graduate = blueprint_for(
        JobProfile(
            title="Graduate Software Engineer", seniority="Fresh graduate",
            summary="", min_years_experience=0,
            requirements=[
                Requirement(text="Java", kind="skill", importance="must_have"),
                Requirement(text="Git", kind="skill", importance="must_have"),
            ],
        )
    )
    sales = blueprint_for(
        JobProfile(
            title="Sales Manager", seniority="Senior", summary="",
            min_years_experience=6,
            requirements=[
                Requirement(text="B2B sales", kind="skill", importance="must_have"),
                Requirement(text="CRM", kind="skill", importance="must_have"),
                Requirement(text="6 years experience", kind="experience",
                            importance="must_have"),
            ],
        )
    )

    # A technical role is scanned for its stack; a sales role is read for outcomes.
    assert senior.order.index("skills") < senior.order.index("experience")
    assert sales.order.index("experience") < sales.order.index("skills")

    # Projects carry the evidence when there is no work history yet.
    assert graduate.spec("projects").weight == "required"
    assert senior.spec("projects").weight == "recommended"

    # And a graduate is not asked for metrics they cannot have.
    assert senior.wants_metrics
    assert not graduate.wants_metrics

    # The priority skills come from the job, must-haves first.
    assert senior.priority_skills[:2] == ["SQL", "Power BI"]


def test_the_preview_is_a_blueprint_not_an_invented_cv():
    text = render(blueprint_for(JOB))
    assert "IDEAL CV" in text and "SENIOR DATA ANALYST" in text
    assert "[required]" in text
    # It must never fabricate a person.
    for invented in ("Mona", "years of experience at", "@example.com"):
        assert invented not in text


# --------------------------------------------------------------------------
# The point of the feature
# --------------------------------------------------------------------------
def test_same_qualifications_written_two_ways():
    good_job, good_template, good_report = scores(WELL_WRITTEN)
    poor_job, poor_template, poor_report = scores(BADLY_WRITTEN)

    # The qualifications are identical, so the job match should barely move.
    assert abs(good_job - poor_job) <= 12, (
        f"job match moved {good_job} -> {poor_job}; the candidate is the same person"
    )

    # The presentation is not identical, and the template score must say so.
    assert good_template - poor_template >= 20, (
        f"template match {good_template} vs {poor_template} - too close to be useful"
    )
    assert good_template >= 70
    assert poor_template <= 60


def test_the_badly_written_cv_is_told_exactly_what_to_change():
    _job, _percent, report = scores(BADLY_WRITTEN)
    text = " ".join(r.text for r in report.recommendations).lower()

    assert report.recommendations, "a CV with this many problems must get advice"
    assert any(r.priority == "high" for r in report.recommendations)

    # Every recommendation has to be actionable rather than "improve your resume".
    for recommendation in report.recommendations:
        assert len(recommendation.text) > 40
        assert "improve your" not in recommendation.text.lower()

    # The specific, checkable problems in this CV.
    assert "education" in text and "experience" in text, "the order problem"
    assert "summary" in text, "the missing summary"


def test_section_order_is_reported_against_the_ideal():
    _job, _percent, report = scores(BADLY_WRITTEN)
    assert report.ideal_order, "the ideal order is part of the comparison"
    assert report.candidate_order, "so is what the candidate actually did"
    assert report.candidate_order.index("education") < report.candidate_order.index(
        "experience"
    )


def test_a_skill_only_listed_is_reported_as_such():
    """Section 12: presence is not evidence, and the report must distinguish."""
    _job, _percent, report = scores(WELL_WRITTEN)
    assert report.skill_placement["Power BI"] == template.PLACEMENT_DEMONSTRATED

    listed_only = profile_from(
        "AHMED\na@example.com\n\nEXPERIENCE\nAdmin - Shop (2019 - 2024)\n"
        "- Filed paperwork.\n\nSKILLS\nSQL, Power BI\n\nEDUCATION\n"
        "Bachelor of Statistics, Cairo University, 2019\n"
    )
    second = template.evaluate(listed_only, blueprint_for(JOB))
    assert second.skill_placement["Power BI"] == template.PLACEMENT_LISTED
    assert second.skill_placement["Python"] == template.PLACEMENT_MISSING


def test_a_keyword_wall_is_not_a_good_skills_section():
    """Counting skills would rank a stuffer above a focused CV."""
    stuffed = profile_from(
        "SAMY\ns@example.com\n\nEXPERIENCE\nIntern - Shop (2024 - 2024)\n"
        "- Data entry.\n\nSKILLS\n"
        + ", ".join(
            [
                "SQL", "Power BI", "Python", "Excel", "Tableau", "AWS", "Azure",
                "GCP", "Spark", "Kafka", "Airflow", "dbt", "Docker", "Kubernetes",
                "Java", "Scala", "React", "Angular", "Vue", "Django", "Flask",
                "MongoDB", "Redis", "Snowflake", "Databricks",
            ]
        )
        + "\n\nEDUCATION\nBachelor of Commerce, 2024\n"
    )
    report = template.evaluate(stuffed, blueprint_for(JOB))
    skills = next(f for f in report.sections if f.key == "skills")
    assert skills.status in {"weak", "partial"}, skills.detail
    assert "padding" in skills.detail or "none is shown" in skills.detail


def test_the_two_scores_are_never_added_together():
    """They answer different questions and must stay separately reported."""
    job_percent, template_percent, report = scores(BADLY_WRITTEN)
    assert report.percent == template_percent
    assert not hasattr(report, "overall")
    assert report.band


def test_the_panel_never_contradicts_the_requirement_list():
    """Two answers to one question on one screen is worse than either answer.

    The panel used to re-derive where a skill sat with plain text matching, so a
    requirement written "Strong SQL" missed a skills entry reading "SQL" - and the
    candidate was told to add a skill their CV lists, directly underneath a row
    saying the requirement was met.
    """
    from ats.job_profile import JobProfile, Requirement
    from ats.models import CandidateProfile, Education, Experience

    job = JobProfile(
        title="Data Analyst", seniority="Mid", summary="Owns reporting.",
        min_years_experience=2,
        requirements=[
            Requirement(text="Strong SQL", kind="skill", importance="must_have"),
            Requirement(text="Power BI", kind="skill", importance="must_have"),
            Requirement(text="Docker", kind="skill", importance="nice_to_have"),
        ],
    )
    candidate = CandidateProfile(
        full_name="Mohamed Tarek", email="m@x.com", phone="", location="", links=[],
        headline="Analyst", seniority="mid", total_years_experience=3.0,
        education=[Education(degree="bachelor", field_of_study="Computer Science",
                             institution="ACU", graduation_year=2023)],
        experience=[Experience(title="Analyst", company="X", start="2023",
                               end="present", years=3, is_internship=False,
                               highlights=["Built revenue dashboards in Power BI."])],
        skills=["SQL", "Power BI", "Python"], certifications=[], languages=[],
        projects=[], summary_text="", sections_found=["experience", "skills"],
        document_type="cv_resume", is_cv=True, ai_generated_score=0, ai_signals=[],
    )

    result = match_stage.match(candidate, job, "cv.pdf")
    report = template.evaluate(candidate, blueprint_for(job), result)

    # SQL is in the skills section, so it is present - never "not mentioned".
    assert report.skill_placement["Strong SQL"] == template.PLACEMENT_LISTED
    assert report.skill_placement["Power BI"] == template.PLACEMENT_DEMONSTRATED
    assert report.skill_placement["Docker"] == template.PLACEMENT_MISSING

    # And the advice must be to demonstrate it, not to add what is already there.
    sql_advice = [r.text for r in report.recommendations if "Strong SQL" in r.text]
    assert sql_advice, "no advice given about a skill listed but never shown"
    assert any("demonstrate" in text.lower() for text in sql_advice)
    assert not any("appears nowhere" in text for text in sql_advice)


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"\n{'FAILED' if failures else 'ALL PASSED'} ({failures} failure(s))")
    raise SystemExit(1 if failures else 0)
