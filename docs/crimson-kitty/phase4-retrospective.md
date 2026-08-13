# Phase 4 retrospective — session of 2026-04-18 / 04-19

Session opened with Phase 3 shipped (deadlock + judge fixes verified in
smoke run r9) and closed mid-Phase-4 with the pipeline hardened by 7
distinct bug fixes but no external-upstream PR landed yet. Two dispatch
attempts, both ended at 10/10 aborted for different reasons. The value
wasn't the PRs — it was the bugs each attempt surfaced.

## Bug catalog

Ordered by when we hit them. Each bug has: class, root cause, fix, and
the thing it teaches about the pipeline.

### B1 — Workflow-task replay deadlock

- **Class**: Worker starvation / event-loop block
- **Symptom**: after a long `request_repro` activity (~2.7hr at
  `max_polls=1000` with no sleep), the subsequent workflow task to
  handle gate results timed out repeatedly at the sticky-task 10s
  timeout, looping forever. Worker restart didn't clear it.
- **Root cause**: `_wait_and_harvest` was a sync hot-loop making
  blocking `gh` subprocess calls from inside an `async def` activity.
  During the activity's ~2.7hr lifetime, the worker's asyncio event
  loop was fully blocked. When the activity finished and Temporal
  scheduled the next workflow task, no event-loop cycles were
  available to service it.
- **Fix**: `_wait_and_harvest` → async, `asyncio.sleep(20)` between
  polls, `asyncio.to_thread` wraps sync `gh` calls, `max_polls=90`
  (30-min bound), `activity.heartbeat()` each iteration, workflow
  sets `heartbeat_timeout=2min` so dead workers get detected.
- **Also shipped**: `task_timeout=60s` on `start_workflow` for replay
  headroom on the initial task.
- **Lesson**: Every sync call from an async def activity is a
  potential event-loop starvation vector. Pattern will recur — see
  B6 below.

### B2 — Judge CLI path unreachable on Windows

- **Class**: Deployment / env
- **Symptom**: every judge call failed `canary`: "claude binary not
  found: claude".
- **Root cause**: `npm install -g @anthropic-ai/claude-code` drops
  `claude`, `claude.cmd`, `claude.ps1` in `%APPDATA%\npm\`. Python's
  `subprocess.run(["claude", ...])` on Windows without `shell=True`
  does NOT find bare-name `.cmd` files from PATH.
- **Fix**: `CRIMSON_CLAUDE_BIN` set to the full `%APPDATA%\npm\claude.cmd`
  path in `ecosystem.config.cjs` for both Flask + worker.
- **Lesson**: "It works in bash" is not enough on a Windows pm2 host.
  Always be explicit about interpreter paths for subprocess calls.

### B3 — Aggregator issue-brief 404 on aged-out issues

- **Class**: Cross-system contract
- **Symptom**: 4/10 of phase4-external-v1 children crashed at
  eligibility with "aggregator returned non-object: NoneType".
- **Root cause**: Aggregator only serves `/issue-brief/{id}` for the
  top-100 scored issues per repo. Between our shortlist (pick time)
  and dispatch (execution time), scoring re-ran and some issues aged
  out of the window. Aggregator's own `recon:{slug}` KV blob also
  gets replaced on every scrape, so A5 (serve from raw consolidated
  blob) alone can't resurrect them.
- **Fix (cross-repo)**: Aggregator shipped `POST /compose-brief`
  (v2.2.16). vibedispatch eligibility now has 3 fallback rungs:
  1. GET `/issue-brief/{id}` — top-100 fast path
  2. GET `/scored-issues` → find snapshot → POST `/compose-brief`
  3. `gh api repos/{slug}/issues/{n}` → build ExtendedIssue → POST
     `/compose-brief`
- **Lesson**: cross-repo contracts decay. Add defense in depth
  on the consumer side even when the producer says they'll fix it.
  Also: filed a written audit at
  `hadoku-aggregator/docs/VIBEDISPATCH-AUDIT-2026-04-18.md`.

### B4 — Fork inherits `has_issues=false`

- **Class**: GitHub contract gotcha / regression from legacy
- **Symptom**: 6/10 of phase4-external-v1 children crashed at
  `request_repro`: "failed to create fork issue: gh: Issues has been
  disabled in this repository. (HTTP 410)".
- **Root cause**: When `gh repo fork` creates a new fork, GitHub
  defaults `has_issues=false` (forks are for code, file bugs
  upstream). `CopilotAgent.assign()` needs to create a context issue
  ON the fork to hand off to Copilot. That POST fails without the
  Issues tab enabled.
- **Legacy had this**: `OSSForkMixin.configure_fork_settings`
  PATCHed `has_issues=true` as step 1. I dropped that when porting
  to the Temporal activity.
- **Fix**: `_configure_fork_safety` in `backend/temporal/activities/fork.py`
  PATCHes `has_issues=true` before anything else.
- **Lesson**: When porting legacy code, itemize the steps and verify
  each one has a destination. Silent omission is easy.

### B5 — `WorkflowExecutionFailed` invisible to operator

- **Class**: Observability
- **Symptom**: Attempt #1's 10 children all ended at Temporal status
  `Failed`, not `Completed`. Our retro view only scans the `state/`
  directory for batches; crashed workflows left partial evidence (or
  none at all, for eligibility crashes). The operator had no UI
  signal — had to `tctl workflow observe` each one by hand.
- **Root cause**: `IssueWorkflow.run()` only caught `_GateFailed` and
  `_OperatorAborted`. Any other exception (RuntimeError from
  activities, ActivityError, etc.) propagated to Temporal as a
  workflow-level failure.
- **Fix**: Added generic `except Exception as e:` handler that
  produces `IssueResult(final_state="aborted",
  abort_reason="activity crashed at state={X}: {class}: {msg}")`. No
  more invisible crashes — they all surface as clean aborted states
  in the existing retro/batches endpoints.
- **Verified live**: in attempt #2, biomejs/biome crashed at
  `request_repro` and ended up as
  `final_state: "aborted", abort_reason: "activity crashed at
  state=environment_ready: ActivityError: Activity task failed"` —
  visible in the workflow output JSON and in retro.
