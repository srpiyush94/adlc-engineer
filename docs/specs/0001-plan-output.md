# Spec 0001: Implementation plan output (`--plan`) and ADR file output (`--write-adr`)

Status: Proposed

## Problem

The report ends at the recommended modernization option plus a `migration_roadmap`
that is a plain list of strings. Nothing in it is ordered, testable, or traceable
to the evidence that triggered it, and the decision (ADR) exists only inside the
report Markdown, not in the repo's `docs/adr/` records.

## Scope

1. `--plan`: generate an ordered, evidence-linked task list.
2. `--write-adr`: persist the generated ADR as a file in `docs/adr/`.

Out of scope: CI exit-code mode, dashboard changes, auto-implementing tasks.

## Design

Both features are opt-in and default off; with both off the pipeline is unchanged
(2 LLM calls).

### `--plan`
- State: `run_plan: bool`, `plan: dict`.
- New node `generate_plan` runs after `propose_modernization` (or after
  `revise_modernization` when the Challenger revised it) and before
  `assemble_report`. Adds 1 LLM call.
- Models:
  - `PlanTask`: `id` (T-1, T-2, ...), `title`, `rationale`, `gap_ref` (evidence key),
    `acceptance_check` (verifiable statement), `depends_on: List[str]`,
    `effort: S|M|L`, `citations: List[str]`.
  - `PlanModel`: `tasks: List[PlanTask]`.
- Granularity: each task is sized for one pull request; 5-10 tasks by default.
- Citations are verified with the existing `check_citations`; unresolved ones are
  reported as warnings, as for other sections.
- Report gets an "Implementation Plan" section: ordered table including dependencies.

### `--write-adr`
- Requires the analyzed repo to be a local path. For a git URL (temporary clone)
  the flag is ignored with a printed warning, since the file would be discarded.
- Writes `docs/adr/NNNN-<slug>.md` where NNNN is the next free number.
- Never overwrites an existing file; never edits an existing ADR in place.
- Updates the index table in `docs/adr/README.md` if present.
- New ADR status is `Proposed` (machine-written, pending human review).
- Independent of `--plan`; either can be used alone.

## Acceptance criteria

- AC-1. With neither flag, output and LLM call count are unchanged.
- AC-2. With `--plan`, the report has an Implementation Plan section; every task has
  an id, an acceptance check, and at least one citation.
- AC-3. Every `depends_on` id refers to an existing task and the dependency graph is
  acyclic; a violation produces a report warning, not a crash.
- AC-4. Every scanner-flagged gap is covered by at least one task or listed as
  deliberately not addressed.
- AC-5. Tasks are consistent with the recommended option (no microservice-split task
  under "Modernize monolith").
- AC-6. `--plan` works with `--challenge` and `--requirement`; when a specification
  exists, tasks may reference AC ids.
- AC-7. With `--write-adr` on a local repo, a new numbered ADR file is created with
  status `Proposed`, and the README index gains a row.
- AC-8. `--write-adr` never overwrites or modifies an existing ADR file.
- AC-9. `--write-adr` on a git URL writes nothing and prints a warning.
- AC-10. Unit tests with a mocked LLM cover routing, model validation, the cycle
  check, rendering, ADR numbering and the no-overwrite rule.
