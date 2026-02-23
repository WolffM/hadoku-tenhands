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

## Rules

- Never add scoring logic, sentiment analysis, or reaction analysis to vibedispatch. These belong in hadoku-aggregator.
- The fallback scorer in `oss_helpers.py` is for graceful degradation ONLY — do not extend it.
- If a feature requires new data analysis, determine which upstream repo (hadoku-scrape or hadoku-aggregator) should own it and provide instructions for that repo instead.
- Slug format: `owner/repo` internally, `owner-repo` for aggregator API calls.
