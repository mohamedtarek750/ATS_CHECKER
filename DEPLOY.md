# Deploying to Vercel

The web app is a Next.js frontend plus one Python serverless function that reuses
the existing `ats` package.

```
app/  components/  lib/    Next.js frontend (React, TypeScript, Tailwind)
package.json  next.config.mjs
api/index.py            FastAPI serverless function
vercel.json             function config + routing
```

The Next app lives at the **repository root**, next to the Python package. That is
Vercel's zero-config layout: it detects Next.js from the root `package.json` and
serves `api/*.py` as Python functions alongside it, with no custom build command to
get out of step with the project's settings.

## Deploy

```bash
npm i -g vercel
vercel
```

Vercel detects Next.js at the root, builds it, and publishes `api/index.py` on
`/api/*`. Nothing else to configure — **the app works with no API key at all**,
using the rules-based reader.

> **If you already created a project when the app lived in `web/`:** set
> **Settings → Build and Deployment → Root Directory** back to empty (the
> repository root) and redeploy. A root directory of `web` now points at a folder
> that no longer exists, and the build fails before it starts.

To enable the "paste a job description" step, add one environment variable in
**Project → Settings → Environment Variables**:

```
GEMINI_API_KEY = AIza...
ATS_PROVIDER   = gemini
```

Redeploy, and reading an advert starts working. Without it, the reference-CV route
still does, because deriving requirements from a parsed CV needs no model.

## Running it locally

Two processes: the API and the frontend.

```bash
ATS_PROVIDER=offline python -m uvicorn api.index:app --port 8000
```
```bash
npm run dev
```

`next.config.mjs` proxies `/api/*` to `127.0.0.1:8000` in development only; in
production Vercel routes it, so no proxy is involved.

---

## Why it is shaped this way

Serverless imposed three things, and each of them turned out to be the right call
anyway.

**One CV per request.** Reading a hundred in a single call would exceed the function
timeout, so the browser sends them one at a time. The user sees each row resolve as
it lands instead of staring at a spinner, and a failure affects one CV rather than
the batch.

**No server-side storage.** A serverless filesystem does not survive between
invocations. Parsed profiles are therefore returned to the browser and kept in the
page for the session — which also means applicants' CVs are not accumulating in a
database nobody asked for. Closing the tab ends it.

**Matching had to be cheap.** Stages 4 and 5 involve no model call, so ranking the
whole pool is one fast request. Changing the job description and re-matching costs
nothing, which is what makes the reference-CV filter usable at all.

## Limits worth knowing

| | |
|---|---|
| Function timeout | 60s configured; Hobby plans cap at 60s, so one CV per call |
| Upload size | 8 MB per file, enforced in the API |
| Reading an advert | needs `GEMINI_API_KEY`; everything else runs without one |
| Session | results live in the tab. Refreshing clears them |

For a large intake — hundreds or thousands — run `hr_cli.py` locally instead. It
stores to SQLite, resumes after an interruption, and is not bounded by a function
timeout. The web app is for a recruiter working through one vacancy.

## Privacy

With `ATS_PROVIDER=offline` no CV content leaves the server that parsed it, and
nothing is written to disk. With `gemini` the CV text is sent to Google, whose free
tier may use submitted content to improve their models — that is a decision to make
deliberately when the content is other people's personal data.

The deployment is public by default. Vercel offers password protection under
**Settings → Deployment Protection**; a recruiting tool holding real applications
should have it on.
