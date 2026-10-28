"""Implementation plan (--plan): models, system prompt, and deterministic validation.

No LLM calls and no filesystem I/O here; graph.py wires these into a node.
"""

from typing import Callable, List, Literal

from pydantic import BaseModel

MONOLITH_OPTIONS = {"Modernize monolith", "Modular monolith"}
# Words that signal a decomposition task, inconsistent with a monolith recommendation.
DECOMPOSITION_TERMS = ("microservice", "event-driven", "event driven", "strangler")


class PlanTask(BaseModel):
    id: str  # "T-1", "T-2", ... sequential, LLM-assigned in output order
    title: str
    rationale: str
    gap_ref: str  # evidence dot-path of the gap this task closes, e.g. "tests.gap"
    acceptance_check: str  # a verifiable statement of done
    depends_on: List[str]
    effort: Literal["S", "M", "L"]
    citations: List[str]
    criteria_refs: List[str]  # AC ids this task helps satisfy; empty when no specification


class PlanModel(BaseModel):
    tasks: List[PlanTask]
    not_addressed: List[str]  # flagged gaps deliberately left out, each with a reason


PLAN_SYSTEM_PROMPT = """You are an Implementation Planner. You will be given repository EVIDENCE and the \
RECOMMENDED MODERNIZATION OPTION with its reasoning, roadmap and risks. Turn them into an ordered list of \
tasks a team can execute.

Rules:
- Produce 5 to 10 tasks. Each task must be sized for a single pull request.
- Each task has a unique `id` of the form "T-1", "T-2", ... in execution order.
- `gap_ref` must be the evidence dot-path of the gap the task closes (e.g. "tests.gap", \
"deployment.gaps", "dependencies.source_file"). `citations` must be non-empty and reference real evidence \
dot-paths or file paths.
- `acceptance_check` must be a concrete, verifiable statement (a command that passes, a file that exists, \
a workflow that goes green) -- never "improve" or "ensure quality".
- `depends_on` lists the ids of tasks that must finish first. It may be empty. It must reference only ids \
that exist in your output and must not form a cycle.
- `effort` is S (hours), M (a day or two) or L (several days).
- Every gap flagged in the evidence (deployment gaps, test gap, missing dependency manifest) must be covered \
by at least one task, or listed in `not_addressed` with the reason it is deliberately left out.
- Stay consistent with the recommended option: do not propose decomposition work (microservices, \
event-driven, strangler) under a monolith recommendation.
- If a SPECIFICATION section is present, set `criteria_refs` to the acceptance criterion ids (e.g. "AC-1") \
the task helps satisfy; otherwise leave `criteria_refs` empty.
"""


def find_cycle(tasks: List[PlanTask]) -> List[str]:
    """Return the ids of one dependency cycle among known task ids, or [] if acyclic."""
    known = {t.id for t in tasks}
    # Self-edges are reported separately by validate_plan, so skip them here.
    deps = {t.id: [d for d in t.depends_on if d in known and d != t.id] for t in tasks}
    WHITE, GREY, BLACK = 0, 1, 2
    color = {task_id: WHITE for task_id in deps}
    stack: List[str] = []

    def visit(node: str) -> List[str]:
        color[node] = GREY
        stack.append(node)
        for nxt in deps[node]:
            if color[nxt] == GREY:
                return stack[stack.index(nxt):] + [nxt]
            if color[nxt] == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return []

    for task_id in deps:
        if color[task_id] == WHITE:
            found = visit(task_id)
            if found:
                return found
    return []


def flagged_gap_paths(evidence: dict) -> List[str]:
    """Evidence dot-paths of the gaps the scanner flagged in this repo."""
    gaps = []
    if evidence.get("deployment", {}).get("gaps"):
        gaps.append("deployment.gaps")
    if evidence.get("tests", {}).get("gap"):
        gaps.append("tests.gap")
    if "dependencies" in evidence and evidence["dependencies"].get("source_file") is None:
        gaps.append("dependencies.source_file")
    return gaps


def validate_plan(
    plan: PlanModel,
    evidence: dict,
    recommended_option: str,
    criterion_ids: List[str],
    check_citations: Callable[[List[str], dict, str], List[str]],
    repo_path: str,
) -> List[str]:
    """Deterministic checks on a generated plan. Returns warnings; never raises."""
    warnings = []
    if not plan.tasks:
        warnings.append("Plan contains no tasks.")
        return warnings

    ids = [t.id for t in plan.tasks]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        warnings.append(f"Duplicate task ids: {duplicates}.")

    known = set(ids)
    for task in plan.tasks:
        warnings.extend(f"{task.id}: {w}" for w in check_citations(task.citations, evidence, repo_path))
        if not task.acceptance_check.strip():
            warnings.append(f"{task.id}: missing acceptance check.")
        for dep in task.depends_on:
            if dep not in known:
                warnings.append(f"{task.id}: depends on unknown task {dep!r}.")
            elif dep == task.id:
                warnings.append(f"{task.id}: depends on itself.")
        for ref in task.criteria_refs:
            if ref not in criterion_ids:
                warnings.append(f"{task.id}: references unknown acceptance criterion {ref!r}.")

    cycle = find_cycle(plan.tasks)
    if cycle:
        warnings.append(f"Dependency cycle: {' -> '.join(cycle)}.")

    for gap in flagged_gap_paths(evidence):
        covered = any(t.gap_ref == gap or gap in t.citations for t in plan.tasks)
        acknowledged = any(gap in note for note in plan.not_addressed)
        if not covered and not acknowledged:
            warnings.append(f"Flagged gap {gap!r} is neither covered by a task nor listed as not addressed.")

    if recommended_option in MONOLITH_OPTIONS:
        for task in plan.tasks:
            # Title and acceptance check state what the task does; the rationale is
            # excluded because it may legitimately say "rather than microservices".
            action = f"{task.title} {task.acceptance_check}".lower()
            if any(term in action for term in DECOMPOSITION_TERMS):
                warnings.append(
                    f"{task.id}: decomposition work in {task.title!r} is inconsistent with the "
                    f"recommended option {recommended_option!r}."
                )
    return warnings
