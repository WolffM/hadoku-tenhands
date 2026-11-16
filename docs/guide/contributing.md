# Contributing

How to run TenHands, where things live, and what ships to production. What
it does for a reader or operator is in [features.md](features.md). Read
[`AGENTS.md`](../../AGENTS.md) first — it is short, and records the rules
that have regressed before.

## Run it locally

```sh
python -m venv .venv                                # repo root — matches the deploy
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip install -r backend/requirements-dev.txt   # test-only deps
cp .env.example .env    # external/offline dev only — production has no .env files
.venv/bin/python -m backend.app
```

The API starts on `http://localhost:5024`. For the frontend:

```sh
cd frontend && pnpm install && pnpm dev   # :5184, proxies API calls to the backend
```

**This checkout is production.** The pm2 services run from this exact
working directory, and a deploy does `git reset --hard origin/main` against
it — which eats any uncommitted work in the tree. Do real work in a git
worktree (`git worktree add .claude/worktrees/<task> -b <branch>`), which a
deploy never touches, and commit and push promptly rather than leaving
changes sitting in the live checkout.

## How it fits together

```
task board ──┐
              ├─► tenhands (this repo): orchestration + UI
hadoku-aggregator ──(scored issues, dossiers)──┘      │
                                                       ├─ Temporal: the shared workflow engine
                                                       ├─ crimson-kitty: fork → fix → submit upstream
                                                       └─ taskauto: board task → merge to this repo's own main
```

TenHands calls a separate scoring service (`hadoku-aggregator`, a public
repo) for issue scores, repo health and dossiers, and falls back to a small
built-in heuristic (`backend/helpers/oss_helpers.py`) when that service is
unreachable — deliberately minimal, and not meant to be extended. A third,
separate service indexes repo metadata on a daily cron and feeds the
scoring service; TenHands never talks to it directly.

- **`backend/routes/`** — Flask blueprints. `oss_routes_stage1` through
  `stage5` are the original five-stage pipeline; `temporal_routes` is
  crimson-kitty; `taskauto_routes` is the board pipeline; `debug/` is
  read-only, admin-gated diagnostics.
- **`backend/temporal/`** — the shared engine. `workflows/` (the Temporal
  workflow definitions), `activities/` (fork, eligibility, agent dispatch,
  review, submission, watchers), `gates/` (the gate registry), `agents/`
  (the Copilot adapter and a no-op for testing), `taskauto/` (the board
  scheduler, runner and reconciler), `judge.py` (the LLM judge),
  `sanitizer.py` (upstream-reference scrubbing).
- **`frontend/src/`** — React 19 + TypeScript, Zustand for state. One view
  per pipeline (`views/`), a typed API client (`api/`), per-pipeline panels
  (`components/`).
- **`scripts/`** — the operator CLI: `dispatch_batch`, `retro_report`,
  `snapshot_outcomes`, `taskauto_run`.

## Access control

There is no `ADMIN_KEY` anywhere in this backend. Every route resolves the
caller's tier from the `X-User-Key` header the edge injects
(`backend/app.py`, `_enforce_tier`): friend tier and up may read; a mutating
request additionally needs service tier **and** a seat on the
`tenhands-write` access list (an admin account is not automatically on it).
The debug routes gate separately, at admin tier specifically
(`backend/routes/debug/_middleware.py`).

## Tests and gates

```sh
cd backend && python3 -m pytest tests/ -q      # zero skips, always
cd frontend && pnpm exec playwright test --project local   # mocked APIs
cd frontend && pnpm exec playwright test --project prod    # real APIs, production smoke
```

**Zero skips, by rule.** A test that needs a credential fetches it through
the vault helper rather than skipping when the environment lacks one — a
`skipif` on a missing secret reads identically to a passing test in CI
output. The one sanctioned exception is the LLM judge's real-CLI test, which
skips only when the account's own usage quota is exhausted, with the reset
time printed in the reason.

CI (`.github/workflows/test.yml`) runs the backend suite on every PR. A
separate static-analysis workflow and the `taskauto.yml` runner round out
the checks named in the README's own tech-stack table.

## How it ships

Production has no `.env` files; secrets come from a vault broker under a
per-repo, per-key access list, and this repo tracks only the names of the
environment variables it needs, in `.devvault.json` (no values, commit-safe).
A push to `main` is itself a live deploy target — the backend's own pm2
services run from this checkout and are reset to `origin/main` by the deploy
process, which is exactly why real work happens in a worktree, never in this
checkout directly.

## Trivia

The repo's own Copilot agents create draft PRs and never undraft them — work
on a dispatch is considered done the moment commits appear on the branch,
not when the PR's own status changes.
