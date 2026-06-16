# TenHands

An orchestration layer for automated open-source contributions. TenHands identifies high-value issues across repositories, scores them using a Contribution Viability Score (CVS) engine, and orchestrates an agent pipeline: fork, assign agent, review, and submit upstream.

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

The scraper and aggregator are separate repositories. TenHands consumes the aggregator API and includes fallback heuristics for graceful degradation when the aggregator is unreachable.

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

## Pipeline Stages

### Stage 1: Target Repos

Repo health overview. Target repos are derived from aggregator scored issues, enriched with health scores.

### Stage 2: Scored Issues

CVS-scored issues with tier classification. Issues are ranked into tiers -- GO, LIKELY, MAYBE, RISKY, SKIP -- based on contribution viability factors (maintainer responsiveness, issue clarity, codebase complexity, community health). The aggregator computes all scores; tenhands only displays and filters them.

### Stage 3: Fork and Assign

Fork the target repository, build agent context from the aggregator's dossier and issue brief, create a context issue on the fork, and assign a coding agent. All upstream references are sanitized before posting to the fork to prevent cross-linking.

### Stage 4: Review on Fork

Automated review pipeline on the fork: SWE agent produces a draft PR, static analysis workflows run, code review is requested, and any remediation is handled. The pipeline orchestrator tracks sub-stage progress and dispatches work through a pluggable dispatcher interface.

### Stage 5: Submit Upstream

Create a pull request from the fork to the upstream repository and track its status (open, merged, closed). Only at this stage are upstream cross-references (e.g., `Fixes #N`) included.

## Tech Stack

**Backend**
- Python / Flask 3.1 with blueprint-based routing
- GitHub CLI (`gh`) for all GitHub operations
- File-based caching with configurable TTL
- ThreadPoolExecutor for concurrent API requests

**Frontend**
- React 19 + TypeScript (Vite build, published as npm package)
- Zustand for state management
- Playwright for E2E testing

**Agent Integration**
- GitHub Copilot coding agent (default)
- Pluggable via `StageDispatcher` interface -- implement `dispatch()`, `check_status()`, and `collect_results()` to add new agent backends

**CI**
- GitHub Actions for static analysis workflows (VibeCheck)

## Getting Started

### Prerequisites

- Python 3.8+
- Node.js 18+ and pnpm
- [GitHub CLI (`gh`)](https://cli.github.com/) authenticated via `gh auth login`

### Backend

```bash
python -m venv .venv                                # repo root — matches the deploy
.venv/bin/pip install -r backend/requirements.txt   # repo-root .venv (.venv/bin)
cp .env.example .env   # configure environment variables
.venv/bin/python -m backend.app
```

The API server starts on `http://localhost:5024` by default.

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

The dev server starts on `http://localhost:5184` and proxies API requests to the backend.

## Project Structure

```
backend/
  routes/              Flask route blueprints
    oss_routes_stage1    Stage 1: target repos
    oss_routes_stage2    Stage 2: scored issues
    oss_routes_stage3    Stage 3: fork and assign
    oss_routes_stage4    Stage 4: review on fork
    oss_routes_stage5    Stage 5: upstream submission
    pipeline_routes      Pipeline orchestration endpoints
    workflow_routes      VibeCheck workflow management
    oss_debug_routes     Debug and diagnostics (admin-key gated)
    health_routes        Health check
    action_routes        Batch actions
  services/            Business logic
    oss_service          Aggregator API client, data transforms
    oss_fork             Fork creation and management
    oss_context          Agent context building, upstream ref sanitization
    dispatchers          Pluggable agent dispatcher interface
    pipeline_orchestrator  Multi-stage pipeline state machine
    oss_state            Local JSON state management
    cache                File-based caching with TTL
    github_api           GitHub CLI wrapper
    workflow_templates   VibeCheck workflow YAML generation
  helpers/             Pure functions
    validation           Input validation, slug sanitization, error sanitization
    oss_helpers          CVS fallback scoring heuristic
    notifications        Discord webhook notifications
    report_generator     Pipeline report generation
    stage_helpers        Stage utility functions
  extensions.py        Shared Flask extensions (rate limiter)
  tests/               Pytest test suite
frontend/
  src/
    api/               Typed API client (client, endpoints, types)
    components/
      oss/             OSS pipeline panels (health, issues, fork, review, runs)
      common/          Shared UI components (Badge, SectionHeader, FilterBar)
      pipeline/        Pipeline management components
      review/          PR review components
      vibecheck/       VibeCheck workflow components
    views/             Page-level views (OSS, HealthCheck, Pipeline, Review)
    store/             Zustand stores (pipeline, review queue)
    hooks/             React hooks (batch actions, review actions, theme)
    utils/             Formatters, diff renderer, severity helpers
  e2e/
    local/             Dev/local E2E tests (mocked APIs)
    prod/              Production smoke tests (real APIs)
    fixtures/          Shared test fixtures and API mocks
scripts/               Utility scripts (Copilot session inspector, report generation)
```

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Description | Default |
|---|---|---|
| `AGGREGATOR_API_URL` | Base URL for the aggregator scoring API. Leave empty for offline/fallback mode. | (none) |
| `FLASK_ENV` | Set to `development` for debug mode and extended cache TTL. | `production` |
| `PORT` | Port the Flask backend listens on. | `5024` |
| `URL_PREFIX` | URL prefix for all API routes. Set to `""` for local dev without prefix. | `/dispatch` |
| `ADMIN_KEY` | When set, all debug endpoints require this key via `X-Admin-Key` header. Leave unset for local dev. | (none) |
| `DISCORD_WEBHOOK_URL` | Webhook URL for pipeline event notifications. Leave empty to disable. | (none) |
| `BACKEND_PORT` | Backend port for Vite dev proxy. Must match `PORT`. | `5024` |

## Testing

### Backend (pytest)

```bash
cd backend && python -m pytest tests/ -v
```

### Frontend (Playwright E2E)

```bash
cd frontend
pnpm exec playwright test --project local    # local tests (mocked APIs)
pnpm exec playwright test --project prod     # production smoke tests (real APIs)
pnpm exec playwright test --ui               # interactive UI mode
```

## License

MIT License -- see [LICENSE](LICENSE) for details.
