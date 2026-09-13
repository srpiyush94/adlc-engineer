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
            {"repo_path": repo_path, "repo_display_name": display_name},
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


if __name__ == "__main__":
    main()
