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
from streamlit_mermaid import st_mermaid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

try:
    # Streamlit Community Cloud provides credentials via st.secrets, not a
    # .env file. Bridge them into os.environ so llm.py's os.environ.get(...)
    # calls work unchanged in both local (.env) and deployed (secrets.toml)
    # contexts.
    for _key, _value in st.secrets.items():
        os.environ.setdefault(_key, str(_value))
except st.errors.StreamlitSecretNotFoundError:
    pass  # no Streamlit secrets configured -- local dev via .env, fine

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
    # A hand-rolled st.components.v1.html + mermaid.js embed produced a
    # degenerate near-zero-size diagram inside Streamlit's sandboxed component
    # iframe (the identical source rendered fine in a plain standalone page --
    # several DOM-measurement-timing fixes didn't resolve it). streamlit-mermaid
    # is a proper Streamlit custom component (not a raw iframe hack), which
    # handles sizing through Streamlit's own component protocol instead.
    try:
        st_mermaid(mermaid_code)
    except Exception as exc:
        st.warning(f"Could not render the diagram inline ({exc}). Raw source below.")
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
    requirement_text = st.text_area(
        "Business requirement (optional)",
        value="",
        placeholder="e.g. System must support 10,000 concurrent requests with p95 latency under 300ms "
                    "and 99.9% availability.",
        help="Leave blank to skip. When supplied, the agent derives a Specification and Acceptance "
             "Criteria, and assesses the recommended modernization option against them (adds 1 more "
             "LLM call).",
    )
    run_challenge = st.checkbox(
        "Run Architecture Challenger (5 reviewer critiques + possible revision — up to 6 extra LLM calls)",
        value=False,
        help="Off by default to avoid burning through the Gemini free-tier daily quota.",
    )
    run_clicked = st.button("Run Analysis", type="primary")

    if not run_clicked:
        return

    handler = get_langfuse_handler()
    callbacks = [handler] if handler else []
    if handler is None:
        st.info("Langfuse credentials not found in .env — running without tracing.")

    num_calls = 2
    if requirement_text.strip():
        num_calls += 1
    if run_challenge:
        num_calls += 6
    spinner_text = f"Analyzing repository — this involves up to {num_calls} LLM calls and can take a few minutes..."
    with st.spinner(spinner_text):
        try:
            with repo_source.resolve_repo(repo_arg) as (repo_path, display_name):
                agent = build_graph()
                config = {"callbacks": callbacks} if callbacks else {}
                result = agent.invoke(
                    {
                        "repo_path": repo_path,
                        "repo_display_name": display_name,
                        "run_challenger": run_challenge,
                        "requirement_text": requirement_text,
                    },
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

    challenger_summary = result.get("challenger_summary")
    if run_challenge and challenger_summary:
        if challenger_summary.get("has_objections"):
            st.info(
                f"Architecture Challenger: objection(s) raised by "
                f"{', '.join(challenger_summary['objecting_personas'])}; recommendation revised once."
            )
        else:
            st.info("Architecture Challenger: no objections raised; original recommendation stands.")

    specification = result.get("specification")
    if requirement_text.strip() and specification:
        compliance = modernization.get("compliance_assessment") or []
        total = len(specification.get("acceptance_criteria", []))
        if compliance:
            satisfied = sum(1 for a in compliance if a["status"] == "satisfied")
            st.info(
                f"Specification: {total} acceptance criteria derived; recommended option satisfies "
                f"{satisfied}/{len(compliance)}."
            )
        else:
            st.info("Specification derived, but no compliance assessment was produced.")

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
