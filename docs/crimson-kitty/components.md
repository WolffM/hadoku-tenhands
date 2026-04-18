# Component inventory

What we keep, what we replace, what we add — across all four repos in the
contribution stack.

## vibedispatch (this repo)

### Backend — keep as-is (utilities)

These are stable, well-tested, and called from new Temporal activities
without modification.

| Module | Why we keep it |
|---|---|
| `helpers/notifications.py` | All 9 Discord functions reusable. `notify_human_comments` becomes a Temporal activity that polls and emits Discord events. |
| `helpers/bot_filter.py` | `is_bot()` and `filter_human_comments()` — pure, used by gates. |
| `helpers/validation.py` | Slug, URL, owner, repo-name validators. Used by activities. |
| `helpers/oss_helpers.py` | `format_upstream_pr_body()` is the seed for the new `pr_body_builder`. `score_issue_fallback` stays as a graceful-degradation utility. |
| `services/github_api.py` | gh CLI wrapper with SAML token override. The single most reused module. Activities call `run_gh_command()` directly. |
| `services/cache.py` | Disk cache used by aggregator API calls. |
| `services/oss_firewall.py` | `_sanitize_upstream_refs()` becomes the seed for the new `sanitizer.py` — broadened to also rewrite commit messages and titles. |
| `services/workflow_templates.py` | Renders GHA workflow YAMLs for static analysis. Reusable as-is by an `setup_static_analysis` activity. |
| `services/oss_runner_setup.py` | Self-hosted runner setup. Used by environment activity. |
| `services/pipeline_session_analysis.py` | `fetch_workflow_analysis`, `fetch_session_log`, `fetch_fork_diff` — used by the activity that harvests Copilot results. |
| `services/pipeline_logger.py` | Generic structured logging. |
| `services/pipeline_retrospective.py` | Legacy retro report consumer; **stays scoped to old pipelines only**. Crimson-kitty gets a separate `temporal_retro_report.py` (decision Q7). |

### Backend — replace

These are tightly coupled to the old pipeline model and need to be rewritten
under Temporal.

| Module | LOC | Replaced by |
|---|---|---|
| `services/pipeline_orchestrator.py` | 494 | Temporal `IssueWorkflow` + `BatchWorkflow` |
| `services/pipeline_loop.py` | 207 | Temporal worker process |
| `services/oss_state.py` | 294 | Evidence store under `state/{batch}/{issue}/` + Temporal's PostgreSQL for workflow state |
| `services/dispatchers.py` | 753 | Per-stage Temporal activities (`activities/agent_assign.py`, `activities/agent_poll.py`, etc.) |
| `services/oss_service.py` | 357 | Thin facade for legacy routes; new pipeline does not use it |
| `services/oss_fork.py` | 789 | Replaced by `temporal/activities/fork.py` — single layer, since there's no quarantine boundary. Wraps `gh repo fork` + branch creation against the existing `WolffM/{repo}` namespace. |
| `services/oss_context.py` | 247 | Folded into `activities/build_context.py` |
| `services/pipeline_context_builders.py` | 131 | Folded into `activities/build_review_context.py` and `activities/build_remediation_context.py` |

### Backend — add

New modules introduced by crimson-kitty.

