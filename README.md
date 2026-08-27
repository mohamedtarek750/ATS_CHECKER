# ACUD ATS

An applicant tracking system that reads each CV **once**, then shortlists that pool
against any vacancy — instantly, and without another API call.

```
1  parse       file            ->  text + file forensics          no model
2  normalize   text            ->  CandidateProfile, stored       model, once per CV
3  jobspec     job advert      ->  reviewable checklist, stored   model, once per job
4  match       profile x job   ->  per-requirement result          no model
5  rank        matches         ->  ordered shortlist with tiers    no model
```

Only stages 2 and 3 cost anything, and stage 2 runs once per document for the
lifetime of that document. Re-screening 2000 stored candidates against a new job
takes **under a second and zero API calls** — which is what makes a pool of
thousands, and many vacancies, practical.

---

## Two front ends

**The web app** (`web/` + `api/`) — a Next.js interface deployed on Vercel. Add CVs,
paste a job description *or* point at a reference CV, and get a ranked list with a
match percentage and the reason behind every result. See `DEPLOY.md`.

```bash
vercel
```

**The command line** (`hr_cli.py`) — for a large intake. Stores to SQLite, resumes
after an interruption, and is not bounded by a serverless timeout.

There is also `app_legacy.py`, the earlier Streamlit interface, kept working.

---

## Quick start

```bash
pip install -r requirements-local.txt
```

Get a free key at **aistudio.google.com/apikey**, copy `.env.example` to `.env`:

```
ATS_PROVIDER=gemini
GEMINI_API_KEY=AIza...
```

### The app

```bash
streamlit run app.py
```

Three tabs, in the order a recruiter works: **CVs → Jobs → Shortlist**.

### The command line

```bash
python hr_cli.py intake --input data/inbox
```
```bash
python hr_cli.py job --from job_ad.txt
```
```bash
python hr_cli.py shortlist --job Data_Analyst
```
```bash
python hr_cli.py pool
```

Useful flags on `shortlist`: `--verbose` shows every requirement and its evidence,
`--all` includes non-matches, `--csv out.csv` writes the full ranking.

> **Windows with several Pythons?** The `streamlit` command belongs to whichever
> interpreter installed it, which may not be the one `python` resolves to — that
> mismatch appears as `ModuleNotFoundError`. Use `python -m streamlit run app.py`,
> or compare `python -c "import sys; print(sys.executable)"` with `where streamlit`.

---

## What a recruiter sees

No scores, and no sliders. For each candidate: which requirements they meet, and
the words from their own CV that show it.

```
Shortlist  |  Omar H. Abdelrahman  |  7/7 must-haves

  + Bachelor in Statistics, CS or related   Met     - bachelor in Statistics
  + 2 years in a data or reporting role     Met     - 3 years of professional experience
  + Strong SQL                              Met     - skills: SQL
  + Power BI or Tableau                     Met     - skills: Power BI
  + Written English                         Met     - English (fluent)
  - Azure or Databricks                     Not found
  + PL-300 certification                    Met     - Microsoft PL-300 Power BI Data Analyst
```

A rejected candidate who asks why gets a real answer, and the employer can stand
behind it.

Each candidate also carries a **match percentage** — a plain weighted ratio of the
requirements they meet, with must-haves carrying most of it and a near miss counting
half. Every point is traceable to a named requirement, which is the only kind of
percentage worth putting next to a person's name.

### Filtering by a reference CV

Instead of writing a checklist you can hand it one CV: *find me more like this*.
The requirements are derived from what that CV **demonstrates** — skills, degree
level, years — and never from its university, employer, or the language it was
written in. Those track where someone came from rather than what they can do, and
"find me people like this one" is exactly where that goes wrong.

Only the top few skills become must-haves; the rest rank. A reference CV is an
example, not a specification.

### The four outcomes

| Tier | When |
|---|---|
| **Shortlist** | Every must-have met. |
| **Worth a look** | One short, or close — 2.5 years against 3, a related-but-unlisted degree. A person should decide, not the system. |
| **Not a match** | Several must-haves genuinely absent. |
| **Not a CV** | A cover letter, certificate, invoice, job advert. |

---

## Decisions worth knowing about

**The weights are fixed in code.** `ats/stages/rank.py` holds them and nothing
exposes them as a dial. Nudging a weight silently reorders real applicants and
nobody reviews who moved down; a recruiter should be reading requirements, not
tuning a scoring function.

**Nice-to-haves never cause a rejection.** They only separate candidates who
already clear the bar. That is what "preferred" means, and an advert that says
"preferred" has made a promise.

**Ambiguous wording in an advert becomes a nice-to-have, not a must-have.** Both
the CLI and the UI then make you confirm each must-have before any CV is screened,
because a wrongly promoted requirement filters people out and nobody sees who.

**A suspected AI-written CV is flagged, never rejected.** It is marked in the list
and keeps the tier it earned. The detection is probabilistic and the cost of a
false positive is borne by a real applicant, so a human makes that call.

**Skills are normalized before matching.** `MS SQL Server`, `T-SQL` and `SQL` are
the same thing; `PowerBI` and `Power BI` are the same thing. Without that, matching
is string comparison, and the people it fails are the ones who did not copy a
template's exact wording. The table lives in `ats/skills.py` — add your own.