- **Lesson**: "the workflow didn't catch it" should be the default
  expectation. Default to catching broad Exception with a clean
  abort, only carve out specific cases that have specific handling.

### B6 — Fork-safety PUT races async GitHub fork provisioning

- **Class**: Race condition / API timing
- **Symptom**: In attempt #2, 8/10 forks had `actions_policy_set:
  false, disabled_workflows: 0` in the fork_safety evidence. The
  has_issues PATCH mostly succeeded (7/8), but PUT `/actions/permissions`
  NEVER succeeded. **Critical**: inherited upstream CI remained
  armed on those 8 forks — budget-burn risk live.
- **Root cause**: `gh repo fork` returns when the fork is
  QUEUED, not when it's READY. Repo-level endpoints (especially
  `/actions/permissions`) can 404/422 for several seconds while
  GitHub provisions the fork asynchronously. Legacy had a
  `wait_for_fork` helper that polled existence — we didn't port it.
- **Fix**: `_gh_with_retry` helper with exponential backoff
  (1s, 2s, 4s, 8s, 16s; 5 attempts). Critical steps (has_issues,
  actions/permissions) now retry until success or raise
  `RuntimeError` on exhaustion. Workflow's new generic exception
  handler (B5) converts to clean abort.
- **E-stop fired during the incident**: 8 forks manually disabled
  (`enabled: false` via `gh api ... /actions/permissions`) and then
  deleted before any Copilot push could fire inherited CI.
- **Lesson**: GitHub is eventually consistent. Any API call made
  within ~30s of a write (fork, repo create, team add, etc.) needs
  retry + backoff. Should probably have a shared retry wrapper for
  all gh calls, not just fork-setup ones.

### B7 — sync retry blocking async event loop

- **Class**: Event-loop starvation (same class as B1)
- **Symptom**: Would have surfaced under attempt #3's fork-retry
  path — the new `time.sleep()`-based retry in
  `fork_and_scrub_brief` (called synchronously from `act_fork_and_scrub_brief`
  async def) would block the worker event loop for up to ~62s per
  retry sequence. With 10 parallel forks all retrying, it compounds.
- **Fix**: Wrapped the whole call in `asyncio.to_thread` so the
  retry sleeps run on a thread, not the event loop.
- **Lesson**: This is B1 all over again. **Every activity wrapper
  should default to `asyncio.to_thread` for its sync body.** The
  async-def-but-calls-sync pattern is a trap we keep walking into.

### B8 — `requests` missing from `requirements.txt`

- **Class**: Deployment contract
- **Symptom**: After a Python env rebuild on the Windows host, Flask
  crash-looped at startup with `ModuleNotFoundError: No module named
  'requests'`. The module had been imported for years by
  `services/oss_service.py`.
- **Root cause**: `requests` was never declared in requirements.txt.
  Previous env had it installed transitively from some other
  package. Something wiped that env.
- **Fix**: Added `requests>=2.31.0` to requirements.txt. Triggered
  `redeploy_service` (not just restart — that runs the `buildCommand:
  "pip install -r backend/requirements.txt"` per deploy-config.json).
- **Lesson**: pm2 `restart` doesn't reinstall deps. Only `redeploy`
  triggers `pip install`. If Python deps change, you need a full
  redeploy. The fact that Python deps lived in an under-declared
  state for months means our contract was loose — no CI lint of
  requirements.txt against actual imports.

## Non-bug observations (things that worked)

### ai_policy detection — working as designed

- llama.cpp in attempt #2 was rejected at eligibility gate with
  reason "repo CONTRIBUTING.md bans AI-generated PRs".
- This is the aggregator's A2 (`ai_policy` detection shipped in
  response to our audit) + our eligibility gate, working together.
- Prevented a PR going to a repo that explicitly disallowed AI
  contributions. Exact intended behavior.

### BatchWorkflow robustness

- BatchWorkflow uses `asyncio.gather(*coros, return_exceptions=True)`
  and converts any child crash to `abort_reason="child workflow
  crashed: ChildWorkflowError: ..."`. In attempt #1, all 10 child
  IssueWorkflows raised WorkflowExecutionFailed, but the parent
  BatchWorkflow completed successfully with 10 aborted results. No
  cleanup needed.
