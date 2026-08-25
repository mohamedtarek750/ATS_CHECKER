# ACUD ATS Checker

An Applicant Tracking System that reads every incoming CV with Claude, works out
**which role the candidate is applying for**, rejects anything that is not a real
human-written CV, and files each file into a folder named after its role.

```
data/output/
├── accepted/
│   ├── Data_Scientists/
│   ├── Data_Analysts/
│   ├── Frontend_Developers/
│   └── ...
├── rejected/
│   ├── Data_Scientists/      <- looked like a Data Scientist CV, but AI-generated
│   ├── Undetermined/         <- not a CV at all: invoices, cover letters, junk
│   └── ...
├── _unscreened/              <- never reached Claude. NOT rejections - re-run these
└── _reports/
    ├── report_20260825_121500.csv
    ├── report_20260825_121500.json
    └── details/<cv-name>.json
```

Both `accepted/` and `rejected/` are split by role, so a rejected frontend CV still
lands under `rejected/Frontend_Developers/`.

---

## Quick start

```bash
pip install -r requirements.txt
```

> **Windows, several Pythons installed?** The `streamlit` command belongs to whichever
> interpreter installed it, which is not always the one `python` resolves to — that
> mismatch shows up as `ModuleNotFoundError: No module named 'anthropic'` inside the
> app. Install into the interpreter Streamlit actually runs on, or sidestep it with
> `python -m streamlit run app.py`. To see which one that is:
> `python -c "import sys; print(sys.executable)"` vs `where streamlit`.

Put your key in a `.env` file next to this README (copy `.env.example`):

```
ANTHROPIC_API_KEY=sk-ant-...
```

### Web UI

```bash
streamlit run app.py
```

Drag CVs in, or point it at a folder. You get a live log, per-CV detail (scores,
AI signals, extracted contact info) and a downloadable CSV.

### Command line

```bash
python ats_cli.py --input data/inbox
```

```bash
python ats_cli.py --input "D:/CVs" --output "D:/screened" --move --threshold 60
```

| Flag | Meaning |
|---|---|
| `-i, --input` | Folder (searched recursively) or a single file. |
| `-o, --output` | Where `accepted/` and `rejected/` are created. |
| `--move` | Move originals instead of copying them. |
| `--dry-run` | Screen and report, but file nothing. |
| `--threshold N` | Reject at AI score ≥ N (default 70). |
| `--workers N` | Parallel screenings (default 4). |
| `--model` | Claude model id (default `claude-opus-5`). |
| `--scaffold` | Pre-create an empty folder for every role in the taxonomy. |

Supported inputs: `.pdf`, `.docx`, `.txt`, `.md`, `.rtf`. A scanned PDF with no text
layer is sent to Claude as a document so it can still be read.

---

## Try it on the sample CVs

13 fictional documents ship with the project — six genuine CVs across different roles,
two written in an unmistakably LLM register, three that are not CVs at all, and two
edge cases:

```bash
python samples/make_samples.py
```

```bash
python ats_cli.py --input samples --output data/output --dry-run
```

`SAMPLES.md` lists the outcome each file should produce and what it is
testing. Note that the two AI-generated samples are deliberate caricatures — real
ones are much subtler, so a clean sweep here is not evidence the detector is
reliable.

---

## How a CV is judged

Each file goes through five stages:

1. **Extract** — text plus the file's embedded metadata (`ats/extract.py`).
2. **Classify** — one Claude call returns a structured `Verdict` (`ats/schema.py`):
   document type, role family, specialization, seniority, contact details, an
   AI-generation score, a format score and a quality score.
3. **Decide** — plain Python applies the accept/reject rules (`ats/decision.py`).
4. **Route** — the file is copied or moved into its folder (`ats/router.py`).
5. **Report** — CSV + JSON, plus a full per-CV JSON under `_reports/details/`.

**The LLM scores; Python decides.** The accept/reject rules live in
`ats/decision.py`, not in the prompt, so they are auditable and you can change a
threshold without re-tuning any wording.

### Rejection reasons

| Reason | When |
|---|---|
| `not_a_cv` | Cover letter, certificate, invoice, screenshot, job posting… |
| `ai_generated` | AI score ≥ threshold. |
| `unreadable` | Encrypted, corrupt, empty, or an unsupported file type. |
| `insufficient_content` | A CV, but under ~250 characters of usable text. |

A CV whose role cannot be pinned down confidently (`role_confidence` below
`--min-role-confidence`, default 40) is **still accepted** but filed under
`Undetermined/` rather than being guessed into the wrong folder.

### Failures are not rejections

