"""Pure Markdown report assembly. No LLM calls, no filesystem I/O."""

import json

SECTION_15_REFRAME_NOTE = (
    "Section 15 is reframed from \"Requirements -> Architecture\" to "
    "\"Evidence -> Architecture Claim -> Modernization Option\" because this is a "
    "repository self-analysis run with no external business-requirements document provided."
)


def _fmt_citations(citations):
    if not citations:
        return "_no citations provided_"
    return ", ".join(f"`{c}`" for c in citations)


def _render_executive_summary(evidence, modernization):
    languages = evidence.get("languages", {})
    lang_summary = ", ".join(
        f"{name} ({stats['files']} files, {stats['loc']} LOC)"
        for name, stats in sorted(languages.items(), key=lambda kv: -kv[1]["loc"])
    ) or "no recognized source languages found"
    pattern = evidence.get("architecture_pattern_guess", {}).get("pattern", "undetermined from evidence")
    recommended = modernization.get("recommended_option", "not determined")
    return (
        "## 1. Executive Summary\n\n"
        f"This repository contains {lang_summary}. Its architecture pattern, based on scanned evidence, "
        f"is best described as **{pattern}**. The recommended modernization path is "
        f"**{recommended}** (see Section 9 for details).\n"
    )


def _render_current_architecture(architecture_model):
    return (
        "## 2. Current Architecture\n\n"
        f"{architecture_model['narrative']}\n\n"
        "```mermaid\n"
        f"{architecture_model['mermaid']}\n"
        "```\n"
    )


def _render_system_components(architecture_model):
    lines = ["## 3. System Components\n"]
    for component in architecture_model.get("components", []):
        lines.append(f"- **{component['name']}** — {_fmt_citations(component.get('grounded_in', []))}")
    return "\n".join(lines) + "\n"


def _render_dependency_map(evidence):
    deps = evidence.get("dependencies", {})
    declared = deps.get("declared", [])
    frameworks = evidence.get("frameworks", {})
    lines = ["## 4. Dependency Map\n"]
    if not declared:
        lines.append(f"_No dependency manifest found (checked: {deps.get('source_file') or 'requirements.txt'})._\n")
    else:
        lines.append("| Declared Dependency | Directly Imported? |")
        lines.append("|---|---|")
        for name in declared:
            imported = "Yes" if name.lower().replace("-", "_") in frameworks else "No"
            lines.append(f"| {name} | {imported} |")
        not_imported = deps.get("declared_but_not_directly_imported", [])
        if not_imported:
            lines.append("")
            lines.append(
                "Declared but not directly imported (may be transitive or unused): "
                + ", ".join(f"`{n}`" for n in not_imported)
            )
    return "\n".join(lines) + "\n"


def _render_architectural_problems(evidence):
    hotspots = evidence.get("hotspots", {})
    tests = evidence.get("tests", {})
    deployment = evidence.get("deployment", {})
    coupling = evidence.get("coupling", {})
    lines = ["## 5. Architectural Problems\n"]

    largest = hotspots.get("largest_files", [])
    if largest:
        lines.append("**Largest files (potential hotspots):**")
        for entry in largest:
            lines.append(f"- `{entry['path']}` — {entry['loc']} LOC")
        lines.append("")

    if hotspots.get("bare_except_count", 0):
        lines.append(
            f"**Bare `except:` clauses:** {hotspots['bare_except_count']} found — "
            f"{_fmt_citations(hotspots.get('bare_except_locations', []))}"
        )
        lines.append("")

    if hotspots.get("todo_fixme_count", 0):
        lines.append(f"**TODO/FIXME markers:** {hotspots['todo_fixme_count']} found.")
        lines.append("")

    if tests.get("gap"):
        lines.append(f"**Test coverage gap:** {tests['gap']}")
        lines.append("")

    if deployment.get("gaps"):
        lines.append("**Deployment gaps:**")
        for gap in deployment["gaps"]:
            lines.append(f"- {gap}")
        lines.append("")

    if coupling:
        lines.append(f"**Local module coupling:** {len(coupling)} file(s) import other local modules directly.")
    else:
        lines.append("**Local module coupling:** no local cross-module imports detected.")

    return "\n".join(lines) + "\n"


def _render_constraints(evidence):
    deployment = evidence.get("deployment", {})
    lines = ["## 6. Business/Technical Constraints\n"]
    lines.append(
        "**Business constraints:** Unknown — this is a self-analysis run with no external "
        "requirements document provided.\n"
    )
    technical_notes = []
    if deployment.get("gaps"):
        technical_notes.append("No containerization or CI/CD pipeline detected, limiting safe, repeatable deploys.")
    if evidence.get("tests", {}).get("count", 0) == 0:
        technical_notes.append("No automated tests detected, limiting safe refactoring velocity.")
    if not technical_notes:
        technical_notes.append("No significant technical constraints observed in evidence.")
    lines.append("**Technical constraints:**")
    for note in technical_notes:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def _render_nfrs(evidence):
    integrations = evidence.get("integrations", {})
    lines = ["## 7. Non-Functional Requirements\n"]
    if integrations.get("external_sdks", {}).get("langfuse"):
        lines.append("- **Observability:** Langfuse tracing integration detected — evidenced.")
    else:
        lines.append("- **Observability:** Not evidenced.")
    lines.append("- **Performance/Scalability targets:** Not evidenced.")
    lines.append("- **Availability targets:** Not evidenced.")
    lines.append("- **Security requirements:** Not evidenced.")
    return "\n".join(lines) + "\n"


