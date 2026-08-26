# ACUD ATS Checker

An Applicant Tracking System that reads every incoming CV with an LLM, works out
**which role the candidate is applying for**, rejects anything that is not a real
human-written CV, and files each file into a folder named after its role.

Runs on **Google Gemini's free tier** by default, or on Anthropic Claude if you
have credits. Only `ats/providers/` knows which — everything else is shared.

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

### Get a key

**Free (default) — Google Gemini.** Go to **aistudio.google.com/apikey**, sign in
with a Google account, **Create API key**. No card, no billing setup.

Copy `.env.example` to `.env` and fill it in:

```
ATS_PROVIDER=gemini
GEMINI_API_KEY=AIza...
```

Google retires models to new keys without warning, which shows up as a 404. If that
happens, ask your own key what it can run:

```bash
python ats_cli.py --list-models
```

**Paid — Anthropic Claude.** A key from console.anthropic.com plus credits on the
account. Stronger at the AI-generation judgement, which is the hardest call the
system makes.

```
ATS_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...
```

Switch any time with `--provider gemini|claude`, the sidebar dropdown, or
`ATS_PROVIDER` in `.env`.

> **Before you point the free tier at real applicants:** Google's free tier may use
> submitted content to improve their models. Real CVs are other people's personal
> data, and that is a decision to make deliberately, not by default. Use the samples
> below to develop and calibrate, and a paid tier (either vendor) for live intake.

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
| `--workers N` | Parallel screenings (default 2 on Gemini, 4 on Claude). |
| `--provider` | `gemini` (free) or `claude` (paid). |
| `--model` | Model id. Blank uses the provider's default. |
| `--scaffold` | Pre-create an empty folder for every role in the taxonomy. |

Supported inputs: `.pdf`, `.docx`, `.txt`, `.md`, `.rtf`. A scanned PDF with no text
layer is sent to Claude as a document so it can still be read.

---

## Deploying to Streamlit Cloud

`.env` is gitignored, so a deployed app has no key. Streamlit Cloud reads them from
its own secrets store instead:

**Manage app → Settings → Secrets**, then paste:

```toml
GEMINI_API_KEY = "AIza..."
APP_PASSWORD = "pick-something-long"
```

Save, and the app restarts with the key available. `.streamlit/secrets.toml.example`
has the full template.

Three things to know before you put this on a public URL:

- **The disk is wiped on every restart.** Streamlit Cloud gives each app ephemeral
  storage, so `accepted/` and `rejected/` do not survive the app sleeping. The
  folder-sorting output is effectively lost — use the **Download report (CSV)**
  button, which is the durable output on a cloud deployment. If you need the folder
  tree, run the CLI locally.
- **A Streamlit Cloud URL is public by default.** Anyone with the link can upload
  CVs and spend your API quota. Set `APP_PASSWORD` in secrets to gate it — the app
  requires it when present, and skips the gate when absent.
- **Uploaded CVs land on Streamlit's servers.** Combined with a free-tier LLM that
  may train on submitted content, that is two third parties holding applicants'
  personal data. For real intake, run it locally or get that cleared first.

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

## Measuring accuracy

You cannot tell whether a screener is accurate by reading its output — you need
labelled CVs and a score.

```bash
python eval/run_eval.py
```

`eval/labels.json` holds the ground truth: expected decision, reason, and a list of
acceptable roles per CV. The harness reports decision accuracy, role accuracy, and —
the number that decides whether this is safe to deploy — the **separation between AI
scores on human CVs and on AI CVs**. If any genuine CV scores at or above the
threshold, it says so loudly, because that means real applicants get rejected.

```bash
python eval/run_eval.py --repeat 3
```

### Tuning thresholds on a finished run

A run already recorded every score, so you can test other settings without
spending a single API call:

```bash
python eval/tune.py
```

Sweeps the AI threshold and the quality bar over the last report and shows how many
CVs each setting rejects. Then see exactly who a setting drops, by name:

```bash
python eval/tune.py --threshold 70 --min-quality 85
```

Do this before changing a threshold in production. "Reject more" is easy to ask for
and hard to picture — this shows you the actual list of people it removes.

Screens each CV three times and reports how often the verdict changes. A system that
answers differently to the same CV is not a screening tool, whatever its average
accuracy is.

**The bundled 13 samples are not a benchmark.** They prove the pipeline works. To
know whether it is accurate on *your* applicants, add 30+ CVs from your own intake to
`eval/labels.json`, labelled by someone who knows the answer — especially real
AI-written ones, which are far subtler than the two synthetic samples here.

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
| `poor_structure` | No headings, no dates, a wall of text, image-only — the information cannot be extracted. |
| `unprofessional` | Inappropriate register or presentation, with the evidence named. |
| `low_quality` | A readable, professional CV with nothing concrete behind its claims. |

