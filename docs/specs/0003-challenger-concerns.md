# Spec 0003: Challenger reviewers list at least one concern

Status: Implemented

## Problem

In a deployed `--challenge` run, all five reviewers answered "no objection" with generic
praise. None mentioned real, evidenced weaknesses (unpinned dependencies, no container
setup as a reliability gap). The prompt forbids manufacturing objections, which is right,
but it leaves "no objection" as a way to say nothing. A panel that never surfaces a
residual risk gives little signal.

## Scope

Each reviewer must always report at least one **concern**: a residual risk, caveat, or
follow-up the recommendation does not fully address from that reviewer's lens. Concerns
are distinct from objections. Out of scope: feeding concerns into the revision step, the
plan, or the ADR; changing what counts as an objection.

## Design

- New model `ReviewConcern`: `description`, `citations`.
- `ReviewFinding` gains `concerns: List[ReviewConcern]`.
- Reviewer prompt adds a rule: list at least one concern even when `has_objection` is
  false; a concern is below the bar for an objection but worth tracking; it must be
  specific to this repository and cite evidence in its own `citations`; pick the real
  weakest point rather than inventing one. The existing "do not manufacture an
  objection" rule stays.
- The reviewer node warns, without failing, when `concerns` is empty or a concern's
  citation does not resolve. Warnings go into the finding's `citation_warnings`.
- `has_objection`, `aggregate_reviews`, and routing are unchanged: a concern alone never
  triggers a revision.
- The report's Challenger section lists each persona's concerns with citations.

## Acceptance criteria

- AC-1. A reviewer finding carries `concerns`, each with a description and citations.
- AC-2. The reviewer prompt requires at least one concern when there is no objection,
  distinguishes a concern from an objection, requires evidence citations on concerns,
  and still forbids manufacturing objections.
- AC-3. Concerns never change `has_objection`, the panel verdict, or routing: five
  no-objection findings with concerns still skip the revision step.
- AC-4. A finding with no concerns produces a warning for that persona, not an error.
- AC-5. A concern citing evidence that does not resolve produces a warning.
- AC-6. The report shows every persona's concerns with their citations, and a placeholder
  when a persona listed none.
- AC-7. Runs without `--challenge` are unchanged (no extra LLM calls).
