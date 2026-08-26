"""Stage 2 without any model: rules, regex, and the skills table.

Instant, free, unlimited, and nothing leaves the machine — which is the whole
point when the alternative is 20 CVs a day and other people's personal data sent
to a free tier.

It is not as good as a model on messy prose, and it does not pretend to be. What it
is good at is exactly what stages 4 and 5 consume: contact details, dates, degrees,
and above all the skills vocabulary, which is dictionary lookup rather than
comprehension. On a normal CV that is most of the value.

Use it as the default at volume, and re-read the shortlist with a model when the
decisions get close. `ats_cli.py`-style hybrid: `ATS_PROVIDER=offline` for intake,
then a model pass over the top 50.
"""

from __future__ import annotations

import re
from datetime import date

from ..models import CandidateProfile, Education, Experience
from ..skills import ALIASES, mentions
from .parse import ParsedDoc

# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?:\+?\d[\d\s\-().]{7,}\d)")
LINK = re.compile(r"(?:https?://|www\.)[^\s,;)]+|(?:linkedin\.com|github\.com)/[^\s,;)]+",
                  re.IGNORECASE)
YEAR = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")

MONTH = (
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
)
DATE_RANGE = re.compile(
    rf"((?:{MONTH}\s+)?\d{{4}})\s*(?:-|–|—|to|until)\s*"
    rf"((?:{MONTH}\s+)?\d{{4}}|present|current|now|till date)",
    re.IGNORECASE,
)

DEGREE_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("phd", ("ph.d", "phd", "doctorate", "doctoral")),
    ("master", ("master", "m.sc", "msc", "m.a", "mba", "m.eng", "meng")),
    ("bachelor", ("bachelor", "b.sc", "bsc", "b.a", "b.eng", "beng", "b.tech",
                  "licence", "undergraduate")),
    ("diploma", ("diploma", "associate degree", "technical institute")),
    ("high_school", ("high school", "secondary school", "thanaweya")),
]

SECTION_HEADINGS = {
    "experience": ("work experience", "professional experience", "employment",
                   "experience", "career history", "work history"),
    "education": ("education", "academic background", "qualifications",
                  "academic qualifications"),
    "skills": ("skills", "technical skills", "core competencies", "competencies",
               "technologies", "technical proficiencies"),
    "projects": ("projects", "technical projects", "selected projects",
                 "personal projects"),
    "certifications": ("certifications", "certificates", "licenses",
                       "courses", "training"),
    "languages": ("languages", "language skills"),
    "summary": ("summary", "profile", "objective", "about me", "professional summary"),
}

LANGUAGE_NAMES = (
    "arabic", "english", "french", "german", "spanish", "italian", "russian",
    "chinese", "turkish", "japanese",
)

