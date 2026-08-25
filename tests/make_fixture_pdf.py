"""Generate the synthetic PDF fixture used by the test suite.

Writes a minimal, dependency-free PDF with a real text layer so `pypdf` can extract
it. The candidate is fictional - no real applicant data belongs in this repository.

    python tests/make_fixture_pdf.py
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent / "fixtures" / "sample_human_cv.pdf"

LINES = [
    ("MARIAM A. FATHY", 16),
    ("Cairo, Egypt | +20 100 555 0142 | mariam.fathy.dev@example.com", 9),
    ("", 9),
    ("PROFESSIONAL SUMMARY", 11),
    ("Third-year Data Science student. Comfortable with Python and SQL, still", 9),
    ("learning Spark. Interned twice, once in a bank IT team and once writing", 9),
    ("reports for a logistics company.", 9),
    ("", 9),
    ("EDUCATION", 11),
    ("BSc Data Science and AI - Elsewedy University of Technology, expected 2027", 9),
    ("Coursework: Data Mining, Probability and Statistics, Data Structures,", 9),
    ("Cloud Databases, Object-Oriented Programming", 9),
    ("", 9),
    ("WORK EXPERIENCE", 11),
    ("Data Analyst Intern - Nile Logistics (Jul 2025 - Sep 2025)", 9),
    ("- Rebuilt the weekly delivery report in SQL; it used to be copy-pasted", 9),
    ("  from four spreadsheets every Sunday.", 9),
    ("- Cleaned the driver dataset. Roughly 8% of rows had swapped columns.", 9),
    ("- Sat in on the ops meeting and took notes.", 9),
    ("", 9),
    ("IT Intern - MIDBANK (Aug 2024 - Sep 2024)", 9),
    ("- Helped the support team with ticket triage and password resets.", 9),
    ("- Documented the onboarding checklist nobody had written down.", 9),
    ("", 9),
    ("PROJECTS", 11),
    ("Retail RFM segmentation - Python, pandas, scikit-learn", 9),
    ("  K-Means on 1.2M transactions. Elbow plot was ambiguous so I used", 9),
    ("  silhouette score instead. Streamlit dashboard on top.", 9),
    ("Campus energy predictor - Python, scikit-learn (unfinished)", 9),
    ("  Linear regression baseline works, the seasonal features do not yet.", 9),
    ("", 9),
    ("TECHNICAL SKILLS", 11),
    ("Programming: Python, SQL, a little Java", 9),
    ("Data: pandas, NumPy, scikit-learn, matplotlib, Power BI basics", 9),
    ("Tools: Git, VS Code, MySQL, Jupyter", 9),
    ("", 9),
    ("CERTIFICATIONS AND LANGUAGES", 11),
    ("Google Data Analytics Certificate (Nov 2025)", 9),
    ("Arabic (native), English (upper intermediate)", 9),
]


def build_content_stream() -> bytes:
    parts = ["BT", "/F1 9 Tf", "1 0 0 1 56 780 Tm", "13 TL"]
    for text, size in LINES:
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        parts.append(f"/F1 {size} Tf")
        parts.append(f"({escaped}) Tj")
        parts.append("T*")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def build_pdf() -> bytes:
    content = build_content_stream()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(build_pdf())
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
