# TenHands — Claude Code Instructions

## Architecture: Three-Repo System

tenhands is the **orchestration layer** in a three-repo pipeline:
- **hadoku-scrape** — daily cron, indexes repo info into a KV store
- **hadoku-aggregator** — reads that index, computes scores, builds dossiers → serves an API at `/recon/...`
- **tenhands** (this repo) — calls the aggregator API and orchestrates: forking, context issues, Copilot assignment, PR review, upstream submission

## Ownership Boundaries

- Does NOT compute scores, repo health, sentiment, reaction analysis, dossiers, or issue briefs → `hadoku-aggregator`
- Does NOT scrape external APIs or write to the KV store → `hadoku-scrape`
- Does NOT host the UI or manage deployment → the site repo
- Minimal scoring fallback in `backend/helpers/oss_helpers.py` for graceful degradation — do not extend

## Aggregator API Contract

All calls go through `_call_aggregator()` in `backend/services/oss_service.py`. Slug format: `owner-repo` (hyphenated) for the aggregator, `owner/repo` (slash) internally.

```
GET  /recon/{slug}/health            → RepoHealth
GET  /recon/{slug}/scored-issues     → ScoredIssue[]
GET  /recon/all-scored-issues        → ScoredIssue[] (all repos)
GET  /recon/{slug}/dossier           → Dossier (6-section markdown)
GET  /recon/{slug}/issue-brief/{id}  → { success, data: { issue, repoHealth, brief } }
POST /recon/{slug}/refresh           → triggers re-scrape
POST /recon/{slug}/claim             → report issue claimed
POST /recon/{slug}/unclaim           → report issue unclaimed
```

Aggregator responses are wrapped in `{ success: true, data: {...} }` — unwrapped in `oss_service.py`.

## Two envelopes, and which one is ours

Nesting under `data` is the shape tenhands **consumes**, not the one it serves:

- **`{ success, data: {...}, _meta }`** — the ecosystem's standard envelope. The aggregator
  serves it (`_unwrap_aggregator_response` in `oss_service.py`), and the site's workers do too.
- **`{ success, ...payload }`** — flat, and what **every route tenhands serves** returns.

`temporal_routes.py` served the nested one from April 2026 until 2026-08-06, the only module in
this backend that did, which cost an `unwrap()` in `endpoints.ts` that existed for eight endpoints
and nothing else, plus a `.get("data", {})` in three operator scripts. It is flat now. Do not
reintroduce the split: mixing the two yields an **empty view rather than an error**, because
`.get("data", {})` and a missing `data` key both read as "no content".

`_meta` on a flat response is fine and unrelated — the OSS routes attach the aggregator's
freshness metadata that way (`oss_routes_stage1.py`).

## Upstream cross-reference isolation — important

Agent work on a fork must not notify upstream maintainers until a human explicitly submits it.
The reason is courtesy, not concealment: GitHub auto-generates a cross-reference notification to
the upstream issue the moment a fork artifact mentions it (via a URL, an `owner/repo#N` short ref,
or a `Fixes #N` keyword), and unfinished agent work should never ping a maintainer. So the pipeline
strips those references from all agent-facing content and links upstream **only at the point of
human-approved submission**. See `docs/crimson-kitty/cross-ref-isolation.md`.

- `_sanitize_upstream_refs()` in `oss_service.py` — all fork issue content passes through this
- `build_agent_context()` sanitizes the aggregator brief/dossier before posting to the fork
- Fork issue titles must not contain upstream refs
- `format_upstream_pr_body()` with `Fixes`/`Closes` is ONLY for Stage 5 (upstream submission)

This has regressed before — treat a cross-reference reaching upstream as a real bug.

## Copilot Agent Behavior

- Agents create **draft PRs** and never undraft. Work is done when **commits appear** on the branch — don't wait for PR status. Author: `app/copilot-swe-agent`.

## Development

- **Python env:** the pm2 services (`tenhands`, `tenhands-temporal`) run from a per-repo `.venv`.
  Local: `python -m venv .venv` at the repo root, then `.venv/bin/pip install -r backend/requirements.txt`.
- **Local:** backend `python3 app.py` (port 5024, prefix `/tenhands`); frontend `pnpm dev` (proxies to the backend).
- **Tests:** `cd backend && python3 -m pytest tests/ -v`. Install `backend/requirements-dev.txt` too (pytest + the schema validators that keep `docs/hadoku-task-automation/openapi.json` honest); those are test-only.
- **Zero skips.** A plain `cd backend && python3 -m pytest tests/ -q` runs the whole suite with **0 skipped**. If a test needs a secret, it fetches it rather than gating on the environment — a `skipif` on a missing credential is indistinguishable from a passing test in the output.
- **This checkout is production.** The pm2 services run *from this working directory*, and a deploy runs `git reset --hard origin/main` against it — which **eats any uncommitted work in the tree** (recoverable only from the lint-staged stash). Do not leave edits uncommitted here, and do not assume the branch you left checked out is still there: concurrent agents and deploys move it. For any real change, work in a git worktree (`git worktree add .claude/worktrees/<task> -b <branch>`), which deploys don't touch, and commit + push promptly.
- **Debugging a taskauto task** (odd notes, gating, deploy, editing a task): [`docs/runbooks/taskauto-debugging.md`](docs/runbooks/taskauto-debugging.md). The board API is reachable from here with the `.devvault.local.json` `key` exported as `HADOKU_SERVICE_KEY` (service tier, shares on every board) — no vault unlock needed for reads.

## Secrets

There are no `.env` files. Secrets are fetched from a vault broker under a per-repo, per-key ACL;
the repo tracks only the *names* of the env vars it needs, in `.devvault.json`. If your code reads
a new `process.env.X`, add its name to `.devvault.json` (values-free, commit-safe) and ask the
operator to grant it. Operator-specific setup lives in `CLAUDE.local.md` (untracked).
