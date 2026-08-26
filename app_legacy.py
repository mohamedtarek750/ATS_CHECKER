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
from ats.router import clear_files, clear_results, prepare_tree
from ats import ledger
from ats import job_profile as jobs
from ats.matcher import parse_job_description
from ats.providers import ClassificationError

st.set_page_config(page_title="ACUD ATS Checker", layout="wide")


def load_secrets() -> None:
    """Streamlit Cloud has no .env - keys arrive through st.secrets.

    Copy them into the environment so the provider layer finds them the same way
    it does locally, without any cloud-specific code below this point.
    """
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "ATS_PROVIDER"):
        if not os.getenv(name):
            try:
                value = st.secrets[name]
            except Exception:  # no secrets file, or key absent
                continue
            if value:
                os.environ[name] = str(value)


def running_on_cloud() -> bool:
    """Streamlit Cloud's filesystem is ephemeral and its URL is public."""
    return bool(os.getenv("STREAMLIT_RUNTIME_ENV") or os.getenv("HOSTNAME", "").startswith("streamlit"))


def check_password() -> bool:
    """Gate the app when APP_PASSWORD is set. Without it a public URL is open."""
    try:
        expected = st.secrets["APP_PASSWORD"]
    except Exception:
        return True                      # no password configured
    if not expected:
        return True
    if st.session_state.get("_authed"):
        return True

    st.title("ACUD ATS Checker")
    entered = st.text_input("Password", type="password")
    if entered:
        if entered == expected:
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    st.stop()
    return False


load_secrets()

