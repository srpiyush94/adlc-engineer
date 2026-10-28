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


def _render_dependency_map(evidence, number=4):
    deps = evidence.get("dependencies", {})
    declared = deps.get("declared", [])
    frameworks = evidence.get("frameworks", {})
    lines = [f"## {number}. Dependency Map\n"]
    if not declared:
        lines.append(f"_No dependency manifest found (checked: {deps.get('source_file') or 'requirements.txt'})._\n")
    else:
        lines.append("| Declared Dependency | Directly Imported? |")
        lines.append("|---|---|")
        not_imported = deps.get("declared_but_not_directly_imported")
        for name in declared:
            if not_imported is not None:
                # The scanner knows about aliases (python-dotenv -> dotenv) and non-framework imports.
                imported = "No" if name in not_imported else "Yes"
            else:
                imported = "Yes" if name.lower().replace("-", "_") in frameworks else "No"
            lines.append(f"| {name} | {imported} |")
        not_imported = not_imported or []
        if not_imported:
            lines.append("")
            lines.append(
                "Declared but not directly imported (may be transitive or unused): "
                + ", ".join(f"`{n}`" for n in not_imported)
            )
    return "\n".join(lines) + "\n"


def _render_architectural_problems(evidence, number=5):
    hotspots = evidence.get("hotspots", {})
    tests = evidence.get("tests", {})
    deployment = evidence.get("deployment", {})
    coupling = evidence.get("coupling", {})
    lines = [f"## {number}. Architectural Problems\n"]

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
    lines.append("")

    lines.extend(_code_health_lines(evidence))
    return "\n".join(lines).rstrip("\n") + "\n"


def _code_health_lines(evidence) -> list:
    """Deterministic checks (spec 0004). A check absent from older evidence is skipped;
    a check that ran and found nothing says so."""
    lines = []
    dependencies = evidence.get("dependencies", {})
    if "unpinned" in dependencies and dependencies.get("source_file"):
        unpinned = dependencies["unpinned"]
        lockfile = "a lockfile is present" if dependencies.get("has_lockfile") else "no lockfile found"
        if unpinned:
            lines.append(
                f"**Unpinned dependencies:** {len(unpinned)} of {len(dependencies.get('declared', []))} "
                f"requirement(s) are not pinned with `==` ({lockfile}) — "
                + ", ".join(f"`{n}`" for n in unpinned)
            )
        else:
            lines.append(f"**Unpinned dependencies:** none — every requirement is pinned ({lockfile}).")
        lines.append("")

    secrets = evidence.get("secrets")
    if secrets is not None:
        if not secrets.get("count"):
            lines.append("**Secrets:** none found.")
        else:
            lines.append(f"**Secrets:** {secrets['count']} potential credential(s) found (values masked):")
            for f in secrets.get("findings", []):
                lines.append(f"- `{f['path']}:{f['line']}` — {f['kind']}: `{f['preview']}`")
            for path in secrets.get("tracked_sensitive_files", []):
                lines.append(f"- `{path}` — sensitive file tracked by git")
            shown = len(secrets.get("findings", [])) + len(secrets.get("tracked_sensitive_files", []))
            if secrets["count"] > shown:
                lines.append(f"- … and {secrets['count'] - shown} more.")
        lines.append("")

    complexity = evidence.get("complexity")
    if complexity is not None:
        if not complexity.get("count"):
            lines.append(f"**Complexity hotspots:** no function at or above complexity {complexity['threshold']}.")
        else:
            lines.append(
                f"**Complexity hotspots:** {complexity['count']} function(s) at or above cyclomatic "
                f"complexity {complexity['threshold']} (worst first):"
            )
            for f in complexity.get("functions", []):
                lines.append(f"- `{f['path']}:{f['line']}` `{f['name']}` — complexity {f['complexity']}, {f['lines']} lines")
        lines.append("")

    untested = evidence.get("untested_modules")
    if untested is not None:
        if not untested.get("count"):
            lines.append("**Untested modules:** every source module is imported by a test.")
        else:
            lines.append(
                f"**Untested modules:** {untested['count']} of {untested['source_modules']} source module(s) "
                f"are not imported by any test _(static heuristic, not coverage)_:"
            )
            lines.extend(f"- `{m}`" for m in untested.get("modules", []))
        lines.append("")

    unused = evidence.get("unused_imports")
    if unused is not None:
        if not unused.get("count"):
            lines.append("**Unused imports:** none found.")
        else:
            lines.append(f"**Unused imports:** {unused['count']} found:")
            lines.extend(f"- `{item}`" for item in unused.get("items", []))
            if unused["count"] > len(unused.get("items", [])):
                lines.append(f"- … and {unused['count'] - len(unused['items'])} more.")
        lines.append("")
    return lines


