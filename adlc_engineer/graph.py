"""ADLC Engineer graph: scan_repo -> analyze_architecture -> propose_modernization -> assemble_report."""

import json
import re
from typing import List, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from adlc_engineer import report_template, scanner
from adlc_engineer.llm import build_llm
from adlc_engineer.state import ADLCState

MODERNIZATION_OPTION_NAMES = [
    "Modernize monolith",
    "Modular monolith",
    "Strangler",
    "Selective microservices",
    "Event-driven decomposition",
]


class ComponentCitation(BaseModel):
    name: str
    grounded_in: List[str]


class ArchitectureModel(BaseModel):
    narrative: str
    mermaid: str
    components: List[ComponentCitation]


class ModernizationOption(BaseModel):
    name: Literal[
        "Modernize monolith",
        "Modular monolith",
        "Strangler",
        "Selective microservices",
        "Event-driven decomposition",
    ]
    cost: str
    risk: str
    complexity: str
    scalability: str
    recommendation: str
    reasoning: str
    citations: List[str]


class ModernizationModel(BaseModel):
    options: List[ModernizationOption]
    recommended_option: str
    adr: str
    migration_roadmap: List[str]
    risks: List[str]
    assumptions: List[str]


ARCHITECTURE_SYSTEM_PROMPT = """You are an Architecture Analyst. You will be given EVIDENCE gathered by a \
deterministic repository scanner, as JSON. Your job is to describe the current architecture using ONLY \
what is present in that evidence.

Rules:
- Never claim a language, framework, database, or deployment mechanism that does not appear in the evidence.
- Every entry in `components` MUST have a non-empty `grounded_in` list, where each item is either an \
evidence dot-path (e.g. "frameworks.langgraph") or a real relative file path from the evidence.
- If evidence for something (e.g. deployment, database, tests) is absent, say so explicitly as a gap in the \
narrative rather than omitting it or inventing a plausible-sounding default.
- The `mermaid` diagram's node labels must exactly match the `name` field of entries in `components`. Use \
simple `graph TD` syntax, one edge per line as `NodeA --> NodeB`. Never use a mermaid reserved word \
(graph, subgraph, end, class, click, style, classDef, direction) as a bare node identifier — mermaid's \
parser fails outright on that.
- Do not speculate about business purpose or scale beyond what the evidence supports.
"""

MODERNIZATION_SYSTEM_PROMPT = """You are a Modernization Strategist. You will be given repository EVIDENCE \
and an ARCHITECTURE MODEL (both grounded in that evidence). Evaluate exactly these five options, in this \
order: Modernize monolith, Modular monolith, Strangler, Selective microservices, Event-driven decomposition.

Rules:
- Every option's `reasoning` must reference concrete evidence (LOC, module/file count, dependency count, \
presence or absence of deployment infrastructure, coupling) — not generic, interchangeable statements.
- For a small, simple, single-process codebase with no deployment infrastructure, heavier decomposition \
options (Selective microservices, Event-driven decomposition) should honestly be rated low-value/high-cost \
overkill, with reasoning that explains why given the evidence — do not artificially balance the ratings to \
look even-handed.
- Every option's `citations` list must be non-empty and reference evidence dot-paths or real file paths that \
back a claim used in its reasoning.
- `recommended_option` must be one of the five option names, verbatim.
- `adr` should be a short Architecture Decision Record (context, decision, consequences) for the recommended \
option, grounded in the same evidence.
"""


_MERMAID_RESERVED_WORDS = {
    "graph", "subgraph", "end", "class", "click", "style", "classDef", "direction", "flowchart",
}
_MERMAID_EDGE_LINE_RE = re.compile(
    r"^(?P<indent>\s*)(?P<src>[A-Za-z_][A-Za-z0-9_]*)(?P<arrow>\s*-->\s*)(?P<dst>[A-Za-z_][A-Za-z0-9_]*)\s*$"
)


def _sanitize_mermaid(mermaid_code: str) -> str:
    """Rewrite a bare node id that collides with a mermaid reserved keyword
    (e.g. a component literally named "graph", matching adlc_engineer/graph.py)
    into a safe synthetic id with the original name kept as a bracketed label.
    Mermaid's parser fails outright -- with no visible error in some embed
    contexts -- on a bare reserved word used as a node id, so this is applied
    unconditionally rather than only trusting the system prompt.
    """

    def safe_token(token: str) -> str:
        return f"n_{token}[{token}]" if token.lower() in _MERMAID_RESERVED_WORDS else token

    lines = []
    for line in mermaid_code.splitlines():
        match = _MERMAID_EDGE_LINE_RE.match(line)
        if match:
            lines.append(
                f"{match.group('indent')}{safe_token(match.group('src'))}"
                f"{match.group('arrow')}{safe_token(match.group('dst'))}"
            )
        else:
            lines.append(line)
    return "\n".join(lines)


