# TenHands

An orchestration layer for dispatching coding agents at real work — and for
earning the right to ship what they produce. The numbers that shaped it: the
**jade-hare** batch (March 2026) dispatched **55 issues and merged 1** upstream,
with 21% empty PRs and 3 accidental cross-reference notifications to
maintainers. That postmortem funded a retrospective system, which funded
**crimson-kitty** — an evidence-gated Temporal pipeline where every state
transition requires an artifact and nothing touches upstream without explicit
human signoff — which in turn became **taskauto**, a board-driven pipeline that
ships unattended commits to this repo's own `main` (7 on its first day, each
gated on the full test suite passing against the merge result).

> **North star:** every PR we submit, we'd be willing to defend in a public
> thread.

## The story

The full arc is in [docs/HISTORY.md](docs/HISTORY.md). The short version:

| Era | When | The lesson it bought |
|---|---|---|
| vibedispatch / vibecheck | Jan 2026 | Generating work for agents is the easy half; deciding what's worth doing is the whole problem |
| OSS pipeline v1 + dusty-lizard | Feb 2026 | You can't learn from a batch you didn't instrument |
| jade-hare | Mar 13–17, 2026 | Volume without evidence gates converts agent capacity into maintainer annoyance at 55:1 |
| Retrospective build-out | late Mar 2026 | Human review comments are the most important signal; read your failures before building more |
| crimson-kitty (Temporal refactor) | Apr–May 2026 | An abort with a clear reason is a success — make failure legible, don't make submission inevitable |
| taskauto (board-driven) | Jul 2026 | Once the middle is proven, the ends are configuration |

## What's here now

Two live pipelines, one shared engine:

- **crimson-kitty** — the OSS-contribution pipeline
  ([docs/crimson-kitty/](docs/crimson-kitty/README.md)). A 20-state Temporal
  workflow: eligibility → fork → reproduce → fix → verify → review → operator
  signoff → upstream submission → post-submission watching. Every transition is
  backed by an evidence artifact and guarded by a
  [gate registry](docs/crimson-kitty/gates.md) that maps each jade-hare bug
  class to the gate that kills it. An LLM judge scores relevance and submission
  quality; a sandboxed test runner verifies fixes;
  [cross-ref isolation](docs/crimson-kitty/cross-ref-isolation.md) guarantees no
  notification reaches an upstream maintainer until the operator explicitly
  submits.
- **taskauto / hadoku-task-automation** — the same engine with both ends
  swapped ([docs/hadoku-task-automation/](docs/hadoku-task-automation/README.md)).
  Work arrives from a task board instead of the aggregator's scoring, and lands
  by merging to this repo's own `main` instead of opening an upstream PR. It
  runs unattended.

The earlier stage-based pipeline (Stages 1–5 below) and the vibecheck workflow
manager remain in the UI as archival pipelines — old pipelines stay forever
here; they're the record.

## The showcase shelf

The documents worth reading, in the order they earn it:

- [Phase 4 bug catalog](docs/crimson-kitty/phase4-retrospective.md) — every bug
  from crimson-kitty's first external dispatch attempts, each with class, root
  cause, fix, and the lesson (event-loop starvation, GitHub eventual
  consistency, deployment drift).
- [Phase 3 final report](docs/crimson-kitty/phase3-final-report.md) — the
  before/after PR-title proof that context plumbing works: hallucinated
  "reproduction" boilerplate vs. titles naming the exact tool, rule, and file.
- [Surprise log](docs/crimson-kitty/smoke-phase3-surprise-log.md) — all 13
  behaviors the operator did not expect during smoke testing, with dispositions.
- [Observation report](docs/crimson-kitty/smoke-phase3-observation-report.md) —
  per-issue trace of the first full smoke batch: 0/5 submitted, and why every
  abort was correct.
- [taskauto day-one run report](docs/hadoku-task-automation/run-report-2026-07-25.md)
  — 7 unattended commits to `main`, and the autonomy proof.
- The engineering-process letters — cross-repo design review conducted in
  writing: [board-contract.md](docs/hadoku-task-automation/board-contract.md),
  [ask-share-by-name.md](docs/hadoku-task-automation/ask-share-by-name.md),
  [ask-preset-sync.md](docs/hadoku-task-automation/ask-preset-sync.md),
  [ask-api-doc-drift.md](docs/hadoku-task-automation/ask-api-doc-drift.md),
  [ask-dispatch-on-lane-change.md](docs/hadoku-task-automation/ask-dispatch-on-lane-change.md).

