"""ADLC Engineer graph: scan_repo -> analyze_architecture -> propose_modernization -> assemble_report."""

import json
import re
from typing import List, Literal, Optional

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
    revision_notes: Optional[str] = None  # only populated by revise_modernization


class ReviewFinding(BaseModel):
    has_objection: bool
    severity: Literal["none", "low", "medium", "high"]
    summary: str
    citations: List[str]


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

_REVIEWER_SYSTEM_PROMPT_TEMPLATE = """You are the {persona} Reviewer on an architecture challenge panel. \
You will be given repository EVIDENCE (from a deterministic scanner) and the RECOMMENDED MODERNIZATION \
OPTION the architect proposed (its reasoning, ADR, migration roadmap, and risks). Critique this \
recommendation strictly from a {persona} perspective: {focus_description}

Rules:
- Only set `has_objection` to true if the evidence actually supports a concrete, material concern from your \
{persona} lens. Do NOT manufacture an objection to seem thorough -- if the recommendation holds up given \
the evidence, honestly set `has_objection` to false and say so.
- `citations` must be non-empty in every case, including when `has_objection` is false -- cite the evidence \
that supports "no issue here" (e.g. a dot-path resolving to an absence, or the specific evidence that \
satisfies your concern). Never leave `citations` empty.
- `severity` must be "none" when `has_objection` is false, and "low"/"medium"/"high" when true, matched \
honestly to how material the concern is -- do not inflate severity for effect.
- `summary` must be 2-4 sentences specific to this repository's actual evidence, not generic advice that \
could apply to any codebase.
"""

REVIEWER_PERSONAS = {
    "Security": (
        "the `integrations` evidence (database/external SDK/http-client usage), the dependency list for "
        "anything security-sensitive, `hotspots.bare_except_count`/locations (swallowed errors can hide "
        "security-relevant failures), and `deployment.gaps` (no CI/CD or containerization means no "
        "repeatable, auditable path to production). Judge whether the recommendation's reasoning and "
        "migration roadmap account for these."
    ),
    "Scalability": (
        "the `coupling` graph (how tightly local modules are interlinked), `architecture_pattern_guess` "
        "(e.g. single-process graph-orchestrated workflow vs. a web service), and `hotspots.largest_files` "
        "(large single modules that resist horizontal scaling). Judge whether the recommendation's claimed "
        "`scalability` rating is actually supported by this evidence or merely asserted."
    ),
    "Cost": (
        "the `migration_roadmap`'s length/complexity relative to the repo's actual size (`languages` LOC/"
        "file counts, `frameworks` declared), and `dependencies.declared_but_not_directly_imported` "
        "(migration effort spent on dependencies that may not even be used). Judge whether the "
        "recommendation's `cost` rating in the modernization table is consistent with what the evidence "
        "shows about repo complexity."
    ),
    "Reliability": (
        "the `tests` evidence (count and any `gap`), `hotspots.bare_except_count`/locations, and "
        "`deployment.gaps` (no CI/CD or docker-compose means no repeatable rollback path). Judge whether "
        "the ADR's consequences and the migration roadmap honestly account for the current lack of "
        "automated test coverage as a regression risk during migration."
    ),
    "Implementation": (
        "whether the `migration_roadmap`'s steps are feasible given the `languages`/`frameworks` actually "
        "present, whether it accounts for the `coupling` edges it would need to preserve or break "
        "intentionally, and whether the `assumptions` in the modernization model are realistic given any "
        "`parse_errors` or other gaps the scanner surfaced."
    ),
}


def _build_reviewer_system_prompt(persona: str, focus_description: str) -> str:
    return _REVIEWER_SYSTEM_PROMPT_TEMPLATE.format(persona=persona, focus_description=focus_description)


