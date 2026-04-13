# Open questions — resolved + follow-ups

All 10 original questions resolved on 2026-04-13. New follow-up questions
identified from those answers are listed at the bottom.

## Resolutions

### Q1. Temporal hosting & deployment — RESOLVED
**Decision (a)**: same WSL host, Docker Compose unit, started by pm2.
**Implementation**: `hadoku_site/services/temporal-cluster/docker-compose.yml`
managed via the existing mgmt-api `redeploy_service` mechanism.

### Q2. Temporal Cluster pm2 integration — RESOLVED
**Decision**: pm2-managed via mgmt-api. **No unmanaged daemon processes.**
**Implementation**: pm2 runs `docker compose up` (in foreground, no `-d`)
as the long-lived process for the cluster. `pm2 restart` triggers
`docker compose down && up`. The mgmt-api `deploy-config.json` gets a new
entry: `temporal-cluster`. The worker process (`vibedispatch-temporal`)
gets a separate entry, restarts independently, and waits for the cluster
to be healthy on startup.

### Q3. Aggregator API additions — RESOLVED
**Decision**: add to hadoku-aggregator. The new endpoints become a
prerequisite for crimson-kitty Phase 1.
**Owned-elsewhere work**: file 5 issues against `hadoku-aggregator`:
1. `GET /recon/{slug}/contributing` — structured CONTRIBUTING.md
   (`{ai_policy, dco_required, license_check_required}`)
2. `GET /recon/{slug}/pr-template` — PR template structure
   (`{path, raw_text, sections, front_matter}`)
3. `GET /recon/{slug}/issue-templates` — issue template structure
4. `GET /recon/{slug}/codeowners` — parsed CODEOWNERS
5. `GET /recon/{slug}/labels?prefix=ai` — labels matching a prefix

These need to be wired into hadoku-scrape's KV writes too. Coordinate as
a one-time prerequisite milestone.

### Q4. Quarantine PAT — WITHDRAWN (2026-04-13)
Originally resolved with a new `TEMPORAL_QUARANTINE_PAT`. Withdrawn when
decision #2 was revised away from a separate quarantine org. The pipeline
uses the existing `gh` user token plus `SAML_ORG_TOKEN` routing in
`services/github_api.py`. No new PAT is created.

### Q5. LLM judge — RESOLVED with follow-up
**Decision**: spawn local `claude` CLI subprocess. Uses the existing
Claude Max subscription, no API key required, plays well with skills.
**Implementation pattern**:
```python
result = subprocess.run(
    ["claude", "-p", judge_prompt, "--model", "haiku",
     "--permission-mode", "bypassPermissions"],
    capture_output=True, text=True, timeout=120,
)
```
**See follow-up F1 below** — production deployment needs to install and
authenticate the `claude` CLI on the deploy host.

### Q6. Cutover — RESOLVED
**Decision**: no retirement. Old pipelines (`vibecheck`, `oss-contribution`)
stay in the repo permanently as archival. Crimson-kitty becomes the
default for new dispatches but old code is not deleted, even after
crimson-kitty is mature.

### Q7. retro_report extension — RESOLVED
**Decision**: separate retro tool per pipeline. Crimson-kitty gets its own
`scripts/temporal_retro_report.py`. Old `scripts/retro_report.py` stays as
the legacy reader.

The frontend `RetroView.tsx` adds a tab strip:
- Tab 1: "Legacy" (existing oss-contribution batches via `retro_report`)
- Tab 2: "Temporal" (crimson-kitty batches via `temporal_retro_report`)

Each tab calls a separate backend endpoint
(`/api/oss/retro/...` vs `/api/temporal/retro/...`). The two retro tools
share no code — they're allowed to diverge as crimson-kitty evolves new
metadata fields.

### Q8. First batch issue selection — RESOLVED
**Decision**: smoke-test against your own repos first
(`vibedispatch`, `hadoku-aggregator`, `hadoku-scrape`, `hadoku_site`,
`personal-dataplatform`, etc.). This validates the pipeline end-to-end
before dispatching against external upstreams.

After the smoke test passes, batch 2 uses the aggregator's
`all-scored-issues` to pick by score (existing scoring system).