| Module | Purpose |
|---|---|
| `temporal/__init__.py` | Module marker |
| `temporal/config.py` | Temporal client config, env vars, namespace, task queue names |
| `temporal/worker.py` | Entry point for the Temporal worker process (runs as separate pm2 service) |
| `temporal/workflows/issue_workflow.py` | `IssueWorkflow` — the per-issue state machine |
| `temporal/workflows/batch_workflow.py` | `BatchWorkflow` — fans out to many `IssueWorkflow`s |
| `temporal/activities/eligibility.py` | `check_eligibility`, `fetch_dossier`, `fetch_issue_brief`, `scan_contributing_md` |
| `temporal/activities/fork.py` | `ensure_fork`, `create_branch`, `scrub_brief` (writes `02-forked/scrubbed_brief.md` + `scrub_report.json`) |
| `temporal/activities/environment.py` | `setup_environment`, `start_dev_server`, `health_check` |
| `temporal/activities/agent.py` | `request_repro`, `request_fix`, `request_verify`, `request_remediation` — each a thin `async` wrapper that calls the Agent adapter's assign → poll → harvest via `asyncio.to_thread` so blocking `gh` subprocess calls don't starve the worker event loop. Poll loop is bounded at `max_polls=90` with `asyncio.sleep(20)` + `activity.heartbeat()` each iteration (30-min wall-clock ceiling per phase). The workflow passes `heartbeat_timeout=timedelta(minutes=2)` + `RetryPolicy(MaximumAttempts=1)` on these long activities — a worker restart mid-poll is a terminal workflow failure, not a retry. |
| `temporal/activities/review.py` | `run_code_review`, `classify_review_severity` |
| `temporal/activities/submission.py` | `materialize_to_public_fork`, `render_pr_body`, `submit_upstream_pr` |
| `temporal/activities/watchers.py` | `notify_human_comments_for_issue`, `watch_upstream_pr_state` |
| `temporal/activities/inbox.py` | `enqueue_for_human_review`, `await_human_decision` |
| `temporal/gates/__init__.py` | Gate registry decorator and runner |
| `temporal/gates/eligibility.py` | `eligibility` gate |
| `temporal/gates/input_context_clean.py` | `input_context_clean` gate — scans the scrubbed brief for any surviving real upstream ref |
| `temporal/gates/environment.py` | `environment_works` gate |
| `temporal/gates/repro.py` | `repro_evidence_present` gate (mechanical only — judge-based `repro_quality` was dropped in favor of stronger structural checks) |
| `temporal/gates/fix.py` | `diff_non_empty`, `relevance` gates |
| `temporal/gates/verify.py` | `verified_evidence_present` gate |
| `temporal/gates/remediation.py` | `remediation_complete` gate |
| `temporal/gates/submission.py` | `no_upstream_refs`, `pr_template_compliance` (both mechanical), `submission_judge` (judge — the consolidated PR-quality call that replaces the old `pr_body_quality`) |
| `temporal/evidence/__init__.py` | `EvidenceStore` class, file/dir helpers, JSONL append helpers |
| `temporal/evidence/store.py` | `EvidenceStore` implementation |
| `temporal/evidence/scanner.py` | `scan_for_url`, `scan_for_short_ref`, `scan_for_keyword_ref`, `scan_commit_messages` |
| `temporal/sanitizer.py` | Two-layer scrubber: (1) `scrub_brief()` strips upstream URL/slug/issue-number from the agent's input brief; (2) `scan_outputs()` runs at submission against PR title/body/commits and blocks any real upstream ref. Broadened from `oss_firewall._sanitize_upstream_refs`. |
| `temporal/agents/__init__.py` | `Agent` protocol |
| `temporal/agents/copilot.py` | `CopilotAgent` implementation |
| `temporal/agents/noop.py` | `NoopAgent` for tests |
| `temporal/pr_body_builder.py` | Renders structured PR body from evidence into upstream's PR template |
| `temporal/judge.py` | Judge wrapper. **Spawns local `claude` CLI subprocess** (no Anthropic API). Uses Claude Max subscription via `claude -p <prompt>` headless mode. Output parsed as JSON. The binary path is read from `CRIMSON_CLAUDE_BIN` (default `"claude"`); on Windows `subprocess.run` can't resolve bare `.cmd` files from `PATH`, so ecosystem.config.cjs pins the full path to `C:\Users\Hadoku\AppData\Roaming\npm\claude.cmd`. `CLAUDE_CODE_OAUTH_TOKEN` is loaded from `hadoku_site/.env` and inherited by the subprocess for auth. A canary call (`claude -p "respond with exactly: OK" --model haiku`) runs before every real judge invocation to fail fast on quota/auth/binary-missing. `POST /api/temporal/judge/canary` exposes the canary for on-demand diagnostics. |
| `routes/temporal_routes.py` | New Flask blueprint: list workflows, get workflow detail, signal a workflow (operator inbox actions) |

### Frontend — keep as-is (patterns)

| Module | Why we keep it |
|---|---|
| `views/PipelineSelectView.tsx` | The pipeline picker. We add a new tile for crimson-kitty. |
| `store/pipelineStore.ts` | Top-level pipeline state. We add a `temporal` slice. |
| `components/common/*` | Badge, Navigation, FilterBar, etc. — all reusable. |
| `views/RetroView.tsx` | Retro view stays. **Gets a tab strip**: "Legacy" (existing oss-contribution batches) and "Temporal" (crimson-kitty batches). Each tab calls a separate backend endpoint. |
| `api/client.ts`, `api/endpoints.ts` | HTTP client. We add new endpoints for `/api/temporal/*`. |

### Frontend — add

| Module | Purpose |
|---|---|
| `components/temporal/index.ts` | Module marker |
| `components/temporal/PipelineInbox.tsx` | The operator inbox: list of issues awaiting human gates, with evidence preview and approve/abort/retry buttons |
| `components/temporal/IssueDetail.tsx` | Per-issue view: state machine timeline, evidence preview, gate results, transitions log |
| `components/temporal/EvidencePreview.tsx` | Renders evidence files inline (diffs, images, JSON) |
| `components/temporal/StateBadge.tsx` | Small badge showing the current state, color-coded |
| `components/temporal/GateResultRow.tsx` | One row per gate result with verdict + reason |
| `views/TemporalPipelineView.tsx` | The main view, wired into PipelineSelectView |
| `store/temporalStore.ts` | Zustand slice for temporal pipeline state |

### Scripts — add

