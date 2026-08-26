"""ACUD ATS — the recruiter-facing app.

Three things a recruiter does, in the order they do them:

    1. Add CVs      files in, read once, kept in the pool
    2. Add a job    paste the advert, check the requirements
    3. Shortlist    ranked candidates with the reasons behind each one

There are no score sliders here. Thresholds and weights live in code, because
nudging one silently reorders real applicants and nobody reviews who moved down.
What a recruiter sees is which requirements a person meets, and the words from
their own CV that show it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from ats import screening, store
from ats.config import Settings
from ats.pipeline import preflight
from ats.providers import ClassificationError
from ats.router import clear_files
from ats.stages import jobspec, parse, rank

st.set_page_config(page_title="ACUD ATS", layout="wide")

STATUS_STYLE = {
    "met": ("✓", "Met"),
    "partial": ("~", "Close"),
    "unclear": ("?", "Needs a look"),
    "not_met": ("✗", "Not found"),
}


def load_secrets() -> None:
    """Streamlit Cloud has no .env; keys arrive through st.secrets."""
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "ATS_PROVIDER"):
        if not os.getenv(name):
            try:
                value = st.secrets[name]
            except Exception:
                continue
            if value:
                os.environ[name] = str(value)


def check_password() -> None:
    """Gate the app when APP_PASSWORD is set. A public URL is otherwise open."""
    try:
        expected = st.secrets["APP_PASSWORD"]
    except Exception:
        return
    if not expected or st.session_state.get("_authed"):
        return
    st.title("ACUD ATS")
    entered = st.text_input("Password", type="password")
    if entered == expected:
        st.session_state["_authed"] = True
        st.rerun()
    elif entered:
        st.error("Wrong password.")
    st.stop()


load_secrets()


# ==========================================================================
# 1. CVs
# ==========================================================================
def tab_cvs(settings: Settings) -> None:
    pool = store.stats(settings)
    left, right = st.columns([2, 1])
    left.subheader("Add CVs")
    right.metric("In the pool", pool["cvs"])

    st.caption(
        "Each CV is read once and kept. Adding the same person again costs nothing, "
        "and every future vacancy is matched against what is already here."
    )

    round_no = st.session_state.get("uploader_round", 0)
    uploads = st.file_uploader(
        "Drop CVs here",
        type=["pdf", "docx", "txt", "md", "rtf"],
        accept_multiple_files=True,
        key=f"uploads_{round_no}",
    )
    if uploads:
        settings.inbox_dir.mkdir(parents=True, exist_ok=True)
        for upload in uploads:
            (settings.inbox_dir / upload.name).write_bytes(upload.getbuffer())

    folder = st.text_input("...or a folder on this machine", value=str(settings.inbox_dir))
    paths = parse.discover(Path(folder)) if folder else []
    if not paths:
        st.info("No CVs staged yet.")
        return

    pending = screening.pending_count(paths, settings)
    st.write(f"**{len(paths)} file(s) here - {pending} still need reading.**")

    problem = preflight(settings)
    if problem:
        st.error(problem)
        return

    if pending == 0:
        st.success("Every CV here has already been read. Go to **Shortlist**.")
    elif pending > 60:
        minutes = round(pending / 10)
        st.warning(
            f"Reading {pending} CVs takes about {minutes} minutes, and a browser tab "
            f"that sleeps will end it. Progress is saved either way, but a batch this "
            f"size belongs in a terminal:"
        )
        st.code(f'python hr_cli.py intake --input "{folder}"', language="bash")

    if st.button(f"Read {pending} CV(s)", type="primary", disabled=pending == 0):
        bar = st.progress(0.0, text="Starting...")
        log = st.empty()
        seen: list[str] = []

        def on_progress(name: str, done: int, total: int) -> None:
            seen.append(name)
            bar.progress(done / total, text=f"{done} of {total}")
            log.code("\n".join(seen[-8:]))

        report = screening.intake(paths, settings, on_progress=on_progress)
        bar.progress(1.0, text="Done")
        st.success(
            f"Added {report.added}, already known {report.already_known}"
            + (f", not CVs {report.not_cvs}" if report.not_cvs else "")
            + (f", failed {report.failed} (run again to retry)" if report.failed else "")
        )
        if report.errors:
            with st.expander(f"{len(report.errors)} file(s) had problems"):
                for name, why in report.errors:
                    st.text(f"{name} - {why}")

    with st.expander("Clear the staged files"):
        st.caption(
            "Removes the uploaded files from disk. Candidates already read stay in "
            "the pool - this only clears the staging folder."
        )
        if st.button("Delete staged files"):
            deleted, _ = clear_files(settings.inbox_dir)
            st.session_state["uploader_round"] = round_no + 1
            st.success(f"Deleted {deleted} file(s).")
            st.rerun()


# ==========================================================================
# 2. Jobs
# ==========================================================================
def tab_jobs(settings: Settings) -> None:
    st.subheader("Add a job")
    st.caption("Paste the advert. The requirements are read out of it for you to check.")

    text = st.text_area("Job advert", height=240)
    if st.button("Read the requirements", disabled=not text.strip()):
        problem = preflight(settings)
        if problem:
            st.error(problem)
        else:
            with st.spinner("Reading..."):
                try:
                    st.session_state["draft"] = jobspec.from_text(text, settings)
                except ClassificationError as exc:
                    st.error(str(exc))

    draft = st.session_state.get("draft")
    if draft is not None:
        st.divider()
        st.markdown(f"### {draft.title}")
        st.caption(f"{draft.seniority} - {draft.summary}")
        st.warning(
            "**Check these before shortlisting anyone.** A must-have removes every "
            "applicant who lacks it, and nobody reviews who was removed. Untick "
            "anything you would hire someone without."
        )
        for index, req in enumerate(list(draft.requirements)):
            is_must = st.checkbox(
                f"**{req.text}**  - {req.kind}",
                value=req.importance == "must_have",
                key=f"req_{index}",
                help="Ticked = must have. Unticked = nice to have.",
            )
            req.importance = "must_have" if is_must else "nice_to_have"

        must = sum(1 for r in draft.requirements if r.importance == "must_have")
        st.caption(f"{must} must-have, {len(draft.requirements) - must} nice-to-have")

        name = st.text_input("Save as", value=draft.slug)
        if st.button("Save this job", type="primary"):
            jobspec.save(draft, name)
            st.session_state.pop("draft", None)
            st.success(f"Saved. Open **Shortlist** to rank the pool against {draft.title}.")

    saved = jobspec.available()
    if saved:
        st.divider()
        st.caption(f"{len(saved)} saved job(s)")
        for path in saved:
            job = jobspec.load(path)
            st.text(
                f"  {job.title:<34} {len(job.must_haves)} must-have, "
                f"{len(job.nice_to_haves)} nice-to-have"
            )


# ==========================================================================
# 3. Shortlist
# ==========================================================================
def tab_shortlist(settings: Settings) -> None:
    saved = jobspec.available()
    if not saved:
        st.info("Add a job first.")
        return
    if store.stats(settings)["total"] == 0:
        st.info("The pool is empty. Add some CVs first.")
        return

    chosen = st.selectbox("Vacancy", [p.stem for p in saved])
    job = jobspec.load(next(p for p in saved if p.stem == chosen))

    ranked = screening.shortlist(job, settings)
    stats = rank.summarize(ranked)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Shortlist", stats["shortlist"])
    c2.metric("Worth a look", stats["review"])
    c3.metric("Not a match", stats["not_a_match"])
    c4.metric("Candidates", stats["total"] - stats["not_a_cv"])

    st.caption(
        f"**{job.title}** - {len(job.must_haves)} must-have, "
        f"{len(job.nice_to_haves)} nice-to-have"
    )
    if stats["flagged_ai"]:
        st.info(
            f"{stats['flagged_ai']} CV(s) read as possibly AI-written. They are "
            f"marked, not rejected - the check is not reliable enough to end "
            f"someone's application on its own."
        )

    show_all = st.toggle("Include candidates who are not a match", value=False)

    for entry in ranked:
        if entry.tier == "not_a_cv":
            continue
        if entry.tier == "not_a_match" and not show_all:
            continue

        flag = "  |  possibly AI-written" if entry.flagged_ai else ""
        header = (
            f"{rank.TIER_LABEL[entry.tier]}  |  {entry.name}  |  "
            f"{entry.match.must_met}/{entry.match.must_total} must-haves{flag}"
        )
        with st.expander(header, expanded=entry.tier == "shortlist"):
            candidate = entry.match.candidate
            top, side = st.columns([2, 1])
            top.write(entry.reason)
            side.caption(
                f"{candidate.headline or '-'}  \n"
                f"{candidate.total_years_experience:g} years  \n"
                f"{candidate.email or '-'}  \n{candidate.phone or '-'}"
            )
            for result in entry.match.results:
                mark, label = STATUS_STYLE[result.status]
                weight = "**" if result.is_must else ""
                evidence = f" - _{result.evidence}_" if result.evidence else ""
                st.markdown(
                    f"{mark} {weight}{result.requirement}{weight}  `{label}`{evidence}"
                )

    rows = [
        {
            "Tier": rank.TIER_LABEL[e.tier],
            "Name": e.name,
            "Role": e.match.candidate.headline,
            "Years": e.match.candidate.total_years_experience,
            "Must-haves": f"{e.match.must_met}/{e.match.must_total}",
            "Meets": ", ".join(e.match.met_labels),
            "Missing": ", ".join(e.match.missing_labels),
            "Email": e.match.candidate.email,
            "Phone": e.match.candidate.phone,
            "Possibly AI-written": "yes" if e.flagged_ai else "",
            "File": e.match.source_name,
        }
        for e in ranked
        if e.tier != "not_a_cv"
    ]
    if rows:
        st.download_button(
            "Download the full ranking (CSV)",
            pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{job.slug}_ranking.csv",
            mime="text/csv",
        )


def main() -> None:
    check_password()
    settings = Settings()

    st.title("ACUD ATS")
    st.caption("Read each CV once. Match it against any vacancy, with the reasons shown.")

    cvs, jobs, shortlist = st.tabs(["1 - CVs", "2 - Jobs", "3 - Shortlist"])
    with cvs:
        tab_cvs(settings)
    with jobs:
        tab_jobs(settings)
    with shortlist:
        tab_shortlist(settings)


if __name__ == "__main__":
    main()
