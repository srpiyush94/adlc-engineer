# Spec 0005: CI exit code for `--scan-only`

Status: Implemented

## Problem

`--scan-only` always exits 0, so it cannot gate a pull request. A team that wants "no
secrets" or "no unpinned dependencies" enforced in CI has to parse the output itself.

## Scope

Add `--fail-on` to `--scan-only`: a comma-separated list of finding categories. The run
exits 1 when any listed category has findings. Without `--fail-on`, behavior is unchanged
(exit 0). Out of scope: baselines or "only new findings" comparison, per-category
thresholds, severity levels, SARIF or PR-comment output.

## Design

- Categories: `secrets`, `unpinned`, `complexity`, `untested`, `unused-imports`.
- `checks.failing_categories(evidence, selected)` returns the selected categories that
  have at least one finding, in the order given by `CATEGORIES`. Pure; no I/O.
- The report is always written before the exit code is decided, so CI can upload it.
- On failure, stdout lists the failing categories and counts. Exit code 1.
- Exit codes: 0 clean (or no `--fail-on`), 1 findings in a selected category, 2 usage error.

## Acceptance criteria

- AC-1. `--fail-on` accepts the five category names, comma-separated, in any order;
  surrounding spaces and repeats are tolerated.
- AC-2. An unknown category is a usage error (exit 2) that names the valid ones.
- AC-3. `--fail-on` without `--scan-only` is a usage error (exit 2).
- AC-4. With findings in a selected category, the run exits 1 and names each failing
  category with its count.
- AC-5. Findings only in categories that were not selected leave the exit code at 0.
- AC-6. With `--fail-on` and a clean repo, the exit code is 0.
- AC-7. Without `--fail-on`, the exit code is 0 even when there are findings.
- AC-8. The report file is written even when the run fails.
