# Phase 3.3 — Surprise log

Every observed behavior the operator did NOT expect during the Phase 3
smoke test. Each surprise is tagged with operator disposition.

## Surprises found during dispatch iterations (r1-r5)

### S1. Missing AGGREGATOR_API_URL on Temporal worker
- **Observed**: Worker eligibility activity crashed with `aggregator returned non-object: NoneType` because `AGGREGATOR_API_URL` was not in the pm2 env
- **Root cause**: ecosystem.config.cjs had the URL for the Flask app but not the Temporal worker
- **Impact**: All dispatches failed immediately at eligibility
- **Fix**: Added `AGGREGATOR_API_URL: 'https://hadoku.me/oss/api'` to worker env
- **Disposition**: fix in v1 (DONE - commit ba25510)

### S2. Eligibility gate read dossier.health.activity_score which doesn't exist
- **Observed**: Gate failed with "repo activity below threshold: 0" even for active repos
- **Root cause**: The dossier endpoint returns `{sections, completeness}`, not health data. Health is a separate endpoint. Gate defaulted to activity_score=0
- **Impact**: Every repo failed eligibility regardless of actual health
- **Fix**: Activity now fetches `/health` separately; gate reads `maintainerHealthScore` from `health.json`
- **Disposition**: fix in v1 (DONE - commit aefc580)

### S3. Personal repos not in scraper bootstrap list
- **Observed**: 4 of 5 smoke targets returned `{"status": "pending"}` from aggregator
- **Root cause**: Only `WolffM/hadoku_site` and `WolffM/hadoku-watchparty` were in `oss_recon.json`
- **Impact**: No dossier/health data for most smoke targets
- **Fix**: Added 5 WolffM repos to bootstrap list; triggered ad-hoc scrapes
- **Disposition**: fix in v1 (DONE - commit 3a24c0b in hadoku-scrape)

### S4. Default install_cmd `["true"]` doesn't exist on Windows
- **Observed**: `FileNotFoundError: [WinError 2] The system cannot find the file specified` in setup_environment
- **Root cause**: `true` is a Unix shell builtin, not available on Windows. The worker runs on a Windows host
- **Impact**: All issues stuck at `forked` forever (3 retries x 10 min timeout)
- **Fix**: Changed default to `["python", "-c", "0"]`
- **Disposition**: fix in v1 (DONE - commit fa0455b)

### S5. Repro gate hardcoded to test/screenshot/trace filenames
- **Observed**: Gate failed with "no test, screenshot, or trace produced" even though Copilot produced lint output and notes
- **Root cause**: Gate only checked `test.*`, `before.png`, `trace.zip` — SA/lint evidence doesn't fit these patterns
- **Impact**: All issues aborted at repro even when the agent did real work
- **Fix**: Gate now accepts any non-boilerplate file as evidence
- **Disposition**: fix in v1 (DONE - commit bc1107d)

### S6. Runtime state dirs clobbered by git pull during deploys
- **Observed**: Batch state disappeared after service restart (`batch not found` on the API)
- **Root cause**: `state/` not in `.gitignore`. Deploy executor runs `git stash/pull` which could interfere with untracked dirs. More importantly, Temporal workflow state and disk evidence were decoupled — workflows completed in Temporal but evidence was lost on disk
- **Impact**: Could not observe pipeline progress after any restart
- **Fix**: Added `.gitignore` patterns for `state/smoke-*`, `state/batch-*`, `state/crimson-kitty-*`
- **Disposition**: fix in v1 (DONE - commit 15d22b3)

### S7. CRIMSON_AGENT_KIND defaulting to noop
- **Observed**: All issues passed repro gate but produced no evidence artifacts — agent was NoopAgent
- **Root cause**: `CRIMSON_AGENT_KIND` env var not set in worker pm2 config. Default is `"noop"`
- **Impact**: Pipeline ran the full workflow but with a fake agent that produces empty results
- **Fix**: Added `CRIMSON_AGENT_KIND: 'copilot'` to worker env
- **Disposition**: fix in v1 (DONE - commit 83cf231 in hadoku_site)