- Should mirror this pattern into IssueWorkflow itself (B5 did
  exactly this — catch-and-convert).

## Emerging patterns

Three classes of bug keep showing up:

1. **Event-loop starvation (B1, B7)** — sync work from async
   activities. Prevention: default pattern should be
   `asyncio.to_thread` wrapping the entire sync body of any
   activity. A style-guide / lint rule would help.

2. **GitHub eventual consistency (B4, B6)** — GitHub APIs that need
   retry/wait after writes. Prevention: central `gh_with_retry`
   wrapper for ALL gh calls, not just fork-setup. Currently each
   site handles this differently (or not at all).

3. **Deployment contract drift (B2, B8)** — "works on dev" doesn't
   reach prod because deps aren't declared, paths differ, etc.
   Prevention: CI that builds + runs the service in a clean Python
   env against every push would catch B8. B2 is harder (platform-
   specific) — needs runbook checklist.

## State left at compact

**Shipped in this session** (all in main, deployed):
- B1 fix: async poll + heartbeat + retry policy in agent activities
- B2 fix: CRIMSON_CLAUDE_BIN points at .cmd; canary endpoint
- B3 fix: 3-rung brief fallback in eligibility; aggregator audit
  written to `hadoku-aggregator/docs/VIBEDISPATCH-AUDIT-2026-04-18.md`
- B4 fix: `_configure_fork_safety` enables has_issues
- B5 fix: IssueWorkflow catches generic Exception → clean aborted
- B6 fix: fork-safety has 5-retry exponential backoff; raises on
  exhaustion
- B7 fix: `act_fork_and_scrub_brief` runs via `asyncio.to_thread`
- B8 fix: `requests` in requirements.txt
- Fork-safety whitelist tightened to `dynamic/copilot-swe-agent/copilot`

**Aggregator-side commits** (shipped to hadoku.me/oss/api):
- v2.2.15: A5 (serve issue-brief from consolidated raw data)
- v2.2.16: `POST /compose-brief` (caller-supplied ExtendedIssue)

**Cleaned up**:
- All 9 attempt-#2 forks deleted
- Attempt-#2 child workflows terminated
- Attempt-#2 parent BatchWorkflow terminated

**Not yet done**:
- **Attempt #3 dispatch** — ready to go once worker restart completes.
  The 10 targets are locked in (same shortlist as attempt #2, minus
  the already-aborted llama.cpp which will just abort again at
  eligibility if re-dispatched since the ai_policy ban hasn't
  changed).
- Worker restart + polling verification is the last step before
  dispatch.
- Aggregator tickets A1–A4, M1–M2 still open (audit doc tracks
  them). A5 + compose-brief shipped.

## Phase 4 scorecard so far

- Attempts: 2
- Completed workflows: 0 `submitted`, varied `aborted` reasons
- Copilot PRs merged upstream: 0
- Bugs found + fixed: 7 (B1–B7)
- Bugs found + deferred to aggregator team: 4 (A1–A4)
- External PRs from attempt #1 that leaked? 0 (none reached Copilot)
- External CI runs fired accidentally? 0 (e-stop in B6 caught it)
- WolffM account banned / flagged? No

The pipeline is measurably more robust after these two attempts than
it was at Phase 3 close. Phase 4 proper — external-upstream PRs
merged — remains unstarted.