def _render_constraints(evidence):
    deployment = evidence.get("deployment", {})
    lines = ["## 6. Business/Technical Constraints\n"]
    lines.append(
        "**Business constraints:** Unknown — this is a self-analysis run with no external "
        "requirements document provided.\n"
    )
    technical_notes = []
    gaps = deployment.get("gaps", [])
    if any(g.startswith(("No Dockerfile", "No docker-compose")) for g in gaps):
        technical_notes.append("No containerization detected, limiting safe, repeatable deploys.")
    if any("CI/CD" in g for g in gaps):
        technical_notes.append("No CI/CD pipeline detected, limiting automated checks and releases.")
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


_CHALLENGER_PERSONA_ORDER = ["Security", "Scalability", "Cost", "Reliability", "Implementation"]


def _render_challenger_review(challenger: dict, modernization: dict, section_number: int) -> str:
    reviews = challenger.get("reviews", {})
    lines = [f"## {section_number}. Architecture Challenger Review\n"]
    lines.append(
        f"The recommended option (**{modernization.get('recommended_option', 'not determined')}**) was "
        "reviewed by a five-persona challenge panel, each citing evidence for their finding.\n"
    )
    for persona in _CHALLENGER_PERSONA_ORDER:
        finding = reviews.get(persona, {})
        lines.append(f"### {persona}")
        objection = "Yes" if finding.get("has_objection") else "No"
        lines.append(f"- **Objection raised:** {objection} (severity: {finding.get('severity', 'none')})")
        lines.append(f"- **Finding:** {finding.get('summary', '_no summary provided_')}")
        lines.append(f"- **Citations:** {_fmt_citations(finding.get('citations', []))}")
        concerns = finding.get("concerns") or []
        if concerns:
            lines.append("- **Concerns:**")
            for concern in concerns:
                lines.append(
                    f"  - {concern['description']} — {_fmt_citations(concern.get('citations', []))}"
                )
        else:
            lines.append("- **Concerns:** _none listed_")
        if finding.get("citation_warnings"):
            lines.append(f"- **Citation warnings:** {'; '.join(finding['citation_warnings'])}")
        lines.append("")

    if challenger.get("has_objections"):
        objecting = ", ".join(challenger.get("objecting_personas", [])) or "unspecified"
        lines.append(f"**Panel verdict:** Objection(s) raised by: {objecting}.\n")
        if modernization.get("revised"):
            lines.append(
                "**Architect's revision:** The recommendation was revised once in response to these "
                "objections (by design, no further re-review pass is performed).\n"
            )
            lines.append(modernization.get("revision_notes") or "_no revision notes provided_")
        else:
            lines.append("_The recommendation was not revised (revision step did not run)._")
    else:
        lines.append(
            "**Panel verdict:** No reviewer raised an objection; the original recommendation stands unchanged."
        )
    return "\n".join(lines) + "\n"


