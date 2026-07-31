# TenHands — Claude Code Instructions

## Architecture: Three-Repo System

tenhands is the **orchestration layer** in a three-repo pipeline:
- **hadoku-scrape** — daily cron, indexes repo info → Cloudflare KV
- **hadoku-aggregator** — reads KV, computes CVS scores, builds dossiers → serves API at `/recon/...`
- **tenhands** (this repo) — calls aggregator API, orchestrates: forking, context issues, Copilot assignment, PR review, upstream submission

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

- **Python env:** both pm2 services (`tenhands`, `tenhands-temporal`) run from a per-repo `.venv` (not the system Python). hadoku_site's deploy creates `.venv` and installs `backend/requirements.txt` into it; the PM2 wrapper launches the venv interpreter. Local: `python -m venv .venv` at the repo root, then `.venv/bin/pip install -r backend/requirements.txt`.
- **Production:** pm2 service managed by hadoku_site. Deploy by pushing to `main` (triggers deploy.yml → hadoku_site dispatch). Never start manually in prod.
- **Local:** backend `python3 app.py` (port 5024, `/tenhands`); frontend `pnpm dev` (port 5184, proxies to backend)
- **Tests:** `cd backend && python3 -m pytest tests/ -v`. Needs `backend/requirements-dev.txt` installed too (pytest, and the schema validators that keep `docs/hadoku-task-automation/openapi.json` honest) — those are test-only and never installed in prod. Discord: `DISCORD_WEBHOOK_URL` (prod), `DISCORD_TEST_WEBHOOK_URL` (test). Tests auto-route to test channel.
- **The one skip, and how to not have it.** A plain run reports `1 skipped`: `test_judge.py::test_score_integration_real_cli` needs `CLAUDE_CODE_OAUTH_TOKEN`, and `test.yml` withholds it deliberately — that workflow runs on `pull_request`, so supplying it would hand a live credential to any PR. It is a real test, not a dead one, so run it locally where the credential is already yours:

      node ../hadoku_site/scripts/secrets/dev-vault.mjs -- \
        bash -c 'cd backend && ../.venv/bin/python -m pytest tests/ -q'

  That is the zero-skip run, and it is the one to do before pushing anything that touches `temporal/judge.py`.

## hadoku-site Contract

- Publishes `@wolffm/tenhands` to GitHub Packages (publish.yml)
- Exports: `mount(el, props)`, `unmount(el)` from `frontend/src/entry.tsx`
- Triggers `packages_updated` dispatch to hadoku_site on publish
- Backend: Flask on port 5024 behind `/tenhands` prefix, deployed via `redeploy_service` dispatch

## Auth & secrets (hadoku ecosystem)

- **Browser fetches** must hit `hadoku.me/{prefix}/*` via edge-router — NEVER `*.hadoku.me` direct subdomains. The `hadoku_session` cookie (`Domain=.hadoku.me`, 30d sliding) is set on `/auth` and resolved server-side by edge-router into `X-User-Key` for the backend.
- **Secrets**: vault-broker model, NO `.env` files. Local dev fetches via `.devvault.json` + `node ../hadoku_site/scripts/secrets/dev-vault.mjs -- <cmd>`. If `pnpm dev` fails, run `node ../hadoku_site/scripts/secrets/dev-vault.mjs --check` for diagnostics. **Tutorial: `../hadoku_site/docs/child-apps/USING_VAULT.md`**. Operational reference: `../hadoku_site/docs/operations/SECRETS.md`.
- **Auth model**: 1:1 named user-keys. `/auth` accepts key + name; whoami returns the name. Admin endpoints `GET/POST/DELETE /session/admin/keys` manage the registry. See `../hadoku_site/docs/planning/next-work.md`.

## Vault — what your service-tier key can and can't do

This repo's vault key lives in `.devvault.local.json` at the repo root (gitignored, mode 0600). `dev-vault.mjs` reads it automatically. Per-key ACL is enforced as of 2026-05-04.

CAN do (no operator needed):

- `GET /api/secrets/status` — sealed/unlocked check
- `GET /api/secrets/get/:key` — fetch a value declared in this repo's `.devvault.json`
  (other repos' secrets return 403 — your key is scoped to THIS repo)
- `GET /api/secrets/acl/me` — see what your key is granted
- Verify with: `node ../hadoku_site/scripts/secrets/dev-vault.mjs --check`

CANNOT do (returns `403` — by design):

- Read secrets NOT in this repo's `.devvault.json`
- `POST /api/secrets/admin/set-many` — adding/changing secrets
- `POST /api/secrets/admin/lock` — sealing the vault
- `GET /api/secrets/list` — enumerating every secret name
- `GET /api/secrets/audit` — dead-key report

If your code reads a new `process.env.X` that isn't in `.devvault.json` yet:

1. Add the mapping to `.devvault.json` (commit-safe, no values).
2. Tell the operator: they grant the new entries via `key-acl-sync --repo ../<this-repo> --key <uuid> [--prune]`.
3. Re-run your dev command.

Operator-only operations (set / lock / audit / grant) use `HADOKU_ADMIN_KEY`. Don't try to escalate: service tier can't write, and there is no key list to add yourself to — auth resolves from the edge-router key registry, which only an admin can write.

Lost or rotating your key? Operator: `python scripts/administration.py key-generate --tier service --repo ../<repo> --name <your-name>-<repo>` then drop the new UUID in `.devvault.local.json`.
