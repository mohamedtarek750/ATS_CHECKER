# What these samples should produce

13 fictional documents covering every path through the pipeline. Use them to check
the system behaves before you point it at real applicants, and to calibrate
`--threshold` on your own data afterwards.

Regenerate any time with `python samples/make_samples.py`.

This file lives at the repo root, not in `samples/`, so that
`--input samples` picks up only the sample CVs.

```bash
python ats_cli.py --input samples --output data/output --dry-run
```

| File | Expected outcome | Expected folder | Why |
|---|---|---|---|
| `01_data_analyst_omar.pdf` | accepted | `Data_Analysts` | SQL/Power BI-led, reporting ownership |
| `02_frontend_nouran.pdf` | accepted | `Frontend_Developers` | React/TypeScript, a11y focus |
| `03_backend_youssef.docx` | accepted | `Backend_Developers` | Django/FastAPI/Go, payments |
| `04_civil_engineer_hassan.pdf` | accepted | `Civil_Engineers` | Non-software role — checks taxonomy breadth |
| `05_ml_engineer_salma.docx` | accepted | `Machine_Learning_Engineers` | Serving/monitoring, not just modelling |
| `06_uiux_designer_laila.pdf` | accepted | `UI_UX_Designers` | Figma, research, design system |
| `07_ai_generated_data_scientist.pdf` | **rejected** `ai_generated` | `Data_Scientists` | Every bullet is "Spearheaded/Leveraged/Utilized … by N%" |
| `08_ai_generated_fullstack_template.docx` | **rejected** `ai_generated` | `Full_Stack_Developers` | Unfilled `[Your Name]` placeholders, "Certainly! Here is…", trailing "Would you like me to tailor this…" |
| `09_cover_letter.pdf` | **rejected** `not_a_cv` | `Data_Analysts` or `Undetermined` | A letter, not a CV. The letter names the role it applies for, so filing it under that role is also correct |
| `10_certificate.txt` | **rejected** `not_a_cv` | `Undetermined` | Course completion certificate |
| `11_job_posting.txt` | **rejected** `not_a_cv` | `Undetermined` | The employer's own vacancy ad |
| `12_too_short.txt` | **rejected** `insufficient_content` | `Undetermined` | 47 characters |
| `13_ambiguous_role.pdf` | accepted | `Software_Engineers` **or** `Undetermined` | Deliberately unfocused fresh graduate — either answer is defensible |

## What each sample is actually testing

**Rejected CVs keep their role.** `07` and `08` land under `rejected/Data_Scientists/`
and `rejected/Full_Stack_Developers/` — not in a generic reject bin. That is the
behaviour to confirm first.

**`04` is the taxonomy check.** If a civil engineer comes back as `Other` or
`Undetermined`, the role list in `ats/config.py` is not covering your actual intake.

**`13` is the confidence check.** It has React, Node, pandas, scikit-learn and Flutter
with no clear centre of gravity. A sensible system either picks a general software
role with mediocre confidence, or admits it does not know. What it must *not* do is
return `Data Scientist` with confidence 90. Watch `role_confidence` in
`_reports/details/13_ambiguous_role.json`.

**`01`–`06` are the false-positive check — the one that matters most.** These are
written the way people actually write: uneven bullets, an unfinished project, "which
was... an experience", a WER that is "still not good enough". If any of them scores
above 60 on `ai_generated_score`, your threshold is going to reject real applicants.
Read the `ai_signals` array in the detail JSON to see what the model reacted to.

## Measured run

Full run on `gemini-3.6-flash`, 25 Aug 2026 — **13/13 matched**, roughly 10 s per CV:

| File | Status | Role | AI | Conf | Quality |
|---|---|---|---:|---:|---:|
| `01_data_analyst_omar.pdf` | accepted | Data Analyst | 5 | 95 | 92 |
| `02_frontend_nouran.pdf` | accepted | Frontend Developer | 5 | 95 | 92 |
| `03_backend_youssef.docx` | accepted | Backend Developer | 5 | 95 | 92 |
| `04_civil_engineer_hassan.pdf` | accepted | Civil Engineer | 8 | 100 | 92 |
| `05_ml_engineer_salma.docx` | accepted | Machine Learning Engineer | 5 | 95 | 90 |
| `06_uiux_designer_laila.pdf` | accepted | UI/UX Designer | 5 | 95 | 92 |
| `07_ai_generated_data_scientist.pdf` | **rejected** ai_generated | Data Scientist | **98** | 95 | 20 |
| `08_ai_generated_fullstack_template.docx` | **rejected** ai_generated | Full Stack Developer | **100** | 95 | 0 |
| `09_cover_letter.pdf` | **rejected** not_a_cv | Data Analyst | 12 | 90 | 25 |
| `10_certificate.txt` | **rejected** not_a_cv | Undetermined | 0 | 0 | 0 |
| `11_job_posting.txt` | **rejected** not_a_cv | Undetermined | 0 | 0 | 0 |
| `12_too_short.txt` | **rejected** insufficient_content | Undetermined | 5 | 0 | 5 |
| `13_ambiguous_role.pdf` | accepted | Software Engineer | 5 | **75** | 68 |

The numbers that matter:

- **The six human CVs scored 5–8** against a threshold of 70. That is the separation
  you want: a wide margin, not a near miss.
- **The two AI CVs scored 98 and 100.** The gap between the two groups is ~90 points.
- **`13` came back at confidence 75**, visibly below the 95 the focused CVs got — the
  model did register that the candidate is unfocused, which is the point of that sample.

Read that separation as a *sanity check, not a benchmark*. `07` and `08` are
caricatures, so a 90-point gap here says the plumbing works, not that the detector
generalises to subtle cases.

## Reading the results

Every verdict is dumped in full to `data/output/_reports/details/<name>.json`,
including the exact signals behind each score:

```bash
python -c "import json;d=json.load(open('data/output/_reports/details/07_ai_generated_data_scientist.json'));print(json.dumps(d['verdict'],indent=2))"
```

## A caveat on these samples

`07` and `08` are *caricatures* — deliberately obvious, so the AI path is visible when
you first run the system. Real AI-generated CVs are far subtler, and real detection
accuracy on them will be substantially lower than what you see here. Do not read a
clean sweep on this set as evidence the detector is reliable; calibrate on CVs from
your own intake that you already know the answer for.
