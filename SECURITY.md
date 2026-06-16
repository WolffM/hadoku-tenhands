# Security Review — TenHands

> Status: CRITICAL · Audited 2026-06-15 · Method: read-only source review + live probes

## Exposure
- Public: dispatch.hadoku.me via cloudflared tunnel → localhost:5024 (Cloudflare Access: NO)
- Other reachability: binds to **127.0.0.1 only** — `app.run(...)` passes no `host=`, so Flask defaults to loopback (`backend/app.py:160`). The app is *not* directly reachable on the LAN; the only public path is the cloudflared tunnel. Confirmed port default 5024 (`backend/app.py:158`).
- Auth model: **None at the application layer for the caller.** `get_authenticated_user()` runs `gh api user` against the *server's own* gh CLI token and returns the server identity — it never inspects the request, so it cannot gate by caller (`backend/services/github_api.py:171-187`). It is used purely as a display/label value (e.g. `backend/routes/health_routes.py:22,34`). There is no `before_request` hook, no session/cookie check, and no `X-User-Key` enforcement anywhere in the backend — `X-User-Key` appears only in the CORS allow-headers list (`backend/app.py:130`), never as a gate. The one real gate, `require_admin_key`, is applied **only to `/api/oss/debug/*` routes** and is a no-op unless the `ADMIN_KEY` env var is set; `.env.example:32` ships it blank and no `.env` is present (`backend/routes/debug/_middleware.py:11-26`).

Net effect: every non-debug route runs unauthenticated with the server's GitHub token and its Temporal client. All paths are served under the `/dispatch` prefix (`URL_PREFIX` default, `backend/app.py:108,142`), matching the live probe of `GET /dispatch/api/owner` → `{"owner":"WolffM"}`.

## Findings
| # | Area / endpoint | Issue | Severity | Location (file:line) |
|---|---|---|---|---|
| 1 | Whole app | No caller authentication on any non-debug route; all run with the server's gh token. `get_authenticated_user()` identifies the *server*, not the caller, and gates nothing. | CRITICAL | `backend/services/github_api.py:171-187`; `backend/app.py` (no `before_request`) |
| 2 | `POST /dispatch/api/merge-pr` | Unauthenticated GitHub merge. Runs `gh pr merge --squash` and will auto-mark a draft PR ready first. | CRITICAL | `backend/routes/action_routes.py:118-168` |
| 3 | `POST /dispatch/api/approve-pr`, `/api/mark-pr-ready`, `/api/assign-copilot` | Unauthenticated PR approval, ready-marking, and Copilot assignment via gh mutations. | CRITICAL | `backend/routes/action_routes.py:23-116` |
| 4 | `POST /dispatch/api/oss/fork-and-assign`, `/api/oss/signoff`, `/api/oss/submit-to-origin`, `/api/oss/merge-fork-pr`, `/api/oss/approve-fork-pr`, `/api/oss/advance-pipeline` | Unauthenticated state-mutating OSS-pipeline actions (fork, assign, sign-off, merge, submit-to-origin). `submit-to-origin` can open PRs against third-party upstream repos under the server identity. | CRITICAL | `backend/routes/oss_routes_stage3.py` (`/api/oss/fork-and-assign`); `backend/routes/oss_routes_stage4.py` (`signoff`, `merge-fork-pr`, `approve-fork-pr`, `advance-pipeline`); `backend/routes/oss_routes_stage5.py` (`submit-to-origin`, `poll-submitted-prs`, `admin/archive-ready-to-submit`) |
| 5 | `POST /dispatch/api/temporal/dispatch`, `/api/temporal/issue/<id>/signal`, `/api/temporal/inbox/resolve-all`, `/api/temporal/inbox/<b>/<i>/resolve`, `/api/temporal/judge/canary` | Unauthenticated Temporal workflow control: start batch workflows, signal/override running issue workflows, bulk-resolve the inbox. | CRITICAL | `backend/routes/temporal_routes.py:278-279` (resolve-all), `:376-377` (dispatch), `:583` (signal) |
| 6 | `POST /dispatch/api/install-vibecheck`, `/api/update-vibecheck`, `/api/run-vibecheck` | Unauthenticated workflow installation / mutation / trigger on repos. | HIGH | `backend/routes/workflow_routes.py` (`install-vibecheck`, `update-vibecheck`, `run-vibecheck`) |
| 7 | `/dispatch/api/oss/debug/*` | Gated by `require_admin_key`, but the gate is a no-op when `ADMIN_KEY` is unset (default). Includes mutating `fork-repo`, `sync-fork`, `assign-copilot`, `create-context-issue`, plus `state-dump` info disclosure. | HIGH | `backend/routes/debug/_middleware.py:11-26`; `backend/routes/debug/*` |
| 8 | `GET /dispatch/api/owner`, `/api/healthcheck`, `/api/temporal/*` reads, `/api/oss/retro/*`, `state-dump` | Unauthenticated information disclosure: owner identity, batch/issue internals, retrospective logs, evidence files, pipeline state. | MEDIUM | `backend/routes/health_routes.py:19-35`; `backend/routes/temporal_routes.py` (read endpoints); `backend/routes/debug/health_routes.py` (`state-dump`) |
| 9 | Rate limiting | Default limit `200/min` keyed on remote address (`get_remote_address`). Behind the tunnel all requests share the tunnel's source IP, so the per-client limit is effectively a coarse global cap and provides little protection. | LOW | `backend/extensions.py:10-14` |
| 10 | CORS | Reflects any `http://localhost:*` / `http://127.0.0.1:*` Origin with `Allow-Credentials: true`. Acceptable for local dev, but combined with no auth it means a victim's local browser session is not the protection boundary — the open endpoints are. | LOW | `backend/app.py:121-132` |