REASON_LABELS = {
    "not_a_cv": "Not a CV",
    "ai_generated": "AI-generated",
    "unreadable": "Unreadable file",
    "insufficient_content": "Too little content",
    "poor_structure": "Unreadable structure",
    "unprofessional": "Unprofessional presentation",
    "low_quality": "Nothing concrete behind it",
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
    with st.sidebar.expander("Standard bar (optional)"):
        st.caption(
            "Each bar rejects under its own reason, so the rejected/ folder says "
            "why. All are keyed to what the CV contains and how it reads - never "
            "to which template it used. Leave at 0 to accept any genuine CV."
        )
        settings.min_format_score = st.slider("Minimum structure score", 0, 100, 0, 5)
        settings.min_quality_score = st.slider("Minimum content score", 0, 100, 0, 5)
        settings.min_professionalism_score = st.slider(
            "Minimum professionalism score", 0, 100, 0, 5
        )
        settings.required_sections = tuple(
            st.multiselect(
                "Sections a CV must have",
                ["contact", "summary", "education", "experience", "projects", "skills"],
                default=[],
            )
        )
        if "experience" in settings.required_sections:
            st.warning(
                "Requiring `experience` rejects every student and fresh graduate, "
                "including the CV this project was calibrated on."
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
        # Rotating the widget key is what actually empties the uploader. Deleting
        # the files alone leaves Streamlit still showing them, which looks broken.
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
                target = settings.inbox_dir / upload.name
                target.write_bytes(upload.getbuffer())
                paths.append(target)
            st.caption(f"{len(paths)} file(s) staged in {settings.inbox_dir}")

        render_clear_uploads(settings)

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


def _human_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB"):
        if num_bytes < 1024 or unit == "MB":
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} MB"


def render_clear_uploads(settings: Settings) -> None:
    """Delete the staged CVs. Two steps, because this is not undoable."""
    staged = [
        f for f in settings.inbox_dir.glob("*")
        if f.is_file() and f.suffix.lower() in {".pdf", ".docx", ".txt", ".md", ".rtf"}
    ] if settings.inbox_dir.is_dir() else []

    if not staged:
        return

    total = sum(f.stat().st_size for f in staged)
    st.divider()
    left, right = st.columns([3, 1])
    left.caption(
        f"{len(staged)} file(s) currently staged in `{settings.inbox_dir}` "
        f"({_human_size(total)})"
    )

    if not st.session_state.get("confirm_clear"):
        if right.button("Clear uploads", use_container_width=True):
            st.session_state["confirm_clear"] = True
            st.rerun()
        return

    st.warning(
        f"Delete all {len(staged)} staged file(s) from `{settings.inbox_dir}`? "
        f"This cannot be undone. Anything already filed into accepted/ or "
        f"rejected/ is kept."
    )
    with st.expander("Show what will be deleted"):
        for f in sorted(staged):
            st.text(f"  {f.name}  ({_human_size(f.stat().st_size)})")

    yes, no = st.columns(2)
    if yes.button("Yes, delete them", type="primary", use_container_width=True):
        deleted, freed = clear_files(settings.inbox_dir)
        st.session_state["confirm_clear"] = False
        st.session_state["uploader_round"] = st.session_state.get("uploader_round", 0) + 1
        st.session_state.pop("results", None)
        st.session_state["cleared_note"] = f"Deleted {deleted} file(s), {_human_size(freed)}."
        st.rerun()
    if no.button("Cancel", use_container_width=True):
        st.session_state["confirm_clear"] = False
        st.rerun()


def render_clear_results(settings: Settings) -> None:
    """Separate control, separate confirmation - this throws away screening work."""
    with st.sidebar.expander("Danger zone"):
        st.caption(
            "Removes accepted/, rejected/, _unscreened/ and _reports/ under "
            f"`{settings.output_dir}`. Staged uploads are not touched."
        )
        if not st.session_state.get("confirm_wipe"):
            if st.button("Clear screening results"):
                st.session_state["confirm_wipe"] = True
                st.rerun()
            return
        st.warning("Delete all sorted CVs and reports? This cannot be undone.")
        if st.button("Yes, delete results", type="primary"):
            removed = clear_results(settings)
            st.session_state["confirm_wipe"] = False
            st.session_state.pop("results", None)
            st.session_state["cleared_note"] = f"Removed {removed} output folder(s)."
            st.rerun()
        if st.button("Cancel wipe"):
            st.session_state["confirm_wipe"] = False
            st.rerun()


# --------------------------------------------------------------------------
# Job description
# --------------------------------------------------------------------------
def job_tab(settings: Settings):
    """Paste an advert, review what was extracted, then screen against it.

    The review step is the point: a requirement wrongly marked must-have gets
    applied to every applicant, and nobody looks at the ones it filtered out.
    """
    saved = jobs.available()
    names = ["(none - screen by role instead)"] + [p.stem for p in saved]
    chosen = st.selectbox("Screen against job", names, key="job_choice")

    with st.expander("Add a job from its description"):
        text = st.text_area(
            "Paste the job advert",
            height=220,
            placeholder="Paste the full advert. Requirements are read out of it.",
        )
        if st.button("Read requirements", disabled=not text.strip()):
            problem = preflight(settings)
            if problem:
                st.error(problem)
            else:
                with st.spinner("Reading the advert..."):
                    try:
                        st.session_state["draft_job"] = parse_job_description(
                            text, settings
                        )
                    except ClassificationError as exc:
                        st.error(str(exc))

        draft = st.session_state.get("draft_job")
        if draft is not None:
            st.markdown(f"**{draft.title}** - {draft.seniority}")
            st.caption(draft.summary)
            st.warning(
                f"**Check the {len(draft.must_haves)} must-have(s) before saving.** "
                "Each one silently removes every applicant who lacks it, and nobody "
                "reviews what was filtered out. Untick anything you would actually "
                "accept a candidate without."
            )
            kept = 0
            for index, req in enumerate(list(draft.must_haves)):
                if st.checkbox(
                    f"Must have - {req.text}  ({req.kind})",
                    value=True,
                    key=f"mh_{index}",
                ):
                    kept += 1
                else:
                    req.importance = "nice_to_have"
            if draft.nice_to_haves:
                st.caption(
                    "Nice to have: " + ", ".join(r.text for r in draft.nice_to_haves)
                )

            name = st.text_input("Save as", value=draft.slug)
            if st.button("Save job profile", type="primary"):
                path = jobs.save(draft, name)
                st.session_state.pop("draft_job", None)
                st.success(f"Saved {path.name} with {kept} must-have(s).")
                st.rerun()

    if chosen == names[0]:
        return None
    try:
        return jobs.load(next(p for p in saved if p.stem == chosen))
    except (StopIteration, OSError, ValueError) as exc:
        st.error(f"Could not load that job profile: {exc}")
        return None


def render_match_results(results: list, profile) -> None:
    """HR-facing view: requirements met, the evidence, and nothing else."""
    stats = summarize(results)
    outcomes = stats["by_outcome"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Screened", stats["total"])
    c2.metric("Shortlist", outcomes.get("strong_match", 0))
    c3.metric("Partial", outcomes.get("partial_match", 0))
    c4.metric("Not a match", outcomes.get("not_a_match", 0))

    st.caption(
        f"Against **{profile.title}** - {len(profile.must_haves)} must-have, "
        f"{len(profile.nice_to_haves)} nice-to-have"
    )

    order = {"strong_match": 0, "partial_match": 1, "not_a_match": 2, "": 3}
    for result in sorted(
        results, key=lambda r: (order.get(r.overall, 3), -r.must_haves_met)
    ):
        if result.errored:
            st.error(f"{result.filename} - not screened: {result.error}")
            continue

        label = {
            "strong_match": "SHORTLIST",
            "partial_match": "PARTIAL",
            "not_a_match": "NOT A MATCH",
        }.get(result.overall, "DROPPED")
        who = result.candidate_name or result.filename
        header = (
            f"{label}  |  {who}  |  "
            f"{result.must_haves_met}/{result.must_haves_total} must-haves"
        )
        with st.expander(header, expanded=result.overall == "strong_match"):
            st.write(result.explanation)
            left, right = st.columns(2)
            if result.met:
                left.markdown("**Meets**")
                left.write("\n".join(f"- {m}" for m in result.met))
            if result.missing:
                right.markdown("**Short on**")
                right.write("\n".join(f"- {m}" for m in result.missing))
            if result.strengths:
                st.markdown("**Strengths**")
                st.write("\n".join(f"- {s}" for s in result.strengths))
            if result.gaps:
                st.markdown("**Gaps**")
                st.write("\n".join(f"- {g}" for g in result.gaps))
            contact = " | ".join(x for x in (result.email, result.phone) if x)
            if contact:
                st.caption(contact)

    frame = pd.DataFrame([asdict(r) for r in results])
    st.download_button(
        "Download shortlist (CSV)",
        frame.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{profile.slug}_shortlist.csv",
        mime="text/csv",
    )


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
    check_password()
    st.title("ACUD ATS Checker")
    st.caption(
        "The model reads every CV, works out the role, flags AI-generated and "
        "off-standard documents, then files each one under accepted/ or "
        "rejected/ by role."
    )

    if running_on_cloud():
        st.warning(
            "**Running on Streamlit Cloud.** The server's disk is wiped whenever the "
            "app restarts or sleeps, so the `accepted/` and `rejected/` folders do "
            "**not** survive - download the CSV report instead. Uploaded CVs are "
            "stored on Streamlit's servers, so do not upload real applicants' CVs "
            "here unless your organisation has approved that."
        )

    settings = sidebar_settings()

    note = st.session_state.pop("cleared_note", None)
    if note:
        st.success(note)

    profile = job_tab(settings)
    paths = collect_inputs(settings)
    render_clear_results(settings)

    st.divider()
    # Block the run outright rather than letting every CV fail one by one.
    problem = preflight(settings)
    if problem:
        st.error(problem)

    # Anything already screened in an earlier run is skipped, so an interrupted
    # batch is resumed rather than repeated.
    done = ledger.load_done(settings, profile.title if profile else "")
    todo = [p for p in paths if ledger.key_for(p) not in done]
    if paths and len(todo) < len(paths):
        st.info(
            f"{len(paths) - len(todo)} of these were screened in an earlier run and "
            f"will be reused. {len(todo)} left to screen."
        )
        if st.checkbox("Screen all of them again from scratch"):
            ledger.clear(settings)
            st.rerun()

    # A long batch in a browser is fragile: the run ends if the tab sleeps or the
    # connection drops. The ledger means nothing is lost, but the terminal is the
    # right tool at this size.
    if len(todo) > 40:
        minutes = max(1, round(len(todo) / 10))
        st.warning(
            f"{len(todo)} CVs will take roughly {minutes} minutes, and a browser tab "
            f"that sleeps or disconnects will end the run. Progress is saved as it "
            f"goes, so nothing is lost either way - but for a batch this size run it "
            f"in a terminal instead:"
        )
        command = (
            f'python jd_cli.py screen --job {profile.slug} --input "{settings.inbox_dir}"'
            if profile
            else f'python ats_cli.py --input "{settings.inbox_dir}"'
        )
        st.code(command, language="bash")

    disabled = not paths or bool(problem)
    label = f"Screen {len(todo)} CV(s)" if todo else "Nothing left to screen"
    if st.button(label, type="primary", disabled=disabled or not todo):
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

        results = screen_many(
            paths, settings, on_progress=on_progress, profile=profile
        )
        progress.progress(1.0, text=f"Done - {len(results)} screened")
        reports = write_reports(results, settings)
        st.session_state["results"] = results
        st.session_state["settings"] = settings
        st.session_state["profile"] = profile
        st.success(f"Report written to {reports['csv']}")

    if st.session_state.get("results"):
        active = st.session_state.get("profile")
        if active is not None:
            render_match_results(st.session_state["results"], active)
        else:
            render_results(st.session_state["results"], st.session_state["settings"])
    elif disabled:
        st.info("Upload CVs or point at a folder to get started.")

    with st.sidebar.expander("Role folders"):
        st.write("\n".join(f"- {r['folder']}" for r in ROLE_TAXONOMY))


if __name__ == "__main__":
    main()