**A skill used in a project counts as much as one in a skills section.** Candidates
who do not pad their skills list are not penalised for it.

**Short skill names are word-boundary matched**, so `R` does not fire on `React`
and `Go` does not fire on `Google`. A single generic word is only matched when it
is a recognised skill name, so `Power BI` is not satisfied by `Power Query`.

---

## How CVs get read

Stage 2 is the only per-CV cost, and you choose what pays it. This is a cost and
privacy decision, not a quality dial.

| `ATS_PROVIDER` | Speed | Limit | Data leaves the machine |
|---|---|---|---|
| **`offline`** | ~15 CVs/second | none | **no** |
| `ollama` | ~1 CV/minute on a CPU | none | **no** |
| `gemini` | ~5 CVs/minute | ~20/day free | yes |
| `claude` | ~5 CVs/minute | paid, no daily cap | yes |

```bash
python hr_cli.py intake --provider offline --input data/inbox
```

**`offline` uses no model at all** — regex, section detection, and the skills table.
It reads a thousand CVs in about a minute, needs no key, and cannot be stopped by a
quota. It is weaker than a model on unusual layouts and it does not attempt the
AI-written check at all (rules cannot judge prose, and reporting a number there
would be inventing one). What it does get is exactly what stages 4 and 5 consume:
contact details, dates, degrees, and the skills vocabulary — which is dictionary
lookup rather than comprehension.

**`ollama` runs a real model on your own machine.** No key, no quota, nothing sent
anywhere. Install Ollama, `ollama pull qwen3:4b`, and set `ATS_PROVIDER=ollama`. On
a CPU expect around a minute per CV, so it suits an overnight batch.

> **A note on "let's train our own model."** Don't. Training one from scratch is
> months of work and serious hardware, to end up well behind a model you can
> download today. If the goal is "no API and no quota", `offline` and `ollama` both
> get you there this afternoon.

**A practical shape for a large intake:** run everything through `offline`, shortlist,
then re-read only the top candidates with a model — `hr_cli.py pool --forget` is not
needed, since re-reading a CV with a better provider simply updates its record.

---

## Scale

| | |
|---|---|
| Reading a CV (stage 2) | ~12 s, once per document, ever |
| Ranking 2000 stored candidates (stages 4-5) | **0.96 s**, no API calls |
| A second vacancy over the same pool | free |

Intake is the only slow part, and it resumes: every candidate is stored as it is
read, so an interrupted batch keeps everything it finished and re-running costs
only the remainder.

**On the free tier the daily quota is the real ceiling** — around 20 requests per
model per day, with failover across four models. A thousand CVs in one day is not
possible on it, whatever the software does. Run intake daily and the pool
accumulates, or move to a paid tier (roughly 4000 tokens per CV) where the cap
disappears.

**Over ~60 CVs, use the terminal.** Streamlit ends the script if the browser tab
sleeps. Nothing is lost when it does, but the terminal simply does not have the
problem, and the app says so and prints the command.

---

## Layout

```
ats/
  models.py      CandidateProfile - the normalized record everything reads
  store.py       SQLite pool, keyed by CV content so re-uploads are free
  skills.py      skill aliases; the difference between matching and string compare
  stages/
    parse.py     1. file -> text
    normalize.py 2. text -> CandidateProfile          (the only per-CV model call)
    jobspec.py   3. advert -> checklist
    match.py     4. profile x job -> requirements     (deterministic)
    rank.py      5. matches -> tiers                  (fixed weights, in code)
  screening.py   intake() and shortlist() - the two things the app actually calls
  providers/     gemini.py, claude.py, behind one interface
app.py           the recruiter app
hr_cli.py        the same five stages from a terminal
```

`app_legacy.py`, `ats_cli.py` and `jd_cli.py` keep the earlier role-sorting and
folder-filing modes working, documented in `README_legacy.md`. They are unchanged
and still pass their tests.

---

## Tests

```bash
python tests/test_stages.py
```
```bash
python tests/test_resume.py
```
```bash
python tests/test_job_match.py
```
```bash
python tests/test_pipeline.py
```
```bash
python tests/test_gemini.py
```
```bash
python tests/test_request_shape.py
```

All six run offline against stubbed providers — no API key needed.

---

## Providers

| | |
|---|---|
| `ATS_PROVIDER=offline` | No model. Instant, unlimited, private. The right default at volume. |
| `ATS_PROVIDER=ollama` | A model on this machine. Unlimited and private, about a minute per CV on a CPU. |
| `ATS_PROVIDER=gemini` | Free tier. `gemini-3.6-flash` by default, failing over across models as daily quotas run out. |
| `ATS_PROVIDER=claude` | Paid. Stronger on the AI-generation judgement specifically. |

`python ats_cli.py --list-models` asks your key what it can actually run — Google
retires models to new keys without warning, which surfaces as a 404.

> Google's free tier may use submitted content to improve their models. Real CVs
> are other people's personal data. Use the samples to develop, and a paid tier for
> live intake.