REVISION_SYSTEM_PROMPT = """You are the Modernization Strategist revisiting your own recommendation after \
an architecture challenge panel raised objections. You will be given the original EVIDENCE, your ORIGINAL \
modernization model output, and the PANEL OBJECTIONS (only findings with has_objection true).

Rules:
- Directly address each listed objection: change `reasoning`, `risks`, `migration_roadmap`, or `adr` content \
to account for it, OR (if an objection isn't well-grounded) explain in `revision_notes` why you are not \
changing that part, citing evidence.
- Still evaluate all five fixed options in the same fixed order, with the same grounding rules as before \
(non-empty citations, no artificially balanced ratings for heavier options on small/simple repos).
- `revision_notes` is REQUIRED on this call and must be 2-4 sentences summarizing exactly what changed and \
which persona's objection drove each change.
- `recommended_option` may change to a different one of the five if the objections genuinely warrant it, but \
must not change gratuitously.
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


REVIEWER_SPECS = [
    ("Security", "security_review", REVIEWER_PERSONAS["Security"]),
    ("Scalability", "scalability_review", REVIEWER_PERSONAS["Scalability"]),
    ("Cost", "cost_review", REVIEWER_PERSONAS["Cost"]),
    ("Reliability", "reliability_review", REVIEWER_PERSONAS["Reliability"]),
    ("Implementation", "implementation_review", REVIEWER_PERSONAS["Implementation"]),
]
REVIEWER_NODE_NAMES = [state_key for _, state_key, _ in REVIEWER_SPECS]


def route_after_modernization(state: dict) -> List[str]:
    """Fan out to all five reviewers if the caller opted in, else go straight to
    assemble_report -- preserving the original 2-LLM-call default behavior."""
    if state.get("run_challenger", False):
        return list(REVIEWER_NODE_NAMES)
    return ["assemble_report"]


def aggregate_reviews(reviews: dict) -> bool:
    """True if any reviewer finding raised a real objection worth revising for."""
    return any(finding.get("has_objection", False) for finding in reviews.values())


def route_after_challenger_review(state: dict) -> str:
    if state["challenger_summary"]["has_objections"]:
        return "revise_modernization"
    return "assemble_report"


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
                "revised": False,
            }
        }

    def _build_reviewer_node(persona: str, focus_description: str, state_key: str):
        system_prompt = _build_reviewer_system_prompt(persona, focus_description)

        def reviewer_node(state: ADLCState):
            evidence = state["evidence"]
            modernization = state["modernization"]
            recommended_name = modernization.get("recommended_option")
            recommended_option = next(
                (o for o in modernization.get("options", []) if o["name"] == recommended_name), None
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=(
                        f"EVIDENCE:\n{json.dumps(evidence, indent=2)}\n\n"
                        f"RECOMMENDED MODERNIZATION OPTION: {recommended_name}\n"
                        f"Reasoning: {recommended_option['reasoning'] if recommended_option else 'not found'}\n"
                        f"ADR: {modernization.get('adr', '')}\n"
                        f"Migration roadmap: {json.dumps(modernization.get('migration_roadmap', []))}\n"
                        f"Risks: {json.dumps(modernization.get('risks', []))}"
                    )
                ),
            ]
            structured_llm = llm.with_structured_output(ReviewFinding)
            result: ReviewFinding = structured_llm.invoke(messages)
            warnings = check_citations(result.citations, evidence, state["repo_path"])
            return {state_key: {"persona": persona, **result.model_dump(), "citation_warnings": warnings}}

        return reviewer_node

    def synthesize_challenger_review(state: ADLCState):
        reviews = {
            "Security": state["security_review"],
            "Scalability": state["scalability_review"],
            "Cost": state["cost_review"],
            "Reliability": state["reliability_review"],
            "Implementation": state["implementation_review"],
        }
        has_objections = aggregate_reviews(reviews)
        objecting_personas = [p for p, finding in reviews.items() if finding.get("has_objection")]
        return {
            "challenger_summary": {
                "reviews": reviews,
                "has_objections": has_objections,
                "objecting_personas": objecting_personas,
            }
        }

    def revise_modernization(state: ADLCState):
        evidence = state["evidence"]
        original_modernization = state["modernization"]
        objections = [
            {"persona": persona, **finding}
            for persona, finding in state["challenger_summary"]["reviews"].items()
            if finding.get("has_objection")
        ]
        structured_llm = llm.with_structured_output(ModernizationModel)
        messages = [
            SystemMessage(content=REVISION_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"EVIDENCE:\n{json.dumps(evidence, indent=2)}\n\n"
                    f"ORIGINAL MODERNIZATION MODEL:\n{json.dumps(original_modernization, indent=2)}\n\n"
                    f"PANEL OBJECTIONS:\n{json.dumps(objections, indent=2)}"
                )
            ),
        ]
        result: ModernizationModel = structured_llm.invoke(messages)
        warnings = _check_modernization_citations(result, evidence, state["repo_path"])
        return {
            "modernization": {
                **result.model_dump(),
                "citation_warnings": warnings,
                "revised": True,
            }
        }

    def assemble_report(state: ADLCState):
        challenger = state.get("challenger_summary") if state.get("run_challenger") else None
        report_markdown = report_template.render_report(
            evidence=state["evidence"],
            architecture_model=state["architecture_model"],
            modernization=state["modernization"],
            repo_display_name=state["repo_display_name"],
            challenger=challenger,
        )
        return {"report_markdown": report_markdown}

    graph = StateGraph(ADLCState)
    graph.add_node("scan_repo", scan_repo)
    graph.add_node("analyze_architecture", analyze_architecture)
    graph.add_node("propose_modernization", propose_modernization)
    for persona, state_key, focus in REVIEWER_SPECS:
        graph.add_node(state_key, _build_reviewer_node(persona, focus, state_key))
    graph.add_node("synthesize_challenger_review", synthesize_challenger_review)
    graph.add_node("revise_modernization", revise_modernization)
    graph.add_node("assemble_report", assemble_report)

    graph.add_edge(START, "scan_repo")
    graph.add_edge("scan_repo", "analyze_architecture")
    graph.add_edge("analyze_architecture", "propose_modernization")
    graph.add_conditional_edges(
        "propose_modernization",
        route_after_modernization,
        path_map=REVIEWER_NODE_NAMES + ["assemble_report"],
    )
    graph.add_edge(REVIEWER_NODE_NAMES, "synthesize_challenger_review")
    graph.add_conditional_edges(
        "synthesize_challenger_review",
        route_after_challenger_review,
        path_map=["revise_modernization", "assemble_report"],
    )
    graph.add_edge("revise_modernization", "assemble_report")
    graph.add_edge("assemble_report", END)

    return graph.compile()
