"""Streamlit front-end for the ACUD ATS checker."""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

from ats.config import PROVIDER_MODELS, PROVIDER_NAMES, ROLE_TAXONOMY, Settings
from ats.classifier import credentials_message, has_credentials
from ats.pipeline import (
    CSV_COLUMNS,
    discover,
    preflight,
    screen_many,
    summarize,
    write_reports,
)
from ats.router import prepare_tree

st.set_page_config(page_title="ACUD ATS Checker", layout="wide")

REASON_LABELS = {
    "not_a_cv": "Not a CV",
    "ai_generated": "AI-generated",
    "unreadable": "Unreadable file",
    "insufficient_content": "Too little content",
    "screening_failed": "NOT screened",
    "none": "-",
}


# --------------------------------------------------------------------------
# Sidebar - configuration
# --------------------------------------------------------------------------
PROVIDER_LABELS = {
    "gemini": "Google Gemini (free tier)",
    "claude": "Anthropic Claude (paid)",
}
KEY_ENV = {"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY"}


def sidebar_settings() -> Settings:
    st.sidebar.header("Settings")

    provider = st.sidebar.selectbox(
        "Provider",
        PROVIDER_NAMES,
        format_func=lambda name: PROVIDER_LABELS.get(name, name),
        help="Gemini is free; Claude is paid and stronger at spotting AI-written CVs.",
    )
    # Set before constructing Settings so the model and worker defaults follow.
    os.environ["ATS_PROVIDER"] = provider
    settings = Settings()

    if has_credentials(settings):
        st.sidebar.success(f"{KEY_ENV[provider]} detected")
    else:
        st.sidebar.error(credentials_message(settings))
        key = st.sidebar.text_input(
            f"Paste a {KEY_ENV[provider]} for this session", type="password"
        )
        if key:
            os.environ[KEY_ENV[provider]] = key
            st.sidebar.info("Key set for this session only. Put it in .env to keep it.")
            st.rerun()

    if provider == "gemini":
        st.sidebar.caption(
            "Google's free tier may use submitted content to improve their models. "
            "Consider that before screening real applicants."
        )

    settings.model = st.sidebar.selectbox(
        "Model", PROVIDER_MODELS[provider], index=0
    )
    settings.ai_threshold = st.sidebar.slider(
        "Reject when AI score is at least",
        min_value=40,
        max_value=100,
        value=settings.ai_threshold,
        step=5,
        help="Lower is stricter. AI detection is probabilistic - keep some headroom.",
    )
    settings.min_role_confidence = st.sidebar.slider(
        "Minimum role confidence",
        min_value=0,
        max_value=90,
        value=settings.min_role_confidence,
        step=5,
        help="Below this the CV goes to the Undetermined folder instead of a guess.",
    )
    settings.file_action = st.sidebar.radio(
        "Original files",
        ["copy", "move"],
        horizontal=True,
        help="'copy' leaves the inbox untouched.",
    )
    settings.max_workers = st.sidebar.slider(
        "Parallel screenings", 1, 12, settings.max_workers
    )
    settings.output_dir = Path(
        st.sidebar.text_input("Output folder", value=str(settings.output_dir))
    )
    st.session_state["scaffold"] = st.sidebar.checkbox(
        "Pre-create every role folder",
        value=False,
        help="Off: only folders that actually receive a CV are created.",
    )
    return settings


