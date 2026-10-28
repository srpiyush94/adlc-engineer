# Spec 0004: Deterministic code-health checks and a no-LLM scan mode

Status: Implemented

## Problem

For team use, the findings must be reproducible and trustworthy, and the tool must be
usable on code that may not be sent to an external LLM API. Today the scanner reports
languages, frameworks, deployment gaps, a test-file count, TODOs and bare excepts. The
valuable analysis (what an LLM cannot reliably do) is missing, and every run needs a
Gemini key and sends repository content to Google.

## Scope

Add five static checks to the scanner and a `--scan-only` mode that renders them with
zero LLM calls. Python repositories only, as the scanner already is.

Out of scope (separate specs): outdated or vulnerable dependency lookup (needs network),
real test coverage (requires executing the repo's code), dead-function detection, CI exit
codes, non-Python languages, `pyproject.toml`/`package.json` dependency parsing.

## Checks

1. **Unpinned dependencies.** `requirements.txt` lines that are not pinned with `==`,
   and whether a lockfile exists (`poetry.lock`, `Pipfile.lock`, `uv.lock`, `pdm.lock`).
   Option lines such as `-r other.txt` are not dependencies.
2. **Secrets.** High-precision patterns for credentials in text files (AWS access key id,
   Google API key, GitHub token, Slack token, private key blocks, and quoted
   `api_key/secret/token/password` assignments that are not obvious placeholders), plus
   sensitive files (`.env`, `*.pem`, `id_rsa`, `credentials.json`) that git tracks. Values
   are masked in the evidence; a full secret is never stored or printed.
3. **Complexity.** Cyclomatic complexity per function and function length. Report the
   functions at or above a threshold, worst first.
4. **Untested modules.** Source modules that no test file imports directly. A static
   heuristic, labelled as such; it is not coverage.
5. **Unused imports.** Imported names never used in the file.

Unpinned dependencies and secrets are added to the gaps the implementation plan must
cover. The other three are informational.

## `--scan-only`

Runs the scanner and renders a Markdown report of the deterministic findings, with the
evidence JSON appended. No LLM call is made, no API key is required, and nothing leaves
the machine. Output is identical across runs on an unchanged repository.

## Acceptance criteria

- AC-1. A requirement not pinned with `==` is listed under `dependencies.unpinned`; exact
  pins are not; `-r`/`-e`/`--` option lines are neither dependencies nor unpinned.
- AC-2. `dependencies.has_lockfile` is true only when a known lockfile exists.
- AC-3. Each secret pattern is detected in a text file, with path, line and kind.
- AC-4. Evidence never contains a full secret value, only a masked preview.
- AC-5. Placeholder values (`your_key_here`, `changeme`, `${VAR}`, `<token>`, `xxxx`,
  `example`) are not reported as secrets.
- AC-6. A sensitive file is reported only when git tracks it; an ignored `.env` is not
  reported, and a non-git directory reports none.
- AC-7. Cyclomatic complexity counts branches, loops, handlers, boolean operators,
  conditional expressions and comprehensions; nested functions are measured separately;
  only functions at or above the threshold are listed, worst first, ties broken by path.
- AC-8. A source module imported by no test file is listed as untested; test files and
  `__init__.py` are never listed; a module imported by a test (`import a.b`,
  `from a import b`, `from a.b import c`) is not.
- AC-9. An import never referenced in its file is listed; used imports, `__init__.py`
  re-exports, `__future__` imports and lines marked `noqa` are not.
- AC-10. Findings are deterministic: sorted, with bounded list sizes.
- AC-11. The report's code-health section shows each finding with file and line, and a
  clear "none found" for a clean check.
- AC-12. `--scan-only` makes no LLM call, needs no API key, writes the report, and
  produces identical output on two consecutive runs. It cannot be combined with
  `--plan`, `--challenge`, `--requirement` or `--write-adr` (the CLI rejects it).
- AC-13. Unpinned dependencies and secrets are among the gaps `validate_plan` requires a
  plan to cover.
- AC-14. A scan of this repository reports no secrets (its own tests build fake
  credentials at runtime so the scanner does not flag itself).