| Script | Purpose |
|---|---|
| `scripts/temporal_retro_report.py` | Crimson-kitty retro tool. Reads from `state/{batch}/{issue}/` evidence dirs, not the legacy API. Separate codebase from `retro_report.py`; allowed to diverge. |
| `scripts/cleanup_legacy_forks.py` | One-time Phase 0 script. Backs up `WolffM/*` fork list to `state/legacy-forks-backup.jsonl`, then deletes via `gh repo delete --confirm`. Excludes forks with open upstream PRs. |

### Tests — add

| Module | Purpose |
|---|---|
| `tests/temporal/test_workflows.py` | Unit tests for workflow logic using Temporal's `WorkflowEnvironment` |
| `tests/temporal/test_activities.py` | Activity tests (mocked external deps) |
| `tests/temporal/test_gates.py` | Gate tests — pure functions, easy to test |
| `tests/temporal/test_sanitizer.py` | Sanitizer rewriting tests |
| `tests/temporal/test_evidence_store.py` | Evidence store I/O tests |
| `tests/temporal/test_end_to_end.py` | Full pipeline test with mocked external services |

## hadoku-aggregator

The new pipeline keeps calling the existing `/recon/...` API. It does NOT
fork or replace the aggregator.

### Endpoints we already use (no change)

- `GET /recon/{slug}/health`
- `GET /recon/{slug}/scored-issues`
- `GET /recon/all-scored-issues`
- `GET /recon/{slug}/dossier`
- `GET /recon/{slug}/issue-brief/{id}`
- `POST /recon/{slug}/refresh`
- `POST /recon/{slug}/claim`
- `POST /recon/{slug}/unclaim`

### Endpoints we'd like added (new dependencies)

These would let crimson-kitty avoid reimplementing scraping logic.

| Endpoint | Why crimson-kitty needs it | Used by |
|---|---|---|
| `GET /recon/{slug}/contributing` | `eligibility` gate needs structured CONTRIBUTING.md data: `{ai_policy: banned\|allowed\|unknown, dco_required: bool, license_check_required: bool}` | `activities/eligibility.py` |
| `GET /recon/{slug}/pr-template` | `pr_template_compliance` gate needs the upstream PR template structure: `{path, raw_text, sections: [{heading, required, placeholder}], front_matter}` | `activities/submission.py` |
| `GET /recon/{slug}/issue-templates` | Future: detect what reproducer fields the upstream issue *should* have, to validate our repro brief | `activities/repro.py` (v2) |
| `GET /recon/{slug}/codeowners` | Surface who'll be auto-tagged on a PR — informs whether to expect strict review | `activities/eligibility.py` (informational) |
| `GET /recon/{slug}/labels?prefix=ai` | Detect `ai-policy`, `no-ai`, `automated` labels | `activities/eligibility.py` |

These should be additive to the aggregator. Crimson-kitty can ship without
them by implementing fallback inline in vibedispatch, but the cleaner home
is the aggregator. **This is one of the open questions for the second sync.**

## hadoku-scrape

We do not interact with `hadoku-scrape` directly. The aggregator reads from
KV that scrape writes. Crimson-kitty inherits this dependency unchanged.

If the aggregator API surface changes (above), `hadoku-scrape` may need to
write new fields to KV. That's a coordinated change documented in
`hadoku-aggregator/docs/` when we get there.

## hadoku-site

The deployment story stays the same:

- vibedispatch is published as `@wolffm/vibedispatch` to GitHub Packages
- `mount(el, props)` / `unmount(el)` from `frontend/src/entry.tsx`
- pm2 service `vibedispatch` for the Flask backend (existing)
- **NEW pm2 service `vibedispatch-temporal`** for the Temporal worker
  process (runs the workflows + activities)
- **NEW pm2 service `temporal-cluster`** OR a Docker Compose unit for the
  Temporal Cluster itself

The deploy.yml in vibedispatch needs to dispatch to hadoku_site to redeploy
**both** `vibedispatch` and `vibedispatch-temporal`. The mgmt-api in
hadoku_site needs an entry for `vibedispatch-temporal` in
`deploy-config.json`.

This is a hadoku_site change, not a vibedispatch change. **Tracked as an
open question.**

## Coexistence with old pipelines

Crimson-kitty is a new tile in `PipelineSelectView`. The other tiles
continue to work. **No retirement** (decision Q6) — old pipelines stay in
the repo permanently as archival.

| Pipeline | Status |
|---|---|
| vibecheck | Untouched. Independent. Stays forever. |
| oss-contribution (legacy) | Stays in the repo as archival. No new features, no cutover, no deletion. |
| crimson-kitty (new) | Built alongside as the third pipeline. Becomes the default for new dispatches once Phase 1 is complete. |

The legacy retro tool (`scripts/retro_report.py`) reads old-style state
from the existing API. The new retro tool (`scripts/temporal_retro_report.py`)
reads from the crimson-kitty evidence store. The frontend `RetroView`
gets a tab strip to switch between them. The two retro tools are allowed
to diverge — they don't share code.