def _render_specification(specification: dict, modernization: dict, section_number: int) -> str:
    lines = [f"## {section_number}. Specification & Acceptance Criteria\n"]
    lines.append("**Business requirement (as supplied):**\n")
    lines.append(f"> {specification.get('requirement_text', '')}\n")

    lines.append("### Derived Constraints\n")
    constraints = specification.get("constraints", [])
    if not constraints:
        lines.append("_No constraints derived._\n")
    else:
        for c in constraints:
            lines.append(f"- {c['description']} — {_fmt_citations(c.get('citations', []))}")
        lines.append("")

    lines.append("### Acceptance Criteria\n")
    criteria = specification.get("acceptance_criteria", [])
    if not criteria:
        lines.append("_No acceptance criteria derived._\n")
    else:
        for ac in criteria:
            lines.append(f"- **{ac['id']}**: {ac['description']} — {_fmt_citations(ac.get('citations', []))}")
        lines.append("")

    recommended_name = modernization.get("recommended_option", "not determined")
    lines.append(f"### Compliance Assessment — Recommended Option: {recommended_name}\n")
    assessments = modernization.get("compliance_assessment") or []
    if not assessments:
        lines.append("_No compliance assessment available for the recommended option._\n")
    else:
        by_id = {ac["id"]: ac["description"] for ac in criteria}
        lines.append("| Criterion | Description | Status | Reasoning | Citations |")
        lines.append("|---|---|---|---|---|")
        for a in assessments:
            desc = by_id.get(a["criterion_id"], "_unknown criterion_")
            lines.append(
                f"| {a['criterion_id']} | {desc} | {a['status']} | {a['reasoning']} | "
                f"{_fmt_citations(a.get('citations', []))} |"
            )
        lines.append("")

    if specification.get("citation_warnings"):
        lines.append("**Citation warnings:**")
        for w in specification["citation_warnings"]:
            lines.append(f"- {w}")
    return "\n".join(lines) + "\n"


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _render_plan(plan: dict, section_number: int) -> str:
    lines = [f"## {section_number}. Implementation Plan\n"]
    tasks = plan.get("tasks", [])
    if not tasks:
        lines.append("_No tasks generated._\n")
    else:
        has_criteria = any(t.get("criteria_refs") for t in tasks)
        header = "| ID | Task | Closes gap | Acceptance check | Depends on | Effort |"
        divider = "|---|---|---|---|---|---|"
        if has_criteria:
            header += " Criteria |"
            divider += "---|"
        header += " Citations |"
        divider += "---|"
        lines.extend([header, divider])
        for t in tasks:
            row = (
                f"| {_cell(t['id'])} | **{_cell(t['title'])}** — {_cell(t['rationale'])} | `{_cell(t['gap_ref'])}` | "
                f"{_cell(t['acceptance_check'])} | {_cell(', '.join(t['depends_on'])) or '—'} | {_cell(t['effort'])} |"
            )
            if has_criteria:
                row += f" {_cell(', '.join(t.get('criteria_refs', []))) or '—'} |"
            row += f" {_fmt_citations(t.get('citations', []))} |"
            lines.append(row)
        lines.append("")

    if plan.get("not_addressed"):
        lines.append("**Deliberately not addressed:**")
        for note in plan["not_addressed"]:
            lines.append(f"- {note}")
        lines.append("")

    if plan.get("citation_warnings"):
        lines.append("**Plan warnings:**")
        for w in plan["citation_warnings"]:
            lines.append(f"- {w}")
    return "\n".join(lines) + "\n"


def render_scan_report(evidence: dict, repo_display_name: str) -> str:
    """Report of the deterministic findings only. Makes no LLM call and contains no
    timestamps, so two runs on an unchanged repository are identical."""
    languages = ", ".join(f"{name} ({d['files']} files, {d['loc']} LOC)" for name, d in evidence.get("languages", {}).items())
    deps = evidence.get("dependencies", {})
    summary = [
        ("Unpinned dependencies", len(deps.get("unpinned", []))),
        ("Potential secrets", evidence.get("secrets", {}).get("count", 0)),
        ("Functions over the complexity threshold", evidence.get("complexity", {}).get("count", 0)),
        ("Source modules not imported by any test", evidence.get("untested_modules", {}).get("count", 0)),
        ("Unused imports", evidence.get("unused_imports", {}).get("count", 0)),
        ("Deployment gaps", len(evidence.get("deployment", {}).get("gaps", []))),
        ("Test files", evidence.get("tests", {}).get("count", 0)),
    ]
    sections = [
        f"# ADLC Engineer — Deterministic Scan\n\n**Repository:** {repo_display_name}\n\n"
        "_No LLM was used: every finding below comes from static analysis of the repository._\n",
        "## 1. Summary\n\n" + (f"{languages}\n\n" if languages else "")
        + "| Check | Count |\n|---|---|\n" + "\n".join(f"| {label} | {count} |" for label, count in summary) + "\n",
        _render_dependency_map(evidence, 2),
        _render_architectural_problems(evidence, 3),
        _render_appendix(evidence),
    ]
    return "\n".join(sections)


def _render_appendix(evidence):
    return "## Appendix A: Evidence Data\n\n```json\n" + json.dumps(evidence, indent=2) + "\n```\n"


def render_report(
    evidence: dict,
    architecture_model: dict,
    modernization: dict,
    repo_display_name: str,
    challenger: dict = None,
    specification: dict = None,
    plan: dict = None,
) -> str:
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
    ]

    optional_sections = []
    if specification is not None:
        optional_sections.append((_render_specification, (specification, modernization)))
    if challenger is not None:
        optional_sections.append((_render_challenger_review, (challenger, modernization)))
    if plan is not None:
        optional_sections.append((_render_plan, (plan,)))

    next_number = 16
    for render_fn, args in optional_sections:
        sections.append(render_fn(*args, next_number))
        next_number += 1

    sections.append(_render_appendix(evidence))
    return "\n".join(sections)
