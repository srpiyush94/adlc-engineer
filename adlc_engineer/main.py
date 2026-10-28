"""CLI entrypoint: analyze a repository (local path or git URL) and write a modernization report.

Run as: python -m adlc_engineer.main [--repo <path-or-url>] [--output <path>]
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from adlc_engineer import adr_writer, report_template, repo_source, scanner  # noqa: E402  (must load env first)
from adlc_engineer.graph import build_graph
from adlc_engineer.llm import get_langfuse_handler

DEFAULT_REPO = str(Path(__file__).resolve().parent.parent)
DEFAULT_OUTPUT = str(Path(__file__).resolve().parent / "reports" / "architecture_report.md")


def _scan_only(args):
    with repo_source.resolve_repo(args.repo) as (repo_path, display_name):
        print(f"Scanning repository (no LLM): {display_name}")
        evidence = scanner.scan_repository(repo_path, display_name)

    output_path = Path(args.output)
    os.makedirs(output_path.parent, exist_ok=True)
    output_path.write_text(report_template.render_scan_report(evidence, display_name), encoding="utf-8")

    print(f"\nReport written to: {output_path}")
    print(f"Unpinned dependencies: {len(evidence['dependencies']['unpinned'])}")
    print(f"Potential secrets: {evidence['secrets']['count']}")
    print(f"Functions at or above complexity {evidence['complexity']['threshold']}: {evidence['complexity']['count']}")
    print(f"Source modules not imported by any test: {evidence['untested_modules']['count']}")
    print(f"Unused imports: {evidence['unused_imports']['count']}")


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
    parser.add_argument(
        "--plan",
        action="store_true",
        default=False,
        help="Generate an ordered, evidence-linked implementation plan (5-10 PR-sized tasks with "
             "acceptance checks and dependencies) for the recommended option. Adds 1 more LLM call.",
    )
    parser.add_argument(
        "--write-adr",
        action="store_true",
        default=False,
        help="Save the generated ADR as a new numbered file (status Proposed) under <repo>/docs/adr/. "
             "Local paths only; ignored with a warning for git URLs. Never overwrites existing ADRs.",
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        default=False,
        help="Run only the deterministic scanner and write a report of its findings (unpinned dependencies, "
             "secrets, complexity, untested modules, unused imports). Makes no LLM call, needs no API key, "
             "and sends nothing off this machine. Cannot be combined with --plan, --challenge, "
             "--requirement or --write-adr.",
    )
    args = parser.parse_args()

    if args.scan_only:
        incompatible = [flag for flag, on in (
            ("--plan", args.plan), ("--challenge", args.challenge),
            ("--requirement", bool(args.requirement)), ("--write-adr", args.write_adr),
        ) if on]
        if incompatible:
            parser.error(f"--scan-only makes no LLM call, so it cannot be combined with {', '.join(incompatible)}")
        _scan_only(args)
        return

    write_adr = args.write_adr
    if write_adr and repo_source.looks_like_git_url(args.repo):
        print("WARNING: --write-adr ignored: the repo is a temporary git clone, so the file would be discarded.")
        write_adr = False

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
                "run_plan": args.plan,
            },
            config=config,
        )

    if write_adr:
        adr_path, indexed = adr_writer.write_adr(
            repo_path, result["modernization"], challenger=result.get("challenger_summary")
        )
        print(f"ADR written to: {adr_path} (status: Proposed)")
        if not indexed:
            print("WARNING: docs/adr/README.md has no index table to add this ADR to; add the row by hand.")

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

    plan = result.get("plan")
    if args.plan and plan:
        print(
            f"Plan: {len(plan['tasks'])} task(s) generated, {len(plan.get('citation_warnings', []))} warning(s)."
        )

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