_NOT_FOUND = object()


def _resolve_dot_path(evidence: dict, dot_path: str):
    """Resolve a dot-path against evidence, greedily matching the longest key at
    each level first so keys that themselves contain literal dots (e.g. a file
    path like "adlc_engineer/graph.py" inside `coupling`) still resolve correctly.
    """
    parts = dot_path.split(".")
    current = evidence
    i = 0
    while i < len(parts):
        if not isinstance(current, dict):
            return _NOT_FOUND
        for j in range(len(parts), i, -1):
            candidate_key = ".".join(parts[i:j])
            if candidate_key in current:
                current = current[candidate_key]
                i = j
                break
        else:
            return _NOT_FOUND
    return current


def check_citations(citations: List[str], evidence: dict, repo_path: str) -> List[str]:
    import os

    warnings = []
    if not citations:
        warnings.append("No citations provided for a claim that requires grounding.")
        return warnings

    for citation in citations:
        # A citation resolves if the dot-path exists in evidence at all -- even an
        # empty dict/list is valid grounding (e.g. "integrations.database" being {}
        # is real evidence that no database was found, not a failed lookup).
        if _resolve_dot_path(evidence, citation) is not _NOT_FOUND:
            continue
        file_candidate = os.path.join(repo_path, citation.split(" ")[0].split(":")[0])
        if os.path.exists(file_candidate):
            continue
        warnings.append(f"Unresolved citation: {citation!r}")
    return warnings


def _check_architecture_citations(model: ArchitectureModel, evidence: dict, repo_path: str) -> List[str]:
    warnings = []
    for component in model.components:
        warnings.extend(check_citations(component.grounded_in, evidence, repo_path))
    return warnings


def _check_modernization_citations(model: ModernizationModel, evidence: dict, repo_path: str) -> List[str]:
    warnings = []
    for option in model.options:
        warnings.extend(check_citations(option.citations, evidence, repo_path))
    if len(model.options) != 5:
        warnings.append(f"Expected 5 modernization options, got {len(model.options)}.")
    return warnings


def build_graph():
    llm = build_llm()

    def scan_repo(state: ADLCState):
        evidence = scanner.scan_repository(state["repo_path"], state["repo_display_name"])
        return {"evidence": evidence}

    def analyze_architecture(state: ADLCState):
        evidence = state["evidence"]
        structured_llm = llm.with_structured_output(ArchitectureModel)
        messages = [
            SystemMessage(content=ARCHITECTURE_SYSTEM_PROMPT),
            HumanMessage(content=f"EVIDENCE:\n{json.dumps(evidence, indent=2)}"),
        ]
        result: ArchitectureModel = structured_llm.invoke(messages)
        warnings = _check_architecture_citations(result, evidence, state["repo_path"])
        model_dump = result.model_dump()
        model_dump["mermaid"] = _sanitize_mermaid(model_dump["mermaid"])
        return {
            "architecture_model": {
                **model_dump,
                "citation_warnings": warnings,
            }
        }

    def propose_modernization(state: ADLCState):
        evidence = state["evidence"]
        architecture_model = state["architecture_model"]
        structured_llm = llm.with_structured_output(ModernizationModel)
        messages = [
            SystemMessage(content=MODERNIZATION_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"EVIDENCE:\n{json.dumps(evidence, indent=2)}\n\n"
                    f"ARCHITECTURE MODEL:\n"
                    f"Narrative: {architecture_model['narrative']}\n"
                    f"Components: {json.dumps(architecture_model['components'], indent=2)}"
                )
            ),
        ]
        result: ModernizationModel = structured_llm.invoke(messages)
        warnings = _check_modernization_citations(result, evidence, state["repo_path"])
        return {
            "modernization": {
                **result.model_dump(),
                "citation_warnings": warnings,
            }
        }

    def assemble_report(state: ADLCState):
        report_markdown = report_template.render_report(
            evidence=state["evidence"],
            architecture_model=state["architecture_model"],
            modernization=state["modernization"],
            repo_display_name=state["repo_display_name"],
        )
        return {"report_markdown": report_markdown}

    graph = StateGraph(ADLCState)
    graph.add_node("scan_repo", scan_repo)
    graph.add_node("analyze_architecture", analyze_architecture)
    graph.add_node("propose_modernization", propose_modernization)
    graph.add_node("assemble_report", assemble_report)

    graph.add_edge(START, "scan_repo")
    graph.add_edge("scan_repo", "analyze_architecture")
    graph.add_edge("analyze_architecture", "propose_modernization")
    graph.add_edge("propose_modernization", "assemble_report")
    graph.add_edge("assemble_report", END)

    return graph.compile()