# --------------------------------------------------------------------------
# Input - uploads or a folder on disk
# --------------------------------------------------------------------------
def collect_inputs(settings: Settings) -> list[Path]:
    tab_upload, tab_folder = st.tabs(["Upload CVs", "Screen a folder"])
    paths: list[Path] = []

    with tab_upload:
        uploads = st.file_uploader(
            "Drop CVs here",
            type=["pdf", "docx", "txt", "md", "rtf"],
            accept_multiple_files=True,
        )
        if uploads:
            settings.inbox_dir.mkdir(parents=True, exist_ok=True)
            for upload in uploads:
                target = settings.inbox_dir / upload.name
                target.write_bytes(upload.getbuffer())
                paths.append(target)
            st.caption(f"{len(paths)} file(s) staged in {settings.inbox_dir}")

    with tab_folder:
        folder = st.text_input("Folder path", value=str(settings.inbox_dir))
        if folder:
            found = discover(Path(folder))
            st.caption(
                f"{len(found)} supported file(s) found"
                if found
                else "No .pdf / .docx / .txt / .md / .rtf files here."
            )
            if found and st.checkbox("Use this folder instead of the uploads"):
                settings.inbox_dir = Path(folder)
                paths = found

    return paths


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------
def render_results(results: list, settings: Settings) -> None:
    stats = summarize(results)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Screened", stats["total"])
    col2.metric("Accepted", stats["accepted"])
    col3.metric("Rejected", stats["rejected"])
    col4.metric("Not screened", stats["errors"])
    col5.metric("Roles found", len(stats["accepted_by_role"]))

    if stats["errors"]:
        st.warning(
            f"{stats['errors']} file(s) could not be screened, so no judgement was "
            f"made on them. They are **not** rejections - they are held in "
            f"`{settings.unscreened_dir}` and should be re-run once the problem "
            f"below is fixed."
        )

    frame = pd.DataFrame([asdict(r) for r in results])
    display_columns = [c for c in CSV_COLUMNS if c in frame.columns]

    tab_all, tab_ok, tab_no, tab_tree = st.tabs(
        [
            "All",
            f"Accepted ({stats['accepted']})",
            f"Rejected ({stats['rejected']})",
            "Folders",
        ]
    )

    with tab_all:
        st.dataframe(frame[display_columns], use_container_width=True, hide_index=True)

    with tab_ok:
        accepted = frame[frame["status"] == "accepted"]
        if accepted.empty:
            st.info("Nothing accepted in this run.")
        else:
            for role, group in accepted.groupby("role_label"):
                st.subheader(f"{role} ({len(group)})")
                st.dataframe(
                    group[
                        [
                            "filename",
                            "candidate_name",
                            "specialization",
                            "seniority",
                            "years_experience",
                            "ai_generated_score",
                            "quality_score",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

    with tab_no:
        rejected = frame[frame["status"] == "rejected"]
        if rejected.empty:
            st.info("Nothing rejected in this run.")
        else:
            for reason, group in rejected.groupby("reason"):
                st.subheader(f"{REASON_LABELS.get(reason, reason)} ({len(group)})")
                st.dataframe(
                    group[
                        ["filename", "role_label", "ai_generated_score", "explanation"]
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

    with tab_tree:
        render_tree(settings)

    st.divider()
    st.subheader("Per-CV detail")
    for result in results:
        if result.errored:
            badge = "NOT SCREENED"
        elif result.accepted:
            badge = "ACCEPTED"
        else:
            badge = "REJECTED - " + REASON_LABELS.get(result.reason, result.reason)
        header = f"{badge}  |  {result.filename}  |  {result.role_label}"
        with st.expander(header):
            left, right = st.columns(2)
            left.markdown(
                f"**Candidate:** {result.candidate_name or '-'}  \n"
                f"**Email:** {result.email or '-'}  \n"
                f"**Phone:** {result.phone or '-'}  \n"
                f"**Major:** {result.major or '-'}  \n"
                f"**Specialization:** {result.specialization or '-'}  \n"
                f"**Seniority:** {result.seniority or '-'}"
            )
            right.markdown(
                f"**AI score:** {result.ai_generated_score}/100  \n"
                f"**Role confidence:** {result.role_confidence}/100  \n"
                f"**Format score:** {result.format_score}/100  \n"
                f"**Quality score:** {result.quality_score}/100  \n"
                f"**Filed to:** `{result.destination}`"
            )
            st.write(result.explanation)
            if result.top_skills:
                st.caption("Skills: " + ", ".join(result.top_skills))
            if result.ai_signals:
                st.markdown("**AI signals**")
                st.write("\n".join(f"- {s}" for s in result.ai_signals))
            if result.human_signals:
                st.markdown("**Human signals**")
                st.write("\n".join(f"- {s}" for s in result.human_signals))
            if result.error:
                st.error(result.error)

    st.download_button(
        "Download report (CSV)",
        frame[display_columns].to_csv(index=False).encode("utf-8-sig"),
        file_name="ats_report.csv",
        mime="text/csv",
    )


def render_tree(settings: Settings) -> None:
    """Show what actually landed on disk."""
    for base, title in (
        (settings.accepted_dir, "accepted"),
        (settings.rejected_dir, "rejected"),
    ):
        st.markdown(f"**{title}/**")
        if not base.exists():
            st.caption("(not created yet)")
            continue
        rows = []
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            files = [f for f in folder.iterdir() if f.is_file()]
            if files:
                rows.append(
                    {
                        "folder": folder.name,
                        "CVs": len(files),
                        "files": ", ".join(f.name for f in files[:5]),
                    }
                )
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.caption("(empty)")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    st.title("ACUD ATS Checker")
    st.caption(
        "Claude reads every CV, works out the role, flags AI-generated and "
        "off-standard documents, then files each one under accepted/ or "
        "rejected/ by role."
    )

    settings = sidebar_settings()
    paths = collect_inputs(settings)

    st.divider()
    # Block the run outright rather than letting every CV fail one by one.
    problem = preflight(settings)
    if problem:
        st.error(problem)

    disabled = not paths or bool(problem)
    if st.button(f"Screen {len(paths)} CV(s)", type="primary", disabled=disabled):
        folders = (
            [r["folder"] for r in ROLE_TAXONOMY]
            if st.session_state.get("scaffold")
            else None
        )
        prepare_tree(settings, folders)
        progress = st.progress(0.0, text="Starting...")
        log = st.empty()
        lines: list[str] = []

        def on_progress(result, done: int, total: int) -> None:
            mark = "FAIL" if result.errored else "PASS" if result.accepted else "DROP"
            detail = (
                result.role_label
                if result.accepted
                else REASON_LABELS.get(result.reason, result.reason)
            )
            lines.append(f"{mark}  {result.filename}  ->  {detail}")
            progress.progress(done / total, text=f"{done}/{total} screened")
            log.code("\n".join(lines[-12:]))

        results = screen_many(paths, settings, on_progress=on_progress)
        progress.progress(1.0, text=f"Done - {len(results)} screened")
        reports = write_reports(results, settings)
        st.session_state["results"] = results
        st.session_state["settings"] = settings
        st.success(f"Report written to {reports['csv']}")

    if st.session_state.get("results"):
        render_results(st.session_state["results"], st.session_state["settings"])
    elif disabled:
        st.info("Upload CVs or point at a folder to get started.")

    with st.sidebar.expander("Role folders"):
        st.write("\n".join(f"- {r['folder']}" for r in ROLE_TAXONOMY))


if __name__ == "__main__":
    main()