If a CV never reaches Claude — no API key, rate limit, network drop — it gets
status `error`, reason `screening_failed`, and is held in `_unscreened/`. It is
**never** written into `rejected/`, because nothing was judged: filing it there
would record a decision against a candidate that nobody ever made. Fix the cause
and re-run those files.

Both entry points check credentials *before* screening starts, so a missing key
fails once with a clear message instead of turning a batch of 200 CVs into 200
failure records. The CLI exits `2` for a blocked run and `3` when some files ended
up unscreened.

Account-level failures that would hit every CV identically — no credits, a rejected
key, a model the account cannot use — raise `FatalScreeningError` and **stop the
whole run on the first one**. The remaining files are marked unscreened without
spending an API call each.

To retry after fixing the cause, just point the input at the holding folder:

```bash
python ats_cli.py --input data/output/_unscreened
```

---

## Tuning

Everything is settable by env var (see `.env.example`) or from the Streamlit
sidebar:

| Variable | Default | Purpose |
|---|---|---|
| `ATS_MODEL` | `claude-opus-5` | Model used for screening. |
| `ATS_EFFORT` | `medium` | Reasoning effort: `low`…`max`. |
| `ATS_AI_THRESHOLD` | `70` | AI score at which a CV is rejected. |
| `ATS_MIN_ROLE_CONFIDENCE` | `40` | Below this → `Undetermined/`. |
| `ATS_MIN_CHARS` | `250` | Below this → `insufficient_content`. |
| `ATS_FILE_ACTION` | `copy` | `copy` or `move`. |
| `ATS_MAX_WORKERS` | `4` | Parallel screenings. |

Add or rename roles in `ROLE_TAXONOMY` in `ats/config.py` — `label` is what Claude
picks from, `folder` is the directory it creates. A genuine role that is not in the
list comes back as `Other` with a `custom_role_title`, and gets its own folder.

---

## About the AI-generation check — read this

AI-detection is **probabilistic, and no detector is reliable enough to be the sole
basis for rejecting a real applicant.** This one is built to fail in the safer
direction, but you should know exactly what it does:

- It scores the **substance** of the CV, not its polish. A beautiful Canva template
  is not a signal. Neither is non-native English — the prompt explicitly rules both
  out, because both would otherwise penalise exactly the candidates who deserve it
  least.
- A CV whose real experience was *reworded* with AI help is not the target. A CV
  whose experience was *invented* is.
- Ambiguous cases are instructed to land in the 40–59 band, below the default
  threshold of 70, so **uncertainty results in acceptance.**
- File metadata (producer, timestamps) is passed as *weak corroborating* evidence
  only, never as a reason on its own. The CV that this project was built against is
  a genuine human CV that was exported through `python-docx` — metadata alone would
  have wrongly flagged it.

Recommended practice: run with `--dry-run` first, read `_reports/details/*.json`
(every verdict lists the exact signals it reacted to), calibrate the threshold on
CVs you already know, and treat `rejected/…/ai_generated` as a review queue rather
than a bin.

---

## Cost

One Claude call per CV. The system prompt (~2k tokens) is cached, so from the second
CV onward you mostly pay for the CV text itself and a short structured response.
Switch `ATS_MODEL` to `claude-sonnet-5` or `claude-haiku-4-5` for high-volume runs —
they are cheaper, and less reliable at the AI-generation judgement specifically.

---

## Tests

```bash
python tests/test_pipeline.py
```

Covers extraction, every rejection rule, folder routing, `copy` vs `move`, and a
full stubbed end-to-end run. No API key needed — Claude is stubbed.

```bash
python tests/test_request_shape.py
```

Runs the real SDK against a mock HTTP transport to confirm the request we build is
well-formed (adaptive thinking, cached system prompt, JSON-schema output, the role
enum) and that the verdict parses back. Also no API key needed.

> The offline suites are green. The **live** Claude path has not been exercised in
> this repository because no API key was available when it was written — run
> `python ats_cli.py --input tests/fixtures --dry-run` once with a real key as your
> first smoke test.

The fixture CVs are synthetic. `tests/make_fixture_pdf.py` regenerates the sample
PDF if you need to change it. Do not commit real applicants' CVs to this repo —
`data/` is gitignored for that reason.

---

## Layout

```
ats/
  config.py      role taxonomy, thresholds, paths
  extract.py     PDF/DOCX/text extraction + file forensics
  prompts.py     the screening prompt: CV standard, AI rubric, role rules
  schema.py      the Verdict model Claude must fill in
  classifier.py  the Claude call
  decision.py    accept/reject policy
  router.py      filesystem placement
  pipeline.py    orchestration, concurrency, reporting
app.py           Streamlit UI
ats_cli.py       command line
```