def _render_modernization_options(modernization):
    lines = ["## 8. Modernization Options\n"]
    lines.append("| Option | Cost | Risk | Complexity | Scalability | Recommendation |")
    lines.append("|---|---|---|---|---|---|")
    for option in modernization.get("options", []):
        lines.append(
            f"| {option['name']} | {option['cost']} | {option['risk']} | "
            f"{option['complexity']} | {option['scalability']} | {option['recommendation']} |"
        )
    lines.append("")
    for option in modernization.get("options", []):
        lines.append(f"**{option['name']}** — {option['reasoning']} ({_fmt_citations(option.get('citations', []))})")
        lines.append("")
    return "\n".join(lines) + "\n"


def _render_recommended_architecture(modernization):
    recommended_name = modernization.get("recommended_option", "not determined")
    matching = next(
        (o for o in modernization.get("options", []) if o["name"] == recommended_name), None
    )
    lines = ["## 9. Recommended Architecture\n"]
    lines.append(f"**Recommended option:** {recommended_name}\n")
    if matching:
        lines.append(matching["reasoning"])
        lines.append("")
        lines.append(_fmt_citations(matching.get("citations", [])))
    return "\n".join(lines) + "\n"


def _render_adr(modernization):
    return "## 10. Architecture Decision Record (ADR)\n\n" + modernization.get("adr", "") + "\n"


def _render_migration_roadmap(modernization):
    lines = ["## 11. Migration Roadmap\n"]
    for i, step in enumerate(modernization.get("migration_roadmap", []), start=1):
        lines.append(f"{i}. {step}")
    return "\n".join(lines) + "\n"


def _render_risks(modernization):
    lines = ["## 12. Risks\n"]
    for risk in modernization.get("risks", []):
        lines.append(f"- {risk}")
    return "\n".join(lines) + "\n"


def _render_assumptions(modernization, architecture_model):
    lines = ["## 13. Assumptions\n"]
    for assumption in modernization.get("assumptions", []):
        lines.append(f"- {assumption}")
    lines.append(f"- {SECTION_15_REFRAME_NOTE}")

    all_warnings = architecture_model.get("citation_warnings", []) + modernization.get("citation_warnings", [])
    if all_warnings:
        lines.append("")
        lines.append("**Citation warnings (claims that could not be fully grounded in evidence):**")
        for warning in all_warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"


def _render_validation_plan(evidence):
    lines = ["## 14. Validation Plan\n"]
    lines.append("- Confirm each citation in Sections 2-3 and 8-9 resolves against Appendix A.")
    if evidence.get("tests", {}).get("count", 0) == 0:
        lines.append("- Add automated tests, then run the test suite as part of validating any change.")
    else:
        lines.append("- Run the existing test suite as part of validating any change.")
    lines.append("- Render the Mermaid diagram in Section 2 to confirm it is syntactically valid.")
    lines.append("- Re-run this tool after making changes and diff the two reports.")
    return "\n".join(lines) + "\n"


def _render_traceability(architecture_model, modernization):
    lines = ["## 15. Traceability (Evidence -> Architecture Claim -> Modernization Option)\n"]
    lines.append(f"_{SECTION_15_REFRAME_NOTE}_\n")
    lines.append("| Architecture Claim | Evidence | Related Modernization Option |")
    lines.append("|---|---|---|")
    recommended = modernization.get("recommended_option", "")
    for component in architecture_model.get("components", []):
        lines.append(
            f"| {component['name']} | {_fmt_citations(component.get('grounded_in', []))} | {recommended} |"
        )
    return "\n".join(lines) + "\n"


def _render_appendix(evidence):
    return "## Appendix A: Evidence Data\n\n```json\n" + json.dumps(evidence, indent=2) + "\n```\n"


def render_report(evidence: dict, architecture_model: dict, modernization: dict, repo_display_name: str) -> str:
    sections = [
        f"# ADLC Engineer — Architecture & Modernization Report\n\n**Repository:** {repo_display_name}\n",
        _render_executive_summary(evidence, modernization),
        _render_current_architecture(architecture_model),
        _render_system_components(architecture_model),
        _render_dependency_map(evidence),
        _render_architectural_problems(evidence),
        _render_constraints(evidence),
        _render_nfrs(evidence),
        _render_modernization_options(modernization),
        _render_recommended_architecture(modernization),
        _render_adr(modernization),
        _render_migration_roadmap(modernization),
        _render_risks(modernization),
        _render_assumptions(modernization, architecture_model),
        _render_validation_plan(evidence),
        _render_traceability(architecture_model, modernization),
        _render_appendix(evidence),
    ]
    return "\n".join(sections)