The failure numbers are part of the record, on purpose: 55 dispatched / 1
merged at jade-hare; 0/5 submitted in crimson-kitty's first smoke batch (all
five findings were already fixed — the empty-diff gate caught every one); two
10/10-aborted external dispatch attempts that surfaced eight pipeline bugs
before any maintainer saw a PR. The system is built so that those outcomes are
cheap, visible, and instructive.

## Architecture

TenHands is the orchestration layer in a three-repo pipeline:

```
scraper (daily cron)
  -> indexes repo metadata, writes to KV store

aggregator (scoring + analysis)
  -> reads KV, computes CVS scores, builds dossiers and issue briefs
  -> serves scoring API

tenhands (this repo -- orchestration + UI)
  -> calls aggregator API for scored data
  -> orchestrates: forking, agent context, agent assignment, PR review, upstream submission
```

The scraper and aggregator are separate repositories. TenHands consumes the
aggregator API and includes fallback heuristics for graceful degradation when
the aggregator is unreachable.

### Responsibility Boundaries

| Concern | Owner |
|---|---|
| Repo scraping and indexing | scraper |
| Issue scoring (CVS) | aggregator |
| Reaction and sentiment analysis | aggregator |
| Dossier and issue brief generation | aggregator |
| Repo health scores | aggregator |
| Fork management | tenhands |
| Agent context building | tenhands |
| Agent assignment | tenhands |
| PR review orchestration | tenhands |
| Upstream PR submission | tenhands |
| Pipeline UI | tenhands |

## Pipeline Stages (legacy pipeline)

### Stage 1: Target Repos

Repo health overview. Target repos are derived from aggregator scored issues,
enriched with health scores.

### Stage 2: Scored Issues

CVS-scored issues with tier classification. Issues are ranked into tiers -- GO,
LIKELY, MAYBE, RISKY, SKIP -- based on contribution viability factors
(maintainer responsiveness, issue clarity, codebase complexity, community
health). The aggregator computes all scores; tenhands only displays and filters
them.

### Stage 3: Fork and Assign

Fork the target repository, build agent context from the aggregator's dossier
and issue brief, create a context issue on the fork, and assign a coding agent.
All upstream references are stripped from agent-facing content first, so no
cross-reference notification reaches a maintainer while the work is unfinished.

### Stage 4: Review on Fork

Automated review pipeline on the fork: SWE agent produces a draft PR, static
analysis workflows run, code review is requested, and any remediation is
handled. The pipeline orchestrator tracks sub-stage progress and dispatches work
through a pluggable dispatcher interface.

### Stage 5: Submit Upstream

Create a pull request from the fork to the upstream repository and track its
status (open, merged, closed). Only at this stage -- after explicit operator
approval -- are upstream cross-references (e.g., `Fixes #N`) included.

## Tech Stack

**Backend**
- Python / Flask 3.1 with blueprint-based routing, tier-gated behind an
  edge-router (`X-User-Key` → tier resolution in `backend/app.py`)
- Temporal (self-hosted, `temporalio` SDK) for the crimson-kitty and taskauto
  workflow engines
- GitHub CLI (`gh`) for all GitHub operations
- LLM judge via the `claude` CLI (relevance, actionability, submission quality)
- File-based caching with configurable TTL

**Frontend**
- React 19 + TypeScript (Vite build, published as npm package)
- Zustand for state management
- Playwright for E2E testing

**Agent Integration**
- GitHub Copilot coding agent (default) -- agents create draft PRs; work is
  done when commits appear
- Pluggable via `StageDispatcher` interface -- implement `dispatch()`,
  `check_status()`, and `collect_results()` to add new agent backends

**CI**
- GitHub Actions: backend test suite on PRs (`test.yml`), static analysis
  (VibeCheck), taskauto runner (`taskauto.yml`)

## Getting Started

### Prerequisites