NOT_A_CV_HINTS = (
    ("cover_letter", ("dear hiring manager", "dear sir", "yours sincerely",
                      "i am writing to apply", "yours faithfully")),
    ("job_description", ("what we offer", "responsibilities:", "we are looking for",
                         "applications close", "job posting", "how to apply")),
    ("certificate_or_transcript", ("certificate of completion", "this is to certify",
                                   "has successfully completed", "certificate id")),
    ("invoice_or_form", ("invoice", "vat", "subtotal", "payment terms", "total due")),
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _sections(text: str) -> dict[str, str]:
    """Split a CV into named sections by their headings.

    Heading detection is deliberately loose - a short line that matches a known
    heading. CVs use every capitalisation and punctuation under the sun.
    """
    lines = text.split("\n")
    found: list[tuple[int, str]] = []

    for index, line in enumerate(lines):
        stripped = line.strip().strip(":").strip()
        if not stripped or len(stripped) > 45:
            continue
        lowered = stripped.lower()
        for name, headings in SECTION_HEADINGS.items():
            if any(lowered == h or lowered.startswith(h + " ") or lowered == h + ":"
                   for h in headings):
                found.append((index, name))
                break

    out: dict[str, str] = {}
    for position, (index, name) in enumerate(found):
        end = found[position + 1][0] if position + 1 < len(found) else len(lines)
        body = "\n".join(lines[index + 1:end]).strip()
        if body:
            out[name] = out.get(name, "") + "\n" + body if name in out else body
    return out


def _guess_name(text: str, email: str) -> str:
    """The name is almost always the first substantial line of a CV."""
    for line in text.split("\n")[:8]:
        candidate = line.strip()
        if not (3 < len(candidate) < 45):
            continue
        if EMAIL.search(candidate) or PHONE.search(candidate) or "@" in candidate:
            continue
        if any(ch.isdigit() for ch in candidate):
            continue
        words = candidate.replace(".", " ").split()
        if not (1 < len(words) <= 5):
            continue
        # A name is capitalised or fully upper; a heading like "CURRICULUM VITAE"
        # is filtered by the word list below.
        if candidate.lower() in {"curriculum vitae", "resume", "cv", "personal details"}:
            continue
        if all(w[:1].isupper() or w.isupper() for w in words if w):
            return candidate.title() if candidate.isupper() else candidate
    # Fall back to the local part of the email: better than nothing on a CV whose
    # name is in a header image.
    if email:
        local = re.split(r"[._\-0-9]+", email.split("@")[0])
        parts = [p.capitalize() for p in local if len(p) > 1]
        if parts:
            return " ".join(parts[:3])
    return ""


def _education(text: str, sections: dict[str, str]) -> list[Education]:
    body = sections.get("education", "")
    haystack = body or text
    entries: list[Education] = []

    for line in haystack.split("\n"):
        lowered = line.lower()
        level = next(
            (name for name, words in DEGREE_WORDS if any(w in lowered for w in words)),
            None,
        )
        if not level:
            continue
        years = [int(y) for y in YEAR.findall(line)]
        institution = ""
        for marker in ("university", "college", "institute", "academy", "school"):
            match = re.search(rf"([A-Z][\w.'\-]*(?:\s+[\w.'\-]+){{0,4}}\s*{marker})",
                              line, re.IGNORECASE)
            if match:
                institution = match.group(1).strip()
                break
        field = ""
        field_match = re.search(r"(?:in|of)\s+([A-Za-z&\s]{3,45})", line, re.IGNORECASE)
        if field_match:
            field = field_match.group(1).strip(" ,.-")
        entries.append(
            Education(
                degree=level,           # type: ignore[arg-type]
                field_of_study=field,
                institution=institution,
                graduation_year=max(years) if years else 0,
            )
        )
    return entries[:5]


def _experience(sections: dict[str, str]) -> tuple[list[Experience], float]:
    """Roles and total professional years, from the dated lines in the CV.

    Years are computed from the date ranges rather than from any claim in the
    text, and overlapping ranges are merged so two concurrent jobs are not
    counted twice.
    """
    body = sections.get("experience", "")
    entries: list[Experience] = []
    spans: list[tuple[float, float]] = []
    today = date.today().year + date.today().month / 12

    for line in body.split("\n"):
        match = DATE_RANGE.search(line)
        if not match:
            continue
        start_years = YEAR.findall(match.group(1))
        if not start_years:
            continue
        start = float(start_years[0])
        end_text = match.group(2).lower()
        if any(w in end_text for w in ("present", "current", "now", "till")):
            end = today
        else:
            end_years = YEAR.findall(end_text)
            end = float(end_years[0]) if end_years else start

        title = line[: match.start()].strip(" -|,–—\t")
        company = ""
        for separator in (" - ", " | ", " at ", ", ", " – "):
            if separator in title:
                head, _, tail = title.partition(separator)
                title, company = head.strip(), tail.strip()
                break

        internship = "intern" in line.lower()
        entries.append(
            Experience(
                title=title[:80] or "Role",
                company=company[:80],
                start=str(int(start)),
                end="present" if end >= today - 0.1 else str(int(end)),
                years=round(max(0.0, end - start), 1),
                is_internship=internship,
                highlights=[],
            )
        )
        if not internship:
            spans.append((start, max(end, start)))

    # Merge overlaps so two concurrent roles are not counted twice.
    merged: list[list[float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    total = round(sum(e - s for s, e in merged), 1)

    return entries[:12], total


def _skills(text: str, sections: dict[str, str]) -> list[str]:
    """Dictionary lookup over the whole CV, not just the skills section.

    A tool used in a project counts. This is the part rules do as well as a model,
    because it is vocabulary rather than comprehension.
    """
    found = [name for name in ALIASES if mentions(text, name)]

    # Anything else the candidate listed under Skills, so a technology missing from
    # our table is still captured rather than silently dropped.
    body = sections.get("skills", "")
    for chunk in re.split(r"[,;\n|•·]+", body):
        token = chunk.strip(" .-:")
        if 1 < len(token) <= 32 and not token.lower().startswith(("proficient", "familiar")):
            if token not in found and any(c.isalpha() for c in token):
                found.append(token)
    return found[:60]


def _languages(text: str, sections: dict[str, str]) -> list[str]:
    body = sections.get("languages", "") or text
    out = []
    for language in LANGUAGE_NAMES:
        match = re.search(
            rf"\b{language}\b\s*(?:\(([^)]{{1,20}})\)|[:\-]\s*([A-Za-z ]{{3,18}}))?",
            body, re.IGNORECASE,
        )
        if match:
            level = (match.group(1) or match.group(2) or "").strip()
            out.append(f"{language.capitalize()} ({level})" if level else language.capitalize())
    return out


def _document_type(text: str, sections: dict[str, str], has_contact: bool) -> tuple[str, bool]:
    lowered = text.lower()
    for kind, hints in NOT_A_CV_HINTS:
        hits = sum(1 for h in hints if h in lowered)
        if hits >= 2 or (hits == 1 and len(text) < 1500 and not sections):
            return kind, False

    # A CV has contact details and at least two of the sections a CV has.
    if has_contact and len(sections) >= 2:
        return "cv_resume", True
    if len(sections) >= 3:
        return "cv_resume", True
    return "other_document", False


# --------------------------------------------------------------------------
# The extractor
# --------------------------------------------------------------------------
def extract_profile(doc: ParsedDoc) -> CandidateProfile:
    """Build a CandidateProfile from a CV using rules only. Never calls a model."""
    text = doc.text
    sections = _sections(text)

    emails = EMAIL.findall(text)
    email = emails[0].lower() if emails else ""
    phones = [p.strip() for p in PHONE.findall(text) if len(re.sub(r"\D", "", p)) >= 9]
    links = list(dict.fromkeys(LINK.findall(text)))[:5]

    education = _education(text, sections)
    experience, years = _experience(sections)
    skills = _skills(text, sections)

    kind, is_cv = _document_type(text, sections, bool(email or phones))

    headline = ""
    if experience:
        headline = experience[0].title
    elif education:
        headline = education[0].field_of_study

    seniority = "unknown"
    if not is_cv:
        seniority = "unknown"
    elif years >= 8:
        seniority = "lead"
    elif years >= 5:
        seniority = "senior"
    elif years >= 2:
        seniority = "mid"
    elif years > 0:
        seniority = "junior"
    elif education:
        seniority = "student"

    certifications = [
        line.strip(" -•·\t")
        for line in sections.get("certifications", "").split("\n")
        if 3 < len(line.strip()) < 120
    ][:12]

    projects = [
        line.strip(" -•·\t")
        for line in sections.get("projects", "").split("\n")
        if 8 < len(line.strip()) < 160
    ][:12]

    return CandidateProfile(
        full_name=_guess_name(text, email),
        email=email,
        phone=phones[0] if phones else "",
        location="",
        links=links,
        headline=headline[:60],
        seniority=seniority,                     # type: ignore[arg-type]
        total_years_experience=years,
        education=education,
        experience=experience,
        skills=skills,
        certifications=certifications,
        languages=_languages(text, sections),
        projects=projects,
        document_type=kind,                      # type: ignore[arg-type]
        is_cv=is_cv,
        # Rules cannot judge whether prose was written by a model. Reporting a
        # number here would be inventing one, so this path stays silent and the
        # flag simply never fires.
        ai_generated_score=0,
        ai_signals=[],
    )