### Q9. Eligibility failure handling — RESOLVED
**Decision (b)**: no auto-retry. First failure escalates to inbox.
The Temporal activity retry policy is `RetryPolicy(maximum_attempts=1)`
for eligibility, environment, and fork activities. Other activities
(GitHub API calls that may flake) keep `maximum_attempts=3`.

### Q10. Existing `WolffM/{repo}` forks — RESOLVED with follow-up
**Decision (c)**: delete all old jade-hare-era forks. Start fresh.
**Implementation**: a one-time script `scripts/cleanup_legacy_forks.py`
that:
1. Lists all `WolffM/*` repos that are forks (via `gh api`)
2. Writes `state/legacy-forks-backup.jsonl` with each fork's metadata
   (parent, branches, last commit, PR refs) for archival
3. Prints the deletion plan and requires `--confirm` to actually delete
4. Deletes via `gh repo delete`

**See follow-up F2 below** — operator must run the script manually after
review.

---

## Follow-up resolutions (2026-04-13)

### F1. claude CLI in production — RESOLVED with new design constraint

**Constraint added**: judge does minimal work — **1-2 judge calls per issue
in the entire pipeline**. Most gates are mechanical. See updated `gates.md`.

**Resolutions**:
- **(a) Install via pm2 bootstrap**: `npm install -g @anthropic-ai/claude-code@<pinned>`
  added to `vibedispatch-temporal` setup script. Reproducible.
- **(b) Production gets own auth**: OAuth flow run once on prod host,
  documented in `docs/runbooks/claude-cli-prod-auth.md`. Credentials are
  machine-local. If the host gets reprovisioned, re-auth.
- **(c) Concurrency + canary**:
  - Semaphore in the activity code: `cap=3` parallel judge subprocesses
  - **Canary check** before each judge call:
    `claude -p "respond with OK" --model haiku` with 10s timeout
  - Canary failure → defer to inbox immediately, don't attempt the real
    call (avoids stalling on Max usage cap)
- **(d) Defer to inbox on unreachable**: reason
  `system:judge_unreachable` to distinguish from quality-based defers.

**New design constraint from this answer**:

> The `claude` CLI emits markdown plus status messages, warnings, and
> tool-use output that can contaminate stdout. The judge MUST use
> `--output-format json` if available, OR wrap the parse in try/catch
> that defers to inbox with reason `system:judge_parse_error` on
> failure rather than crashing the gate.

This is now a Phase 1 hard requirement on `judge.py`.

### F2. Legacy fork cleanup — RESOLVED
- **(a) Phase 0 this week** — confirmed.
- **(b) Backup forever** — confirmed. `state/legacy-forks-backup.jsonl`
  has no expiration.
- **(c) Delete ALL forks**, no exclusion for open PRs. The 6 jade-hare
  PRs still open will be closed by upstream eventually; deleting our
  forks doesn't kill the PR records on upstream.

### F3. Smoke-test target — RESOLVED with reframing
**Pick from vibecheck-created issues** in the hadoku ecosystem. These
are issues already triaged by your own pipeline against your own repos.

**Reframe**: "easy" means easy for the **agent**, not easy for the
operator. The pipeline is testing whether Copilot SWE can navigate an
unfamiliar (to it) codebase through the full state machine. The
operator has nothing to prove — the agent does.

Action: query vibecheck output for repos in `hadoku-*` namespace, pick
3-5 issues with the "small fix" label or equivalent.

### F4. Temporal Docker image — RESOLVED with infra requirement
**(b) `temporalio/auto-setup`** confirmed. Pin version to match the SDK
version in the worker.

**New infra requirement**: the Docker Compose unit MUST include a
**named volume** for PostgreSQL data. Pm2 restarts trigger
`docker compose down && up`, and without a named volume, every restart
wipes workflow history and breaks every in-flight workflow.

```yaml
volumes:
  temporal-postgres-data:

services:
  postgresql:
    image: postgres:13
    volumes:
      - temporal-postgres-data:/var/lib/postgresql/data
```

This is now a Phase 1 hard requirement on the Docker Compose file.

### F5. Retro UI tabs — RESOLVED
**Lazy-load**. Tactical, deferred to Phase 1 implementation.

---

## Status

All 10 original questions and all 5 follow-ups resolved.
**Phase 0 prereqs are unblocked.** Ready to commit and start Phase 0
work this week.