The last three fire only when you configure a bar for them. All are off by default.

### The quality bars (optional, off by default)

```bash
python ats_cli.py --input data/inbox --strict
```
```bash
python ats_cli.py --input data/inbox --min-format 70 --min-professionalism 70 --min-quality 60
```

Each bar rejects under its **own reason**, so `rejected/` tells you why:

| Bar | Reason | What it actually catches |
|---|---|---|
| `--min-format` | `poor_structure` | No headings, no dates, a wall of text, content trapped in an image, a layout that scrambles when parsed |
| `--min-professionalism` | `unprofessional` | A joke email address, slang, emoji bullets, oversharing, pervasive typos, a placeholder left in |
| `--min-quality` | `low_quality` | Claims with no evidence behind them |
| `--require` | `poor_structure` | A named section genuinely absent |

**What these deliberately do not catch:** a template you did not pick. The prompt
rules out, explicitly and by name, deducting for non-native English, a photo or date
of birth (normal on CVs in Egypt and the region), a plain or free template, a modest
university, an employment gap, or a personal Gmail address. Those correlate with
where someone is from and what they could afford, not with whether they can do the
job. A designer's two-column CV with real work passes; a beautiful one with nothing
in it does not.

When several bars fail at once the most specific wins — structure first, since a CV
nobody can read cannot be judged on anything else — and the others are appended to
the explanation rather than dropped.

Two things worth knowing before you turn it on:

- **Requiring `experience` rejects every student and fresh graduate**, including the
  CV this project was calibrated on. The UI warns you if you select it.
- **Measure the bar before you deploy it.** `python eval/run_eval.py --strict`
  prints exactly which labelled CVs the bar drops and flags the ones that are
  genuine human applicants. On the bundled samples, `--strict` drops one file, and
  it is a 47-character stub — zero real CVs. Set the bar much higher and that stops
  being true: the genuine samples score 85–95 on structure and 85–95 on content, so
  a bar above ~85 starts rejecting real people.

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
| `ATS_PROVIDER` | `gemini` | `gemini` (free) or `claude` (paid). |
| `ATS_MODEL` | per provider | `gemini-3.6-flash` / `claude-opus-5`. |
| `ATS_GEMINI_RPM` | `10` | Free-tier requests per minute to stay under. |
| `ATS_EFFORT` | `medium` | Claude only: reasoning effort `low`…`max`. |
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

One LLM call per CV.

**Gemini free tier** costs nothing. The limits are per-minute and per-day rather
than per-token, so the pipeline paces itself: `ATS_GEMINI_RPM` (default 10) spaces
requests out, 429s are retried with backoff, and a spent *daily* quota stops the run
rather than burning through the rest of the batch. Re-run the held files after the
quota resets at midnight Pacific.

**Claude** is paid. The system prompt (~2k tokens) is cached, so from the second CV
onward you mostly pay for the CV text and a short structured response. `claude-sonnet-5`
and `claude-haiku-4-5` are cheaper, and less reliable at the AI-generation call
specifically.

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

Runs the real Anthropic SDK against a mock HTTP transport to confirm the request we
build is well-formed (adaptive thinking, cached system prompt, JSON-schema output,
the role enum) and that the verdict parses back.

```bash
python tests/test_gemini.py
```

Confirms the `Verdict` schema survives conversion to Gemini's format with all 36
role enum values intact, that account-level errors are recognised as fatal while a
per-minute burst is not, and that the rate limiter really spaces requests out.

None of the three need an API key.

> The offline suites are green, and the **Gemini** path has been exercised live:
> a full 13-sample run on `gemini-3.6-flash` matched every expected outcome
> (`SAMPLES.md`). The **Claude** path is covered only by the mock-transport test —
> no credits were available to run it end to end.

The fixture CVs are synthetic. `tests/make_fixture_pdf.py` regenerates the sample
PDF if you need to change it. Do not commit real applicants' CVs to this repo —
`data/` is gitignored for that reason.

---

## Layout

```
ats/
  config.py      role taxonomy, thresholds, paths, provider defaults
  extract.py     PDF/DOCX/text extraction + file forensics
  prompts.py     the screening prompt: CV standard, AI rubric, role rules
  schema.py      the Verdict model Claude must fill in
  classifier.py  dispatches to the configured provider
  providers/     base.py (contract + rate limiter), gemini.py, claude.py
  decision.py    accept/reject policy
  router.py      filesystem placement
  pipeline.py    orchestration, concurrency, reporting
app.py           Streamlit UI
ats_cli.py       command line
```
