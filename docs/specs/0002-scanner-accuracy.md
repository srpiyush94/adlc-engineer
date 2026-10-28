# Spec 0002: Scanner and report accuracy fixes

Status: Implemented

## Problem

A self-scan of this repo (`--repo . --plan`) produced a report built on wrong facts:

1. The scanner walked `.claude/worktrees/...`, a duplicate copy of the repo, so it
   reported 36 Python files (15 were the copy), 10 test files (7 real), and listed the
   copy's files as hotspots. Every downstream size claim was inflated.
2. `python-dotenv` and `streamlit-mermaid` were flagged "declared but not directly
   imported" although `dotenv` and `streamlit_mermaid` are imported. The check compares
   against framework markers only, and never maps a package name to its module name.
3. Report Section 6 said "No containerization or CI/CD pipeline detected" whenever any
   deployment gap existed, contradicting Section 2 when CI workflows were present.
4. The TODO/FIXME counter matched the text "TODO" inside the scanner's own source
   (strings and docstrings), producing a false "resolve TODOs" plan task.

## Scope

Fix these four defects. Out of scope: flagging unpinned dependencies, the LLM omitting
newer modules from the component list, and recommendation quality.

## Design

- Add `.claude` to `EXCLUDED_DIRS` (agent worktrees and skills are not application source).
- `_detect_dependencies` receives every imported top-level module, not just framework
  markers. A declared package counts as imported if its normalized name, or its entry in
  a `PACKAGE_MODULE_ALIASES` map (e.g. `python-dotenv` -> `dotenv`), is among them.
- Count TODO/FIXME only in Python comment tokens (via `tokenize`), not in strings or
  docstrings. A file that fails to tokenize is skipped.
- Section 6 states each deployment gap separately: containerization missing, and CI/CD
  missing, each only when its own gap is present.

## Acceptance criteria

- AC-1. Files under `.claude/` contribute nothing to languages, frameworks, tests,
  hotspots, or coupling.
- AC-2. A declared package whose module name differs from its package name (alias map)
  is not reported as "declared but not directly imported" when the module is imported.
- AC-3. A declared package that is genuinely never imported is still reported.
- AC-4. A declared package that is imported but is not a framework marker (e.g. an
  arbitrary library) is not reported as unimported.
- AC-5. `TODO`/`FIXME` inside a comment is counted; inside a string literal or
  docstring it is not.
- AC-6. A file with a tokenize error does not crash the scan and does not stop other
  files being counted.
- AC-7. Section 6 mentions CI/CD only when the CI/CD gap is present, and
  containerization only when a Dockerfile/docker-compose gap is present.
- AC-8. A re-scan of this repo reports no `.claude/` paths anywhere in the evidence.
- AC-9. The report's Section 4 table agrees with the scanner: a package is shown as
  imported ("Yes") unless it is in `declared_but_not_directly_imported`. (Added after a
  deployed report showed `python-dotenv` as "No" in the table while the sentence below it
  correctly omitted it; the table had its own, framework-only check.)