- Python 3.8+
- Node.js 18+ and pnpm
- [GitHub CLI (`gh`)](https://cli.github.com/) authenticated via `gh auth login`

### Backend

```bash
python -m venv .venv                                # repo root — matches the deploy
.venv/bin/pip install -r backend/requirements.txt   # repo-root .venv (.venv/bin)
cp .env.example .env   # external/offline dev only — production uses a vault broker, no .env files
.venv/bin/python -m backend.app
```

The API server starts on `http://localhost:5024` by default.

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

The dev server starts on `http://localhost:5184` and proxies API requests to
the backend.

## Project Structure

```
backend/
  app.py               Flask app + request-tier gate (_enforce_tier)
  routes/              Flask route blueprints
    oss_routes_stage1-5  Legacy pipeline stages (target repos ... upstream submission)
    oss_routes_retro     Retrospective data
    temporal_routes      crimson-kitty (Temporal) pipeline endpoints
    taskauto_routes      Board-driven pipeline endpoints
    automation_routes    Automation presets + OpenAPI surface
    pipeline_routes      Legacy pipeline orchestration
    workflow_routes      VibeCheck workflow management
    debug/               Read-only diagnostics (tier-gated)
    health_routes        Health check
    action_routes        Batch actions
  temporal/            The workflow engine (shared by both live pipelines)
    workflows/           IssueWorkflow, BatchWorkflow, post-submission lifecycle
    activities/          Fork, eligibility, agent, review, submission, watchers...
    gates/               Gate registry: eligibility, repro, fix, actionability...
    agents/              Agent adapters (Copilot, noop)
    taskauto/            Board-driven scheduler, runner, landing, reconcile
    judge.py             LLM judge (claude CLI subprocess)
    sanitizer.py         Upstream-ref scrubbing
    calibration.py       Judge calibration harness (20 hand-scored fixtures)
  services/            Business logic (aggregator client, forks, dispatchers, ...)
  helpers/             Pure functions (validation, notifications, reports, ...)
  middleware/          Request identity (whoami)
  tests/               Pytest test suite
frontend/
  src/
    api/               Typed API client (client, endpoints, types)
    components/        Per-pipeline panels (oss, temporal, taskauto, retro,
                       review, pipeline, vibecheck, common)
    views/             Page-level views (OSSView, TemporalPipelineView,
                       TaskAutoView, RetroView, ReviewQueueView,
                       PipelineSelectView, VibecheckView, HealthCheckView)
    store/             Zustand stores
    hooks/             React hooks (batch actions, review actions, theme)
    utils/             Formatters, diff renderer, severity helpers
  e2e/
    local/             Dev/local E2E tests (mocked APIs)
    prod/              Production smoke tests (real APIs)
    fixtures/          Shared test fixtures and API mocks
scripts/               Operator CLI (dispatch_batch, retro_report,
                       snapshot_outcomes, copilot-sessions, taskauto_run, ...)
docs/                  The story and the designs (start at docs/HISTORY.md)
```

## Configuration

Production fetches secrets from a vault broker at start-up — there are no
`.env` files in production. `cp .env.example .env` applies to external or
offline development only; the example file documents every setting:

| Variable | Description | Default |
|---|---|---|
| `AGGREGATOR_API_URL` | Base URL for the aggregator scoring API. Leave empty for offline/fallback mode. | (none) |
| `FLASK_ENV` | Set to `development` for debug mode and extended cache TTL. | `production` |
| `PORT` | Port the Flask backend listens on. | `5024` |
| `URL_PREFIX` | URL prefix for all API routes. Set to `""` for local dev without prefix. | `/tenhands` |
| `DISCORD_WEBHOOK_URL` | Webhook URL for pipeline event notifications. Leave empty to disable. | (none) |
| `BACKEND_PORT` | Backend port for Vite dev proxy. Must match `PORT`. | `5024` |

There is no `ADMIN_KEY`: access control is a request-tier gate in
`backend/app.py` (`_enforce_tier`), which resolves the caller's tier from the
`X-User-Key` header the edge-router injects. Debug endpoints are read-only and
gated by tier, not by a shared secret.

## Testing

### Backend (pytest)

```bash
cd backend && python3 -m pytest tests/ -q
```

The suite runs with **zero skips** — tests that need credentials fetch them
through the vault helper rather than skipping when the environment lacks them.
CI runs the same suite on every PR (`.github/workflows/test.yml`). Install
`backend/requirements-dev.txt` first (test-only dependencies).

### Frontend (Playwright E2E)

```bash
cd frontend
pnpm exec playwright test --project local    # local tests (mocked APIs)
pnpm exec playwright test --project prod     # production smoke tests (real APIs)
pnpm exec playwright test --ui               # interactive UI mode
```

## License

MIT License -- see [LICENSE](LICENSE) for details.
