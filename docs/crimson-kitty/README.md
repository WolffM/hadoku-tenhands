# crimson-kitty — design index

The third-generation contribution pipeline for vibedispatch. Coexists with
`vibecheck` and `oss-contribution` as a separate pipeline configuration in the
UI; does **not** replace them during the build phase.

Built on Temporal. Designed around the lessons from the `jade-hare` batch
(55 dispatched, 1 merged, 21% empty PRs, 3 cross-reference leaks, 18% AI-slop
callouts, 49% never reached upstream).

## North star

> Every PR we submit, we'd be willing to defend in a Hacker News thread.

## Decisions log (locked)

| # | Decision | Date |
|---|---|---|
| 1 | Workflow engine: **Temporal** (self-hosted) | 2026-04-13 |
| 2 | Cross-ref isolation: **input-context scrubbing** — strip upstream URL/slug/number from the brief before the agent sees it. Agent works directly on existing `WolffM/{repo}` forks. (Supersedes earlier "quarantine org" decision, 2026-04-13.) | 2026-04-13 |
| 3 | Agent for v1: **Copilot SWE** via a modular `Agent` adapter (cost optimization) | 2026-04-13 |
| 4 | Operator UX: **inbox model** — easy issues flow through, blocked issues queue | 2026-04-13 |
| 5 | Coexistence: **new pipeline tab** in the UI alongside vibecheck and oss-contribution; old pipelines stay forever (archival, no cutover required) | 2026-04-13 |
| 6 | Reuse philosophy: **prefer existing utilities** from vibedispatch helpers + hadoku-aggregator API; only rewrite the orchestration layer | 2026-04-13 |
| 7 | Evidence-first: **every state transition requires an artifact**, not just a timestamp | 2026-04-13 |
| 8 | Untrust the agent: **all Copilot output passes through sanitization and gates** before touching anything GitHub indexes | 2026-04-13 |
| 9 | Temporal hosting: **same WSL host, Docker Compose, pm2-managed via mgmt-api** (no unmanaged daemons) | 2026-04-13 |
| 10 | Aggregator endpoints: **add new scrapes to hadoku-aggregator** (CONTRIBUTING, PR template, issue templates, codeowners, ai labels) | 2026-04-13 |
| 11 | LLM judge: **spawn local `claude` CLI subprocess** (uses existing Claude Max subscription, no API key required) | 2026-04-13 |
| 12 | ~~Quarantine PAT~~ — **WITHDRAWN**: no new PAT needed. Pipeline uses the existing `gh` user token + `MSFT_SSO` routing in `services/github_api.py`. (Superseded when decision #2 was revised, 2026-04-13.) | 2026-04-13 |
| 13 | retro_report: **separate tool per pipeline** (`retro_report.py` for legacy, `temporal_retro_report.py` for crimson-kitty); RetroView UI gets tabs | 2026-04-13 |
| 14 | Smoke test: **first batch dispatches against your own repos** before going to external upstreams | 2026-04-13 |
| 15 | Eligibility failure: **no auto-retry** — first failure escalates to inbox | 2026-04-13 |
| 16 | Existing forks under `WolffM/*`: **delete all old jade-hare-era forks** before crimson-kitty's first run; backup fork list to JSONL first | 2026-04-13 |

## Document map

### Spec docs (how the system works today)

| Doc | Purpose |
|---|---|
| [architecture.md](architecture.md) | Five principles, Temporal rationale, system diagram, signal pattern |
| [state-machine.md](state-machine.md) | Issue states, transitions, evidence requirements per state |
| [gates.md](gates.md) | Gate registry; each jade-hare bug class mapped to its killing gate |
| [cross-ref-isolation.md](cross-ref-isolation.md) | Input-context scrubbing model, output sanitizer, leak vector mapping |
| [components.md](components.md) | Reuse map across vibedispatch, hadoku-aggregator, hadoku-scrape, hadoku-site |
| [pipeline-config.md](pipeline-config.md) | How crimson-kitty plugs into the existing pipeline-select UI |

### Forward plan

| Doc | Purpose |
|---|---|
| [phase-5-plan.md](phase-5-plan.md) | What's left between today and "ready to actually ship upstream PRs at batch scale" — five sub-phases ordered by blocking-ness |

## Status (2026-04-27)

Phases 4, 5.1, 5.2, and 5.3 are shipped. The pipeline can run end-to-end
through upstream submission and continue watching the upstream PR until
merge / close, with a remediation branch that responds to maintainer
review comments. Per-repo conventions (DCO, conventional commits,
custom close keywords) are honored automatically when the aggregator
surfaces them.

| Phase | Status |
|---|---|
| 4 — Operator-signoff loop with rich preview PR | shipped (2026-04-26) |
| 5.1 — Post-submission lifecycle + remediation loop | shipped (2026-04-27) |
| 5.2 — Local Copilot Review remediation branch | shipped (2026-04-27) |
| 5.3 — Per-repo contribution conventions | shipped (2026-04-27) |
| 5.4 — Operator inbox UI for signoff | not started |
| 5.5 — Judge calibration | not started |

Zero upstream PRs have shipped at scale yet — `submit_to_upstream`
defaults to `false` until 5.4 lands and operators can drive the
signoff loop without `curl`. The first real-world batch with the
post-submission loop active will be the production exercise of 5.1's
30-min watcher cadence + remediation cycle.

Phase 4 retrospective: B1–B26 documented in
[state/crimson-kitty/phase4-retrospective.md](../../state/crimson-kitty/phase4-retrospective.md).