Note on the intended design (`CLAUDE.md:65,67`): the edge-router is meant to resolve the `hadoku_session` cookie into an `X-User-Key` header for backends. TenHands's backend **never reads `X-User-Key` to authorize**, so even if the edge forwards it, and even with the tunnel in place, the app itself enforces nothing. The current tunnel route has no Cloudflare Access, so requests reach the app raw.

## Recommended hardening (priority order)
1. **Put Cloudflare Access in front of `dispatch.hadoku.me` (fastest mitigation).** This is the single change that closes the public hole immediately. Coordinate in the **hadoku_site** repo, since public routing / Cloudflare Access / edge-router config lives there, not here.
2. **Adopt the `X-Edge-Origin` shared-secret seal** that `hadoku_site/services/mgmt-api` already uses: edge-router injects a secret header the backend verifies on every request, rejecting anything that did not transit the edge. Add a `before_request` gate in `backend/app.py` that 401s when the seal is absent/wrong (exempt only `/api/healthcheck`). This stops anyone who discovers the tunnel hostname from bypassing the edge.
3. **Add real app-level auth keyed on the caller.** Have the edge resolve `hadoku_session` → `X-User-Key` (per `CLAUDE.md:65`) and enforce it in a `before_request` hook: map the key to an allowlisted user and reject otherwise. Do not rely on `get_authenticated_user()` for authorization — it only ever returns the server identity.
4. **Require `ADMIN_KEY` in production** (or fold debug routes behind the same gate as #2/#3) so `/api/oss/debug/*` is never an open no-op. Set it via the vault, not a committed `.env`.
5. **Tighten state-mutating routes specifically.** Until #1–#3 land, treat every `POST` listed in findings #2–#6 as a privileged operation; at minimum require the seal from #2 before they execute any `gh`/Temporal call.
6. **Re-key the rate limiter** to use the real client identity (forwarded by the edge, e.g. `CF-Connecting-IP` or the resolved user key) rather than the tunnel IP, and lower the default below `200/min` for mutating routes.
7. **Restrict CORS** to known production origins in production builds; keep the localhost reflection only when `FLASK_ENV=development`.

## Verification (after fixing)
- From the public internet, `curl https://dispatch.hadoku.me/dispatch/api/owner` returns **401/403** (Cloudflare Access challenge or seal rejection), not `{"owner":"WolffM"}`.
- `curl -X POST https://dispatch.hadoku.me/dispatch/api/merge-pr -d '{}'` and the same for `/api/temporal/dispatch`, `/api/oss/fork-and-assign`, `/api/temporal/inbox/resolve-all` all return **401/403** with no gh/Temporal side effect (confirm via server logs that `run_gh_command` / dispatch was never invoked).
- A request that *does* carry a valid edge seal + authorized `X-User-Key` succeeds, proving legitimate edge traffic still works.
- A request to any `/dispatch/api/oss/debug/*` route without a valid `X-Admin-Key` returns **401** in production (i.e. `ADMIN_KEY` is set).
- Confirm in **hadoku_site** that the Cloudflare Access policy / tunnel config for `dispatch.hadoku.me` is committed and deployed, and that the edge injects the seal header.
- Re-run the rate-limit check from two distinct clients and confirm limits apply per-caller, not globally.
