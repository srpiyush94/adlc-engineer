---
name: adr-writer
description: Write, supersede, or update Architecture Decision Records (ADRs) in this repo's docs/adr/ directory, using the project's context -> decision drivers -> options considered -> decision -> consequences -> follow-up actions format. Use this whenever the user wants to record a technical decision, choose between platforms/libraries/approaches and document why, write "ADR 0002", supersede or revisit an earlier ADR, or tick off follow-up actions on an existing ADR, even if they never say "ADR" (e.g. "document why we picked X", "write up this decision", "we decided to switch to Y").
---

# ADR Writer

This project keeps ADRs in `docs/adr/` for its own engineering decisions, in the same format the ADLC Engineer tool produces for repositories it analyzes. `docs/adr/0001-deployment-platform-selection.md` is the reference example: read it first so your output matches its tone, depth, and structure.

An ADR records a decision when it is made. It is not a retroactive justification, and it is not edited in place when the decision changes; it gets superseded by a new ADR. That is why the rules below exist: a future reader must be able to trust that an ADR reflects what was known and decided at the time.

## Workflow

### 1. Establish the decision

Work out from the conversation, or by asking, these things:
- What decision is being made, and what forced it now?
- What constraints exist (cost, stage of the project, technical limits of the app)?
- Which options were or should be considered? Include the ones ruled out, and why.
- What was decided? If nothing is decided yet, write the ADR as `Proposed`.

Ask only about what you cannot infer. If the user has already decided, don't re-litigate the decision; document it faithfully and put your reservations under Consequences.

### 2. Verify time-sensitive facts

Claims about pricing, free-tier limits, API terms, or version support go stale quickly, and ADR 0001 verified them against official documentation. Do the same:
- Use WebSearch/WebFetch against the vendor's own docs for each such claim.
- Write the verification date in the Options section ("verified against current official documentation on YYYY-MM-DD").
- If you can't verify a claim, keep it but label it explicitly as unverified, as ADR 0001 did for third-party sleep-timeout figures. Never state an unverified figure as fact.

Skip this step for decisions that depend on no external facts (e.g. an internal naming or module-boundary decision).

### 3. Pick the number and file name

List `docs/adr/`, take the highest number, add one, and zero-pad to four digits. File name: `NNNN-kebab-case-title.md`. The title in the H1 is `# ADR NNNN: Title`.

### 4. Write the ADR

Use this structure. Match the density of ADR 0001: specific and concrete, no filler.

```markdown
# ADR NNNN: <Title>

**Status:** Proposed | Accepted | Superseded by ADR NNNN
(add scope/stage note if relevant)

**Date:** YYYY-MM-DD   <- today's date

## Context
What is being built, what forced this decision, what constraints are real.
Name constraints that come from the application's own design.

## Decision Drivers
Numbered, each with a bolded name and one sentence on why it matters.

## Options Considered
One `### A. Name` subsection per option with concrete bullets (cost,
limits, effort, risks). End with a "Ruled out entirely" paragraph for
options eliminated early, each with its reason.

## Decision
Bold the decision. State what is explicitly deferred and the trigger for
revisiting it.

## Consequences
**Positive:** ...
**Negative / risks accepted, to revisit before <milestone>:** ...
Be honest: unresolved risks belong here, not hidden.

## Follow-up Actions
- [ ] Checkbox per concrete next step. Include the trigger for the
  successor ADR if the decision is stage-scoped.
```

Writing principles:
- State the *why* behind each option's rejection, not just that it lost.
- Record risks you are knowingly accepting; an ADR that lists only upsides is not trustworthy.
- Prefer concrete facts and numbers over adjectives.

### 5. Update the index

Add a row to the table in `docs/adr/README.md`:
`| [NNNN](file.md) | Title | Status |`
Keep the table sorted by number.

### 6. Superseding an earlier ADR

When a decision changes:
- Write the new ADR with its own context explaining what changed.
- In the old ADR, change only the Status line to `Superseded by ADR NNNN` (plus a link). Leave the body untouched, since it is the historical record.
- Update the status in the README index for both rows.

### 7. Updating follow-up actions

The one thing you *do* edit in an existing ADR is the follow-up checklist. When an action is completed, change `[ ]` to `[x]` and append what was done, where (URL or commit), and the date, as ADR 0001 did for the secrets bridge. Do not alter Context, Options, or Decision.

## Before finishing

- Date is today's date; number does not collide with an existing file.
- Every external claim is either verified (with date) or labeled unverified.
- Consequences include real negatives.
- README index updated.
- Tell the user the file path and summarize any unverified claims or open risks you recorded. Don't commit unless asked.