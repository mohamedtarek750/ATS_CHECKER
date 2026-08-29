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
#: Separators people actually use between two dates. Restricting this to a hyphen
#: loses every role on a CV that writes "2016>2020" or "2016 .. 2020", and losing
#: the roles means losing all the evidence.
_RANGE_SEP = r"(?:-{1,2}|–|—|>|=>|→|/|\.{2,}|to|until|through|till)"
DATE_RANGE = re.compile(
    rf"((?:{MONTH}\s+)?\d{{4}})\s*{_RANGE_SEP}\s*"
    rf"((?:{MONTH}\s+)?\d{{4}}|present|current|now|today|ongoing|till date)",
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


def section_order(text: str) -> list[str]:
    """The sections a CV contains, in the order they appear.

    Order is a fact worth recording on its own. A senior CV that opens with
    education is presenting the same qualifications less effectively than one that
    opens with the work - and unlike a missing skill, that is fixable by the
    candidate in ten minutes, which makes it worth telling them about.
    """
    order: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip().strip(":").strip()
        if not stripped or len(stripped) > 45:
            continue
        lowered = stripped.lower()
        for name, headings in SECTION_HEADINGS.items():
            if any(
                lowered == h or lowered.startswith(h + " ") or lowered == h + ":"
                for h in headings
            ):
                if name not in order:
                    order.append(name)
                break
    return order


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


#: Degree words, longest first and word-bounded on both sides.
#: Ordering matters: regex alternation is left-to-right, so a short "b.a"
#: placed before "bachelor" matches the "Ba" inside it and leaves
#: "chelor of Statistics" as the field of study. Both patterns are built from
#: this one ordered list so they cannot drift apart again.
_DEGREE_WORDS_ORDERED = (
    r"bachelor's", r"bachelors", r"bachelor",
    r"master's", r"masters", r"master",
    r"doctorate", r"doctoral",
    r"b\.?sc", r"bsc", r"b\.?eng", r"beng", r"b\.?tech", r"btech",
    r"m\.?sc", r"msc", r"m\.?eng", r"meng", r"mba",
    r"ph\.?d", r"phd",
    r"b\.?a", r"m\.?a",
    r"diploma", r"licence", r"license",
)
_DEGREE_ALT = "|".join(_DEGREE_WORDS_ORDERED)

#: "BSc Computer Science" - the subject follows the degree word.
_DEGREE_LEAD = re.compile(
    rf"\b(?:{_DEGREE_ALT})\b\.?\s*(?:degree)?\s*(?:in|of)?\s*",
    re.IGNORECASE,
)

#: "Computer Engineering BSc" - the degree word trails the subject instead.
_DEGREE_TRAIL = re.compile(
    rf"\s*\b(?:{_DEGREE_ALT}|degree)\b.*",
    re.IGNORECASE,
)


def _field_of_study(line: str, institution: str) -> str:
    """The subject, not the university and not the degree word.

    Both orderings are common - "BSc Computer Science" and "Computer Engineering
    BSc" - and which pattern applies depends on where the degree word sits. Using
    the leading pattern on a trailing CV takes everything *after* the degree word,
    which is the institution and the year, and returns nothing usable.
    """
    text = line
    if institution:
        text = text.replace(institution, " ")

    lead = _DEGREE_LEAD.search(text)
    trail = _DEGREE_TRAIL.search(text)

    # Near the start: the subject follows it. Later: the subject precedes it.
    if lead and lead.start() <= 3:
        text = text[lead.end():]
    elif trail:
        text = text[: trail.start()]
    elif lead:
        text = text[lead.end():]

    # The subject runs to the first comma, dash or year.
    field = re.split(r"[,;|]|\s[-\u2013\u2014]\s|\b(?:19|20)\d{2}\b", text)[0]
    field = re.sub(
        r"\b(?:university|college|institute|academy|school|uni)\b.*", "", field,
        flags=re.IGNORECASE,
    )
    field = field.strip(" ,.-\t")
    return field[:60] if 2 < len(field) < 70 else ""


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
            # At most two words before the marker. Allowing four let "BSc Computer
            # Science - Cairo University" match from "Computer", so removing the
            # institution removed the subject with it.
            match = re.search(
                # No bare dash in the words before the marker: on
                # "BSc Computer Science - Cairo University" it let the match start
                # at "Science", so removing the institution took the subject too.
                rf"([A-Z][\w.']*(?:\s+[\w.']+){{0,2}}\s*{marker})",
                line, re.IGNORECASE,
            )
            if match:
                institution = match.group(1).strip()
                break
        field = _field_of_study(line, institution)
        entries.append(
            Education(
                degree=level,           # type: ignore[arg-type]
                field_of_study=field,
                institution=institution,
                graduation_year=max(years) if years else 0,
            )
        )
    return entries[:5]


#: Nothing before this is a plausible professional start date on a CV.
_EARLIEST_YEAR = 1960
#: A role cannot start in the future.
_LATEST_SLACK = 1


def _experience(
    sections: dict[str, str], fallback: str = ""
) -> tuple[list[Experience], float]:
    """Roles, their bullets, and total professional years.

    Years come from the date ranges rather than any claim in the text, overlapping
    ranges are merged so two concurrent jobs are not counted twice, and impossible
    ranges are discarded rather than believed - a CV listing 1995-2035 must not
    read as forty years of experience.

    The bullets matter as much as the dates: they are the only evidence that a
    skill was ever used, as opposed to listed.
    """
    # A CV with headings like "WHERE" or "WHAT I DO" has no section we recognise.
    # Scanning the whole document for dated role lines still finds the work, and
    # losing every role over a heading style is exactly the formatting penalty an
    # ATS should not impose.
    body = sections.get("experience") or fallback
    lines = body.split(chr(10))
    entries: list[Experience] = []
    spans: list[tuple[float, float]] = []
    today = date.today().year + date.today().month / 12

    role_indices: list[int] = []
    for index, line in enumerate(lines):
        if DATE_RANGE.search(line):
            role_indices.append(index)

    for position, index in enumerate(role_indices):
        line = lines[index]
        match = DATE_RANGE.search(line)
        if match is None:
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

        # Discard what cannot be true rather than believing it.
        plausible = (
            _EARLIEST_YEAR <= start <= today + _LATEST_SLACK
            and _EARLIEST_YEAR <= end <= today + _LATEST_SLACK
            and end >= start
        )

        title = line[: match.start()].strip(" -|,\u2013\u2014\t")
        company = ""
        for separator in (" - ", " | ", " at ", " @ ", ", ", " \u2013 "):
            if separator in title:
                head, _, tail = title.partition(separator)
                title, company = head.strip(), tail.strip()
                break

        # Everything between this role and the next one is what they did in it.
        stop = role_indices[position + 1] if position + 1 < len(role_indices) else len(lines)
        highlights = [
            candidate.strip(" -\u2022\u00b7*\t")
            for candidate in lines[index + 1 : stop]
            if 8 < len(candidate.strip(" -\u2022\u00b7*\t")) < 300
        ][:6]

        internship = "intern" in line.lower()
        entries.append(
            Experience(
                title=title[:80] or "Role",
                company=company[:80],
                start=str(int(start)) if plausible else "",
                end=("present" if end >= today - 0.1 else str(int(end))) if plausible else "",
                years=round(max(0.0, end - start), 1) if plausible else 0.0,
                is_internship=internship,
                highlights=highlights,
            )
        )
        if plausible and not internship:
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

    # No recognisable headings. Judge by what the document contains instead:
    # dated roles, a degree, and named skills are what make a CV a CV, and a
    # candidate must not be discarded for using their own headings.
    signals = 0
    signals += bool(has_contact)
    signals += len(DATE_RANGE.findall(text)) >= 2
    signals += any(
        any(word in line.lower() for _, words in DEGREE_WORDS for word in words)
        for line in text.split(chr(10))
    )
    signals += len([n for n in ALIASES if mentions(text, n)]) >= 3
    if signals >= 3:
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
    experience, years = _experience(sections, fallback=text)
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

    summary_text = " ".join(
        line.strip()
        for line in sections.get("summary", "").split(chr(10))
        if line.strip()
    )[:600]

    return CandidateProfile(
        summary_text=summary_text,
        sections_found=section_order(text),
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
