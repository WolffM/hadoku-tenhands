# VibeDispatch — Claude Code Instructions

## Architecture: Three-Repo System

VibeDispatch is the **orchestration layer** in a three-repo pipeline:

```
hadoku-scrape (daily cron)
  → indexes repo info, dumps to Cloudflare KV

hadoku-aggregator (scoring + analysis)
  → reads KV, computes CVS scores, builds dossiers/issue-briefs
  → serves API: /recon/...

vibedispatch (this repo — orchestration + UI)
  → calls aggregator API for scored data
  → orchestrates: forking, context issues, Copilot assignment, PR review, upstream submission
```

### Responsibility Boundaries — STRICT

| Concern | Owner | NOT vibedispatch |
|---------|-------|-----------------|
| Repo scraping / indexing | hadoku-scrape | |
| Issue scoring (CVS) | hadoku-aggregator | |
| Reaction analysis | hadoku-aggregator | |
| Comment sentiment analysis | hadoku-aggregator | |
| Dossier generation | hadoku-aggregator | |
| Issue briefs | hadoku-aggregator | |
| Repo health scores | hadoku-aggregator | |
| Fork management | vibedispatch | |
| Agent context building | vibedispatch | |
| Copilot assignment | vibedispatch | |
| PR review orchestration | vibedispatch | |
| Upstream PR submission | vibedispatch | |
| Pipeline UI | vibedispatch | |

**CRITICAL: vibedispatch must NEVER implement scoring logic, sentiment analysis, reaction analysis, or any data analysis that belongs to the aggregator.** The only scoring code permitted in vibedispatch is the minimal fallback heuristic in `backend/helpers/oss_helpers.py` which exists solely for graceful degradation when the aggregator is unreachable. This fallback must remain simple and should not be extended with new scoring features — those belong in hadoku-aggregator.

### Data Flow

1. **Stage 1 (Target Repos):** Aggregator provides watchlist + health scores. Fallback: local watchlist + gh CLI metadata.
2. **Stage 2 (Scored Issues):** Aggregator provides pre-scored issues via `GET /recon/all-scored-issues`. Fallback: gh CLI + simple heuristic.
3. **Stage 3 (Fork & Assign):** vibedispatch forks, builds context (from aggregator dossier/brief), creates issue, assigns Copilot.
4. **Stage 4 (Review on Fork):** vibedispatch reads fork PRs via gh CLI.
5. **Stage 5 (Submit Upstream):** vibedispatch creates upstream PR, polls status.

### Aggregator API Contract

All calls go through `_call_aggregator()` in `backend/services/oss_service.py`.

```
GET  /recon/watchlist                     → { slugs: string[] }
GET  /recon/{slug}/health                 → RepoHealth scores
GET  /recon/{slug}/scored-issues          → ScoredIssue[]
GET  /recon/all-scored-issues             → ScoredIssue[] (all repos)
GET  /recon/{slug}/dossier                → Dossier (6-section markdown)
GET  /recon/{slug}/issue-brief/{id}       → { success, data: { issue, repoHealth, brief } }
POST /recon/{slug}/refresh                → triggers re-scrape
POST /recon/{slug}/claim                  → report issue claimed
POST /recon/{slug}/unclaim                → report issue unclaimed
POST /recon/watchlist/add                 → add repo to watchlist
POST /recon/watchlist/remove              → remove repo from watchlist
```

Slug format for aggregator: `owner-repo` (hyphenated). Internal vibedispatch format: `owner/repo` (slash).

### Local State (JSON files in backend/cache/oss/)

- `watchlist.json` — repos user has added
- `selected-issues.json` — issues marked for work
- `assignments.json` — issues forked and assigned to Copilot
- `ready-to-submit.json` — merged fork PRs pending upstream submission
- `submitted-prs.json` — PRs submitted upstream, tracked for status

### Caching

File-based caching in `backend/services/cache.py`. TTL: 5min (prod), 1hr (local dev). Cache is a local convenience layer for API responses — it does NOT store scoring logic or computed data. To force fresh data, clear the cache or use the refresh endpoint.

## Development

### Backend tests

```bash
cd backend && python -m pytest tests/ -v
```

### Key directories

- `backend/routes/` — Flask route blueprints (oss_routes.py, oss_debug_routes.py)
- `backend/services/` — Business logic (oss_service.py, cache.py, github_api.py)
- `backend/helpers/` — Pure functions (oss_helpers.py — fallback scoring, PR templates)
- `backend/tests/` — Pytest test suite
- `frontend/src/` — React frontend

## Copilot Agent Behavior

- Copilot agents (copilot-swe-agent) create PRs in **draft mode** and never take them out of draft.
- They add commits to the branch — when commits appear, the work is done and ready for review.
- Do NOT wait for a PR to leave draft mode before reviewing it. Check for commits/changes instead.
- PRs authored by `app/copilot-swe-agent` are the Copilot agent's output.

## Copilot Session Investigation

`scripts/copilot-sessions.py` inspects Copilot coding agent session logs. Requires `gh` CLI >= 2.80.0.

```bash
# List recent Copilot agent sessions (optionally filter by repo)
python scripts/copilot-sessions.py list --repo WolffM/hadoku-watchparty

# View full session log for a specific PR
python scripts/copilot-sessions.py log -R WolffM/hadoku-watchparty --pr 123

# View condensed thinking summary (strips file content noise)
python scripts/copilot-sessions.py summary -R WolffM/hadoku-watchparty --pr 123

# Same, with TDD workflow analysis appended
python scripts/copilot-sessions.py summary -R WolffM/hadoku-watchparty --pr 123 --analyze

# Compare workflow compliance across multiple PRs (table output)
python scripts/copilot-sessions.py compare -R WolffM/hadoku-watchparty --prs 95,115,123

# Bulk thinking summaries for a batch of PRs
python scripts/copilot-sessions.py batch -R WolffM/hadoku-watchparty --prs 107,109,111
```

**How it works:** PR number → first commit SHA → copilot check-run → Actions run ID → job logs → `COPILOT_AGENT_SESSION_ID` → `gh agent-task view <id> --log`. Tool detection is dynamic (pattern-based, no hardcoded tool names) so it works across any repo.

**Workflow analysis tracks:** reproduced (lint/check before first edit), verified (lint/check after edit), tool_installed, code_review, codeql, self_corrected (edits after code review feedback).

## Aggregator Response Envelope

All aggregator API responses are wrapped in `{ success: true, data: { ... } }`. The unwrapping happens in `backend/services/oss_service.py` — each method (get_watchlist, get_scored_issues, get_dossier, get_issue_brief) handles the envelope. If adding new aggregator calls, always unwrap the envelope.

## Rules

- Never add scoring logic, sentiment analysis, or reaction analysis to vibedispatch. These belong in hadoku-aggregator.
- The fallback scorer in `oss_helpers.py` is for graceful degradation ONLY — do not extend it.
- If a feature requires new data analysis, determine which upstream repo (hadoku-scrape or hadoku-aggregator) should own it and provide instructions for that repo instead.
- Slug format: `owner/repo` internally, `owner-repo` for aggregator API calls.
