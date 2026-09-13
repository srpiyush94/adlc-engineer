# ADR 0001: Deployment Platform Selection

**Status:** Accepted (Stage 0 — personal POC). Superseding decision expected
at Stage 1 (team pilot) — see Follow-up Actions.

**Date:** 2026-09-13

## Context

`adlc-engineer` (the ADLC Engineer agent — repository analysis,
architecture modeling, modernization recommendation) needs a place to run
that a person other than the developer can reach: the CLI works locally,
but the Streamlit dashboard needs to be hosted somewhere to be shared or
demoed.

At this stage the project is a single-developer proof of concept, not a
funded or team-owned system, so the primary constraint is **$0 recurring
cost** — but the platform choice also has to not paint the project into a
corner: if this becomes a team pilot or a departmental tool handling real
(possibly proprietary) client repositories, the platform decision made
today should not force a rewrite.

Two additional constraints came from the application's own design:
- It shells out to `git clone` via `subprocess` to analyze arbitrary
  repositories (local path or GitHub URL) — the platform must allow
  spawning subprocesses and have (or allow installing) the `git` binary.
- It calls the Gemini API twice per analysis run and needs outbound
  internet access plus environment-variable/secret-based credentials.

## Decision Drivers

1. **Cost** — must be genuinely free, not a time-limited trial, given the
   project's current stage.
2. **Effort** — the smaller the operational surface (YAML, Dockerfiles,
   pipelines) required, the more likely the POC actually gets shared and
   iterated on, rather than stalling on deployment plumbing.
3. **Governance/security posture** — how much control does the platform
   give over secrets handling, access restriction, and data handling of
   whatever gets cloned and sent to the LLM.
4. **Growth path** — how much rework is needed to move this to a governed,
   audited enterprise platform (e.g. OpenShift) later, if the project earns
   that investment.

## Options Considered

All four were verified against each platform's current official
documentation (not assumed from prior knowledge, since free-tier terms
change frequently) on 2026-09-13.

### A. Streamlit Community Cloud

- Free indefinitely for public GitHub repos, no card required.
- Runs a full Debian Linux container — `git` is present; a `packages.txt`
  file can install any additional apt package if ever needed.
- Native secrets manager (`secrets.toml` in app settings) — no code changes
  needed beyond bridging `st.secrets` into `os.environ` at startup.
- Supports restricting a deployed app to specific viewer emails even on the
  free tier, addressing the risk that a fully public app would let any
  visitor burn the developer's Gemini API quota.
- Sleeps on inactivity; wakes in roughly a minute (exact threshold
  undisclosed by Streamlit — third-party figures like "15 minutes" are
  unverified estimates, not documented guarantees).
- **Zero YAML, zero Dockerfile** — the least operational surface of any
  option considered.

### B. Google Cloud Run

- Free tier is a genuine permanent monthly quota (2M requests, 360K
  GB-seconds, 1GB egress), not a trial credit.
- Full Docker container — no restriction on subprocess use or installed
  binaries.
- Real IAM-based access control, the strongest access-restriction option
  of the four.
- Requires writing and maintaining a Dockerfile and light GCP project
  setup — more operational surface than Streamlit Cloud, less than
  OpenShift.

### C. Hugging Face Spaces (Streamlit SDK)

- Free indefinitely, full Linux container, native repository secrets,
  native private-Space support.
- Comparable to Streamlit Cloud; considered a backup if Streamlit Cloud's
  undocumented resource limits prove too tight in practice.

### D. Red Hat OpenShift Developer Sandbox

- Free, no card required, and explicitly supports deploying custom Python
  apps (not just fixed templates).
- **Not an indefinite free tier**: a 30-day sandbox requiring manual
  renewal (unlimited renewals permitted).
- Requires a Dockerfile plus Kubernetes-style YAML (Deployment, Service,
  Route, Secret) — real, ongoing operational surface that the other three
  options don't require at all.
- The one option that would inherit an organization's existing OpenShift
  governance (RBAC, network policies, audit trail) *if* deployed inside an
  org-managed cluster rather than the personal Developer Sandbox — the
  Sandbox itself does not provide that governance, since it's a personal
  free trial, not an enterprise-managed cluster.

**Ruled out entirely** (confirmed via current research, not assumed):
Render (free tier now sleeps after 15 minutes idle and wipes local disk on
every spin-down — risky for a tool that writes report files to disk),
Railway (free tier replaced by a one-time trial credit), Fly.io (free tier
eliminated for new signups since Oct 2024), Cloudflare Workers (Python runs
via Pyodide/WebAssembly there — `subprocess` is not supported at all, which
would silently break the `git clone` step).

## Decision

**Deploy to Streamlit Community Cloud for the current (Stage 0, personal
POC) stage**, with the viewer allowlist restricted to the developer only
until a real access-sharing need arises.

**Containerize the application now, regardless of this choice** (a
Dockerfile that runs identically on Cloud Run and OpenShift), so that
moving to a governed platform later is additive infrastructure work, not a
rewrite.

**Explicitly defer** the OpenShift Developer Sandbox and any managed
OpenShift/Kubernetes option until the project reaches Stage 1 (team pilot)
or beyond, where the added operational overhead (Dockerfile + K8s YAML +
30-day renewal or real cluster access) is justified by an actual
governance need — not adopted now for its own sake.

## Consequences

**Positive:**
- Live, shareable deployment achievable with zero YAML and zero recurring
  cost today.
- Native secrets manager and private-viewer support close the two real
  risks identified during planning (secrets handling, quota-abuse from
  public access) without extra engineering.
- Containerizing now means the Stage 1 move to OpenShift reuses the same
  image rather than starting over.

**Negative / risks accepted, to revisit before Stage 1:**
- **Data handling is not enterprise-grade.** The Gemini API's free/consumer
  tier data-retention and training-use terms have not been verified as
  suitable for analyzing proprietary or client source code. This must be
  resolved (an enterprise API agreement, or self-hosted/other LLM with
  clear data terms) before this tool is pointed at any repository the
  developer doesn't personally own.
- Streamlit Community Cloud's exact resource limits (RAM, concurrency) are
  undocumented by Streamlit itself; if the app is throttled or evicted in
  practice, Hugging Face Spaces or Cloud Run are the pre-identified
  fallbacks.
- No audit trail, network policy control, or SSO integration — acceptable
  for a single-developer POC, not acceptable once a second team or a real
  client's code is involved.

## Follow-up Actions

- [ ] Write the Dockerfile (Cloud-Run/OpenShift-portable) — see Stage 0→1
  containerization step.
- [ ] Bridge `st.secrets` into `os.environ` at Streamlit Cloud startup.
- [ ] Restrict the deployed app's viewer list to the developer.
- [ ] Before onboarding any non-personal repository: resolve the Gemini
  API data-handling question above.
- [ ] When the project reaches Stage 1 (team pilot): open ADR 0002 to
  select and justify the Stage 1 platform (OpenShift Dev project vs.
  continuing on Cloud Run with IAM), superseding this ADR's Stage 0 scope.