### S8. BatchWorkflow awaited children sequentially
- **Observed**: Only 1 issue workflow existed in Temporal at a time; batch of 5 would take 5x as long
- **Root cause**: `for coro in coros: r = await coro` pattern awaits each child one at a time
- **Impact**: ~5 hour batch time instead of ~1 hour
- **Fix**: Switched to `asyncio.gather(*coros, return_exceptions=True)`
- **Disposition**: fix in v1 (DONE - commit a60a8e0)

### S9. CopilotAgent files not downloaded to evidence store
- **Observed**: Copilot created real PRs with commits (notes.md, trace files) but the repro gate couldn't find them locally
- **Root cause**: CopilotAgent commits to a remote branch on GitHub. The `request_repro` activity only wrote `agent_result.json` locally. Nobody fetched the agent's files from the PR branch into the evidence directory
- **Impact**: All issues failed repro gate despite Copilot doing real work
- **Fix**: Added `_download_agent_files()` that fetches each touched file via GitHub API after harvest
- **Disposition**: fix in v1 (DONE - commit 338f2e4)

### S10. CLAUDE_CODE_OAUTH_TOKEN not configured — relevance judge gate crashes
- **Observed**: Relevance gate deferred with `MissingConfigError: CLAUDE_CODE_OAUTH_TOKEN is not set`
- **Root cause**: Token is in pm2 env but may be empty (`process.env.CLAUDE_CODE_OAUTH_TOKEN || ''`). The judge gate calls Claude via the CLI and needs this token
- **Impact**: Low — gate fires after diff_non_empty, so the empty-diff abort preempted the crash. Would be blocking if the pipeline reached a real fix with a non-empty diff
- **Fix needed**: Verify CLAUDE_CODE_OAUTH_TOKEN is set in .env on the prod host
- **Disposition**: fix in v1 (TODO — config issue, not code)

### S11. All 5 smoke targets were stale (already fixed on main)
- **Observed**: Every issue produced an empty diff at the fix stage
- **Root cause**: The vibeCheck SA issues were created months ago against older code. All 5 findings had been resolved in subsequent commits
- **Impact**: 0/5 reached submittable — no end-to-end submission test possible with these targets
- **Fix needed**: Pick fresher issues for the next smoke batch, or create synthetic known-broken fixtures
- **Disposition**: fix in v1 (pick new targets for re-test)

### S12. Docker Desktop auto-start needed
- **Observed**: temporal-cluster crash-looped 42x because Docker Desktop wasn't running
- **Root cause**: Docker Desktop is a GUI app that doesn't auto-start on Windows boot
- **Impact**: Entire Temporal stack down until human intervention
- **Fix**: Wrapper now probes `docker version`, launches Docker Desktop if unreachable, polls for 180s
- **Disposition**: fix in v1 (DONE - commit 0cfa313 in hadoku_site)

## Prediction scorecard

From `smoke-targets.md` "Expected surprises":

1. "At least 2 of 5 findings are already fixed on main" — **CONFIRMED: 5 of 5** (underestimated staleness)
2. "markdownlint fixes trivial enough that Copilot may not add a test" — **MOOT** (never reached fix stage due to empty diff)
3. "jscpd duplicate is the riskiest — agent may misjudge scope" — **MOOT** (finding already resolved)

## Top-3 surprises for Phase 3.4

Ranked by impact (would block a real batch in Phase 4):

1. **S9 — Evidence download gap** (fixed): Without this, no Copilot-driven issue can ever pass the repro gate. Highest impact.
2. **S10 — CLAUDE_CODE_OAUTH_TOKEN missing**: The relevance judge gate is required for submission. Any real fix would be blocked here. Config fix needed.
3. **S11 — All targets stale**: Prevents validation of the submission/upstream-PR path. Need fresh targets.
