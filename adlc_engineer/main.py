"""CLI entrypoint: analyze a repository (local path or git URL) and write a modernization report.

Run as: python -m adlc_engineer.main [--repo <path-or-url>] [--output <path>]
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from adlc_engineer import repo_source  # noqa: E402  (must load env first)
from adlc_engineer.graph import build_graph
from adlc_engineer.llm import get_langfuse_handler

DEFAULT_REPO = str(Path(__file__).resolve().parent.parent)
DEFAULT_OUTPUT = str(Path(__file__).resolve().parent / "reports" / "architecture_report.md")


def main():
    parser = argparse.ArgumentParser(description="Analyze a repository and produce a modernization report.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Local path or git URL of the repo to analyze.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Where to write the Markdown report.")
    parser.add_argument(
        "--challenge",
        action="store_true",
        default=False,
        help="Run the Architecture Challenger: five specialist reviewers critique the recommended "
             "modernization option, with one revision pass if they object. Worst case adds 6 more LLM "
             "calls (8 total vs. 2 by default) -- opt in only when you have Gemini quota headroom.",
    )
    parser.add_argument(
        "--requirement",
        default="",
        help="Optional business requirement free text (e.g. 'System must support 10,000 concurrent "
             "requests with p95 latency under 300ms and 99.9%% availability'). When supplied, the agent "
             "derives a Specification and Acceptance Criteria and assesses the recommended modernization "
             "option against them. Adds 1 more LLM call. Empty by default -- pipeline behaves exactly as "
             "before.",
    )
    args = parser.parse_args()

    handler = get_langfuse_handler()
    callbacks = [handler] if handler else []
    if handler is None:
        print("(Langfuse credentials not found in .env — running without tracing.)\n")

    agent = build_graph()

    with repo_source.resolve_repo(args.repo) as (repo_path, display_name):
        print(f"Analyzing repository: {display_name}")
        config = {"callbacks": callbacks} if callbacks else {}
        result = agent.invoke(
            {
                "repo_path": repo_path,
                "repo_display_name": display_name,
                "run_challenger": args.challenge,
                "requirement_text": args.requirement,
            },
            config=config,
        )

    output_path = Path(args.output)
    os.makedirs(output_path.parent, exist_ok=True)
    output_path.write_text(result["report_markdown"], encoding="utf-8")

    evidence = result["evidence"]
    modernization = result["modernization"]
    architecture_model = result["architecture_model"]
    warning_count = len(architecture_model.get("citation_warnings", [])) + len(
        modernization.get("citation_warnings", [])
    )

    print(f"\nReport written to: {output_path}")
    print(f"Languages detected: {', '.join(evidence.get('languages', {}).keys()) or 'none'}")
    print(f"Frameworks detected: {', '.join(evidence.get('frameworks', {}).keys()) or 'none'}")
    print(f"Recommended modernization option: {modernization.get('recommended_option', 'not determined')}")
    if warning_count:
        print(f"WARNING: {warning_count} unresolved citation(s), see Assumptions section in the report.")

    challenger_summary = result.get("challenger_summary")
    if args.challenge and challenger_summary:
        if challenger_summary.get("has_objections"):
            print(
                f"Architecture Challenger: objection(s) raised by "
                f"{', '.join(challenger_summary['objecting_personas'])}; recommendation revised once."
            )
        else:
            print("Architecture Challenger: no objections raised; original recommendation stands.")

    specification = result.get("specification")
    if args.requirement and specification:
        compliance = modernization.get("compliance_assessment") or []
        total = len(specification.get("acceptance_criteria", []))
        if compliance:
            satisfied = sum(1 for a in compliance if a["status"] == "satisfied")
            print(
                f"Specification: {total} acceptance criteria derived; recommended option satisfies "
                f"{satisfied}/{len(compliance)}."
            )
        else:
            print("Specification derived, but no compliance assessment was produced.")


if __name__ == "__main__":
    main()
