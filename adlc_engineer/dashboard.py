"""Streamlit dashboard: run new repository analyses and browse past reports.

Run with: streamlit run adlc_engineer/dashboard.py
"""

import os
import re
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from adlc_engineer import repo_source
from adlc_engineer.graph import build_graph
from adlc_engineer.llm import get_langfuse_handler

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
MERMAID_PATTERN = re.compile(r"```mermaid\n(.*?)\n```", re.DOTALL)

st.set_page_config(page_title="ADLC Engineer", layout="wide")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return slug[:60] or "repo"


def _list_reports():
    if not REPORTS_DIR.exists():
        return []
    return sorted(REPORTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def _render_report(report_markdown: str):
    match = MERMAID_PATTERN.search(report_markdown)
    if not match:
        st.markdown(report_markdown)
        return

    before, after = report_markdown[: match.start()], report_markdown[match.end():]
    mermaid_code = match.group(1)

    st.markdown(before)
    # Rendering this inline via st.components.v1.html + mermaid.js produces a
    # degenerate near-zero-size diagram inside Streamlit's sandboxed component
    # iframe (confirmed: the identical mermaid source renders correctly in a
    # plain standalone page -- multiple fixes for DOM-measurement timing did
    # not resolve it, so this may be specific to that iframe sandbox). Showing
    # the raw source is simple and always correct; paste it into
    # https://mermaid.live or a markdown viewer that renders mermaid fences
    # (GitHub, most IDEs) to view it visually.
    st.code(mermaid_code, language="text")
    st.caption("Paste this into https://mermaid.live to view it rendered.")
    st.markdown(after)


def _run_analysis_tab():
    st.subheader("Run a new analysis")
    repo_arg = st.text_input(
        "Repository (local path or git URL)",
        value=str(Path(__file__).resolve().parent.parent),
        help="Either a local filesystem path or a GitHub URL (shallow-cloned read-only).",
    )
    run_clicked = st.button("Run Analysis", type="primary")

    if not run_clicked:
        return

    handler = get_langfuse_handler()
    callbacks = [handler] if handler else []
    if handler is None:
        st.info("Langfuse credentials not found in .env — running without tracing.")

    with st.spinner("Analyzing repository — this involves two LLM calls and can take a minute or two..."):
        try:
            with repo_source.resolve_repo(repo_arg) as (repo_path, display_name):
                agent = build_graph()
                config = {"callbacks": callbacks} if callbacks else {}
                result = agent.invoke(
                    {"repo_path": repo_path, "repo_display_name": display_name},
                    config=config,
                )
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
            return

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = REPORTS_DIR / f"{_slugify(display_name)}_{timestamp}.md"
    report_path.write_text(result["report_markdown"], encoding="utf-8")

    architecture_model = result["architecture_model"]
    modernization = result["modernization"]
    warning_count = len(architecture_model.get("citation_warnings", [])) + len(
        modernization.get("citation_warnings", [])
    )
    st.success(f"Analysis complete. Saved to {report_path.name}")
    if warning_count:
        st.warning(f"{warning_count} unresolved citation(s) — see the Assumptions section below.")

    _render_report(result["report_markdown"])


def _browse_reports_tab():
    st.subheader("Browse past reports")
    reports = _list_reports()
    if not reports:
        st.info("No reports yet — run an analysis in the other tab first.")
        return

    labels = [f"{p.name} ({datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M')})" for p in reports]
    selected = st.selectbox("Select a report", options=range(len(reports)), format_func=lambda i: labels[i])
    report_markdown = reports[selected].read_text(encoding="utf-8")
    _render_report(report_markdown)


def main():
    st.title("ADLC Engineer")
    st.caption("Repository Analyst -> Architecture Analyst -> Modernization Strategist")

    tab_run, tab_browse = st.tabs(["Run New Analysis", "Browse Reports"])
    with tab_run:
        _run_analysis_tab()
    with tab_browse:
        _browse_reports_tab()


main()
