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

| Doc | Purpose |
|---|---|
| [architecture.md](architecture.md) | Five principles, Temporal rationale, system diagram |
| [state-machine.md](state-machine.md) | Issue states, transitions, evidence requirements per state |
| [gates.md](gates.md) | Gate registry; each jade-hare bug class mapped to its killing gate |
| [cross-ref-isolation.md](cross-ref-isolation.md) | Input-context scrubbing model, output sanitizer, leak vector mapping |
| [components.md](components.md) | Reuse map across vibedispatch, hadoku-aggregator, hadoku-scrape, hadoku-site |
| [pipeline-config.md](pipeline-config.md) | How crimson-kitty plugs into the existing pipeline-select UI |
| [phase-1-plan.md](phase-1-plan.md) | Ordered build plan with exit criteria per phase |
| [open-questions.md](open-questions.md) | All 10 original questions resolved; 5 follow-ups (F1-F5) outstanding |

## Status

**Phase 0 — Design (complete) → prerequisites (in progress)**
- ✓ Design docs written
- ✓ Backend `temporal/` directory scaffolded
- ✓ Frontend `temporal/` components scaffolded
- ✓ All 10 original open questions resolved
- ⏳ 5 follow-up questions outstanding (F1-F5 in [open-questions.md](open-questions.md))
- ⏳ Phase 0 prereqs (legacy fork cleanup, aggregator endpoint deploy, claude CLI on prod) — see [phase-1-plan.md](phase-1-plan.md#phase-0--prerequisites)

Next: answer F1-F4, then begin Phase 1.
