# VibeDispatch — Claude Code Instructions

## Architecture: Three-Repo System

vibedispatch is the **orchestration layer** in a three-repo pipeline:
- **hadoku-scrape** — daily cron, indexes repo info → Cloudflare KV
- **hadoku-aggregator** — reads KV, computes CVS scores, builds dossiers → serves API at `/recon/...`
- **vibedispatch** (this repo) — calls aggregator API, orchestrates: forking, context issues, Copilot assignment, PR review, upstream submission

## Ownership Boundaries

- Does NOT compute CVS scores, repo health, sentiment, reaction analysis, dossiers, or issue briefs → `hadoku-aggregator`
- Does NOT scrape external APIs or write to Cloudflare KV → `hadoku-scrape`
- Does NOT host the UI or manage worker deployment → `hadoku_site`
- Minimal scoring fallback in `backend/helpers/oss_helpers.py` for graceful degradation — do not extend

## Aggregator API Contract

All calls go through `_call_aggregator()` in `backend/services/oss_service.py`. Slug format: `owner-repo` (hyphenated) for aggregator, `owner/repo` (slash) internally.

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

All responses are wrapped in `{ success: true, data: {...} }` — unwrapped in `oss_service.py`.

## Upstream Cross-Linking Prevention — CRITICAL

Fork work MUST be invisible to upstream until the user explicitly submits via their personal account. GitHub creates cross-reference notifications from URLs (`github.com/owner/repo/issues/N`), short refs (`owner/repo#N`), and keywords (`Fixes #N`). All of these MUST be stripped:

- `_sanitize_upstream_refs()` in `oss_service.py` — all fork issue content passes through this
- `build_agent_context()` sanitizes aggregator brief/dossier before posting to fork
- Fork issue titles MUST NOT contain upstream refs
- `format_upstream_pr_body()` with `Fixes`/`Closes` is ONLY for Stage 5 (upstream submission)

This has leaked in 3 consecutive runs. If cross-references reach upstream, the stealth workflow is compromised.

## Copilot Agent Behavior

- Agents create **draft PRs** and never undraft. Work done when **commits appear** on branch — don't wait for PR status. Author: `app/copilot-swe-agent`.

## Development

- **Production:** pm2 service managed by hadoku_site. Deploy by pushing to `main` (triggers deploy.yml → hadoku_site dispatch). Never start manually in prod.
- **Local:** backend `python3 app.py` (port 5024, `/dispatch`); frontend `pnpm dev` (port 5184, proxies to backend)
- **Tests:** `cd backend && python3 -m pytest tests/ -v`. Discord: `DISCORD_WEBHOOK_URL` (prod), `DISCORD_TEST_WEBHOOK_URL` (test). Tests auto-route to test channel.

## hadoku-site Contract

- Publishes `@wolffm/vibedispatch` to GitHub Packages (publish.yml)
- Exports: `mount(el, props)`, `unmount(el)` from `frontend/src/entry.tsx`
- Triggers `packages_updated` dispatch to hadoku_site on publish
- Backend: Flask on port 5024 behind `/dispatch` prefix, deployed via `redeploy_service` dispatch

## Auth & secrets (hadoku ecosystem)

- **Browser fetches** must hit `hadoku.me/{prefix}/*` via edge-router — NEVER `*.hadoku.me` direct subdomains. The `hadoku_session` cookie (`Domain=.hadoku.me`, 30d sliding) is set on `/auth` and resolved server-side by edge-router into `X-User-Key` for the backend. See `../hadoku_site/CLAUDE.md` for the rule.
- **Secrets**: vault-broker model. Local dev fetches via `.devvault.json` + `node ../hadoku_site/scripts/secrets/dev-vault.mjs -- <cmd>`. Production runtime is wired automatically (PM2 wrappers for tunnel apps; CF Worker secret bindings pushed by `python ../hadoku_site/scripts/administration.py cloudflare-secrets`). NEVER add `.env` files. See `../hadoku_site/docs/operations/SECRETS.md`.
- **Auth model**: 1:1 named user-keys. `/auth` accepts key + name; whoami returns the name. Admin endpoints `GET/POST/DELETE /session/admin/keys` manage the registry. See `../hadoku_site/docs/planning/next-work.md`.
