# Phase 1 build plan

Ordered build plan with per-step verification, phase gates between
phases, and a dedicated test plan. **Every step has an explicit "Done
when" criterion. Every phase has a gate that must pass before the next
phase begins.**

## Step format

Every step uses this format:

```
### Step X.Y — Name
- Output: file or artifact
- Test: how we verify it works
- Done when: explicit, observable criterion
```

## Phase gate format

Between phases, a **Phase Gate** lists every checkbox that must be
satisfied before moving on. Operator signs off on the gate in writing
(commit, comment, or chat acknowledgment) before the next phase starts.

A phase gate is not a suggestion — if any item is unchecked, work on the
next phase does not begin.

---

## Phase 0 — Prerequisites

Operator-driven setup. No vibedispatch code lands in this phase.

### Step 0.1 — Original 10 questions
- Output: decisions in [open-questions.md](open-questions.md)
- Test: every Q has a "RESOLVED" header
- Done when: ✓ already done (2026-04-13)

### Step 0.2 — ~~`WolffM-temporal` org~~ — WITHDRAWN
Superseded when decision #2 was revised on 2026-04-13 to the input-context
scrubbing model. No new org needed; the pipeline uses existing `WolffM/{repo}`
forks. See [cross-ref-isolation.md](cross-ref-isolation.md).

### Step 0.3 — ~~Quarantine PAT~~ — WITHDRAWN
Superseded with step 0.2. The pipeline uses the existing `gh` user token
plus `MSFT_SSO` routing in `services/github_api.py`. No new PAT needed.

### Step 0.4 — `cleanup_legacy_forks.py`
- Output: `scripts/cleanup_legacy_forks.py` with `--dry-run` and `--confirm` modes
- Test:
  - Unit: `tests/test_cleanup_legacy_forks.py` mocks `gh` calls and verifies the listing/backup/delete logic
  - Manual smoke (operator): run with `--dry-run`, verify the printed list matches the expected ~30 forks under `WolffM/*`
- Done when: dry-run prints the right forks AND `state/legacy-forks-backup.jsonl` is written with one record per fork (parent, branches, last commit, open PR refs)

### Step 0.5 — Run cleanup with `--confirm`
- Output: `state/legacy-forks-backup.jsonl` (kept forever per F2b); empty `WolffM/*` namespace for the cleaned forks
- Test: `gh repo list WolffM --fork` after cleanup returns 0 forks (or only forks unrelated to jade-hare)
- Done when: post-cleanup `gh` count is zero AND the backup file is committed to the repo (so we have history)

### Step 0.6 — File aggregator endpoint issues
- Output: 5 issues against `hadoku-aggregator` for the new endpoints (Q3)
- Test: each issue has a clear schema example and a link back to `docs/crimson-kitty/components.md`
- Done when: 5 issue URLs recorded in this doc

### Step 0.7 — Implement aggregator endpoints
- Output: 5 new endpoints in `hadoku-aggregator/api/recon/`
- Test: per-endpoint integration test in `hadoku-aggregator` that hits the endpoint with 3 known repos and validates the schema
- Done when: aggregator `pnpm test` passes + deployed to prod

### Step 0.8 — Verify aggregator endpoints from vibedispatch
- Output: smoke script `scripts/test_aggregator_endpoints.py`
- Test: script calls each new endpoint for 3 known repos (vibedispatch itself, microsoft/markitdown, mermaid-js/mermaid) and validates the response shape against a hand-written schema
- Done when: script exits 0

### Step 0.9 — Install `claude` CLI on prod
- Output: `npm install -g @anthropic-ai/claude-code@<pinned>` run on the production host
- Test: `claude --version` returns the pinned version
- Done when: version output matches expected; pinned version recorded in `docs/runbooks/claude-cli-prod-auth.md`

### Step 0.10 — Authenticate `claude` CLI on prod
- Output: `~/.claude/credentials.json` on prod host (machine-local)
- Test: `claude -p "respond with OK" --model haiku --output-format json` returns within 10s with exit 0
- Done when: canary command succeeds + runbook documents the OAuth steps for re-auth on host reprovision

### Step 0.11 — Canary baseline measurement
- Output: 10 consecutive canary calls on prod, recorded with timing
- Test: all 10 succeed; p95 latency < 5s; no unexplained errors
- Done when: timing CSV saved to `docs/runbooks/claude-cli-canary-baseline.csv` for future comparison

---

## Phase Gate: 0 → 1A

**ALL of these must be checked before any vibedispatch code lands for crimson-kitty:**

- [ ] `cleanup_legacy_forks.py --dry-run` output reviewed and approved by operator
- [ ] `cleanup_legacy_forks.py --confirm` executed; post-cleanup fork count is 0
- [ ] `state/legacy-forks-backup.jsonl` exists with N records (N matches pre-cleanup count) and is committed
- [ ] All 5 aggregator endpoints return valid schema for 3 known repos (script exits 0)
- [ ] `claude --version` on prod matches pinned version
- [ ] Canary command on prod returns OK in <10s
- [ ] 10-call canary baseline recorded
- [ ] Operator writes "Phase Gate 0 → 1A: PASS" in a commit message or chat acknowledgment

If any item fails, **stop**. File a follow-up question, fix, retest. Do
not proceed.

---

## Phase 1A — Infrastructure + foundational utilities

Goal: stand up Temporal, write the lowest-level utilities, prove they
work in isolation. **No workflow code yet.**

### Step 1A.1 — Add `temporalio` dependency
- Output: `backend/requirements.txt` updated; `temporalio>=1.5.0` pinned
- Test: `pip install -r backend/requirements.txt` succeeds in a fresh venv
- Done when: import works in a Python REPL: `from temporalio.client import Client`

### Step 1A.2 — Docker Compose for Temporal Cluster
- Output: `hadoku_site/services/temporal-cluster/docker-compose.yml` using `temporalio/auto-setup` (version-pinned to match the SDK), with named volume `temporal-postgres-data` for `/var/lib/postgresql/data`
- Test:
  - `docker compose up -d` starts cleanly
  - `curl localhost:7233` returns gRPC-style response (cluster is listening)
  - `docker compose down && docker compose up -d` — workflow history persists (verify via PostgreSQL `\dt` showing the same `default_partition.executions` row count)
- Done when: down/up cycle preserves data; Temporal Web UI at :8233 loads

### Step 1A.3 — mgmt-api `deploy-config.json` entries
- Output: hadoku_site `deploy-config.json` adds `temporal-cluster` (manages the docker compose process) and `vibedispatch-temporal` (Python worker, not yet implemented)
- Test:
  - `curl https://mgmt.hadoku.me/api/temporal-cluster/status` returns running
  - `pm2 list` on prod host shows both services
- Done when: pm2 lists both; mgmt-api can read status from both

### Step 1A.4 — `temporal/config.py` implementation
- Output: replace stub with real implementation; loads from env, validates required fields, raises clear errors on missing
- Test: `tests/temporal/test_config.py`:
  - `load_config()` returns valid config with all env vars set
  - `load_config()` raises `MissingConfigError` with helpful message when a required Temporal config var is missing (e.g. `TEMPORAL_HOST`)
- Done when: pytest passes + manual `python -c "from backend.temporal.config import load_config; print(load_config())"` works

### Step 1A.5 — `EvidenceStore` implementation
- Output: `backend/temporal/evidence/store.py` — full class, file/dir helpers, JSONL append
- Test: `tests/temporal/test_evidence_store.py`:
  - `write_text` / `read_text` round-trip preserves content
  - `write_json` / `read_json` round-trip preserves structure
  - `append_jsonl` appends correctly across multiple calls
  - `record_transition` produces valid JSONL records
  - `record_gate` produces valid JSONL records
  - `for_issue(batch, slug, num)` constructs the right path even with `/` in slug
  - Concurrent writes from multiple threads don't corrupt JSONL
- Done when: all 7 unit tests pass + manual smoke creates a fake issue dir, writes 5 records of each type, `cat`s the JSONL files to verify

### Step 1A.6 — `evidence/scanner.py` (cross-ref scanner)
- Output: `scan_for_url`, `scan_for_short_ref`, `scan_for_keyword_ref`, `scan_commit_messages`
- Test: `tests/temporal/test_evidence_scanner.py`:
  - **Positive cases** (must catch):
    - `https://github.com/microsoft/markitdown/issues/183` in body
    - `microsoft/markitdown#183` short ref in body
    - `Fixes #183` in commit message (with upstream slug as context)
    - `Closes microsoft/markitdown#183` in commit message
    - URL spread across two lines with markdown formatting
  - **Negative cases** (must NOT catch):
    - `#183` alone with no upstream context
    - `WolffM/markitdown#9` (our own fork ref, not upstream)
    - URL to a different repo
- Done when: all positive cases return non-empty leak lists; all negatives return empty

### Step 1A.7 — `temporal/judge.py` implementation
- Output: full implementation with semaphore (cap=3), canary check, `--output-format json`, `JudgeUnreachable` and `JudgeParseError` exception classes
- Test: `tests/temporal/test_judge.py`:
  - `_canary_or_raise()` raises `JudgeUnreachable` when subprocess returns non-zero (mock subprocess)
  - `_canary_or_raise()` raises `JudgeUnreachable` on timeout (mock subprocess.TimeoutExpired)
  - `_extract_json` parses a valid envelope correctly
  - `_extract_json` raises `JudgeParseError` on missing `result` field
  - `_extract_json` raises `JudgeParseError` when no fenced JSON block in text
  - `_extract_json` raises `JudgeParseError` on malformed JSON in fenced block
  - `score()` integration test: real call against local `claude` CLI, real rubric, verify `JudgeResult` returns
- Done when: 6 unit tests pass + 1 integration test passes against local `claude` CLI

### Step 1A.8 — Judge rubrics
- Output: `backend/temporal/rubrics/relevance_v1.md` and `backend/temporal/rubrics/submission_v1.md`
- Test:
  - Rubrics specify the 5 scoring axes from gates.md
  - Rubrics include 2-3 worked examples with expected scores
  - Each rubric ends with the expected JSON output format
- Done when: rubrics committed; will be calibrated in step 1E.5

---

## Phase Gate: 1A → 1B

- [ ] `pip install` of `temporalio` works
- [ ] Docker Compose temporal-cluster survives a `down && up` cycle with state intact
- [ ] mgmt-api shows both `temporal-cluster` and `vibedispatch-temporal` (latter may be "stopped")
- [ ] `tests/temporal/test_config.py` passes
- [ ] `tests/temporal/test_evidence_store.py` passes (7 tests)
- [ ] `tests/temporal/test_evidence_scanner.py` passes (positive + negative cases)
- [ ] `tests/temporal/test_judge.py` passes (6 unit + 1 integration)
- [ ] Two rubric markdown files exist
- [ ] Operator writes "Phase Gate 1A → 1B: PASS"

---

## Phase 1B — Sanitizer + Agent adapter

### Step 1B.1 — `temporal/sanitizer.py` implementation
- Output: two functions: `scrub_brief(brief, upstream_slug, issue_number)` for input-side scrubbing, `scan_outputs(pr_title, pr_body, commits, upstream_slug, issue_number)` for output-side scanning at submission. Plus the `SanitizerError` exception class.
- Test: `tests/temporal/test_sanitizer.py`:
  - **scrub_brief: URL stripping**: brief containing `https://github.com/microsoft/markitdown/issues/183` → URL replaced with neutral placeholder; `scrub_report` records the substitution
  - **scrub_brief: short ref stripping**: `microsoft/markitdown#183` → replaced; recorded
  - **scrub_brief: bare slug stripping**: standalone `microsoft/markitdown` → replaced with "the upstream project"; recorded
  - **scrub_brief: keyword stripping**: `Fixes #183` and `Closes microsoft/markitdown#183` → removed entirely
  - **scrub_brief: idempotent**: scrubbing already-clean text returns unchanged text and an empty scrub_report
  - **scrub_brief: preserves code**: a fenced code block containing the upstream slug as part of an import path is left alone IF the slug isn't an issue ref (best-effort; document the heuristic)
  - **scan_outputs: catches all 3 jade-hare leak fixtures** (markitdown#183, mermaid#4099, hoppscotch#3331) — fixtures pulled from the real PRs
  - **scan_outputs: tolerates hallucinated refs**: `Fixes #99999` against an upstream that has no #99999 → does NOT raise (only flags refs matching the workflow's recorded `upstream_slug + issue_number`)
  - **scan_outputs: catches commit-message leaks**: a commit whose message contains the upstream URL is detected even if title/body are clean
- Done when: 9 tests pass

### Step 1B.2 — `Agent` protocol
- Output: `backend/temporal/agents/__init__.py` with the `Agent` Protocol class, `AgentJob`, `AgentStatus`, `AgentResult` dataclasses
- Test: `tests/temporal/test_agent_protocol.py`:
  - `NoopAgent` (next step) implements the full protocol — type-check passes
- Done when: protocol exists and `NoopAgent` will satisfy it

### Step 1B.3 — `NoopAgent` implementation
- Output: `backend/temporal/agents/noop.py` — returns canned responses for testing
- Test: `tests/temporal/test_noop_agent.py`:
  - `assign()` returns a job ID
  - `poll()` returns "done" immediately
  - `harvest()` returns a hand-crafted `AgentResult` with predictable diff/commits
- Done when: 3 tests pass; this agent is what we use in workflow tests

### Step 1B.4 — `CopilotAgent` implementation
- Output: `backend/temporal/agents/copilot.py` — wraps the existing dispatcher logic from `services/dispatchers.py::CopilotSWEDispatcher`
- Test: `tests/temporal/test_copilot_agent.py`:
  - Mock `gh` calls; verify `assign()` issues the right `gh api` command
  - Mock `gh` polling; verify `poll()` translates Copilot states to `AgentStatus`
  - Mock harvest; verify `AgentResult` has the right fields
- Done when: 3 tests pass; manual smoke with a real Copilot assignment against a test issue in your own repo

---

## Phase Gate: 1B → 1C

- [ ] `tests/temporal/test_sanitizer.py` passes (4 tests)
- [ ] `tests/temporal/test_agent_protocol.py` passes
- [ ] `tests/temporal/test_noop_agent.py` passes (3 tests)
- [ ] `tests/temporal/test_copilot_agent.py` passes (3 tests)
- [ ] Manual smoke: assign Copilot to a real test issue in a private vibedispatch fork; verify `harvest()` returns the expected result shape
- [ ] Operator writes "Phase Gate 1B → 1C: PASS"

---

## Phase 1C — Activities + Gates

Each activity and gate is its own step with its own test. There are 12
activities (per components.md) and 11 gates (per gates.md). For brevity
this section lists groups; **each module gets a unit test before the
group's phase gate**.

### Step 1C.1 — Eligibility activity + gate
- Output: `activities/eligibility.py`, `gates/eligibility.py`
- Test:
  - `tests/temporal/test_activity_eligibility.py`: mock aggregator, verify dossier + brief + contributing scan are written to evidence
  - `tests/temporal/test_gate_eligibility.py`: 4 cases — pass, ai_policy=banned, assignee set, activity too low
- Done when: both test files pass

### Step 1C.2 — Fork + scrub-brief activity + `input_context_clean` gate
- Output: `activities/fork.py` (`ensure_fork`, `create_branch`, `scrub_brief`), `gates/input_context_clean.py`
- Test:
  - Unit `ensure_fork`: mock `gh` calls; verify `gh repo fork upstream/repo --clone=false` is invoked when the fork doesn't exist; verify the call is skipped when it already exists
  - Unit `create_branch`: mock `gh` calls; verify a descriptive operator-readable branch is created via the API
  - Unit `scrub_brief`: takes a real aggregator brief fixture with upstream URL/slug/number, runs the sanitizer, writes `02-forked/scrubbed_brief.md` + `scrub_report.json` to the evidence store, asserts the scrubbed file contains zero real refs
  - Unit `input_context_clean` gate: 4 cases — pass (clean brief), fail (URL survived), fail (short ref survived), fail (bare slug survived)
- Done when: all 4 tests pass

### Step 1C.3 — Environment activity + gate
- Output: `activities/environment.py`, `gates/environment.py`
- Test: unit tests with mocked subprocess; verify install/dev-server logs are captured to evidence; gate fails when `installable=false`
- Done when: tests pass

### Step 1C.4 — Repro activity + gate
- Output: `activities/repro.py`, `gates/repro.py`
- Test:
  - Unit: gate fails when `notes.md` missing, fails when notes <50 words, fails when sections missing, passes when all 3 conditions met + at least one of test/before.png/trace exists
- Done when: tests pass

### Step 1C.5 — Fix activity + gates (`diff_non_empty`, `relevance`)
- Output: `activities/fix.py`, `gates/fix.py`
- Test:
  - Unit `diff_non_empty`: empty diff fails, <50 byte diff fails, no commit SHAs fails, valid diff passes
  - Unit `relevance`: mock judge, test pass/defer/fail paths and exception handling (`JudgeUnreachable` → defer with `system:` prefix)
- Done when: tests pass; **this is the empty-PR killer — verify the `diff_non_empty` test catches all 6 jade-hare empty-PR examples (use real diffs from those PRs as test fixtures)**

### Step 1C.6 — Verify activity + gate
- Output: `activities/verify.py`, `gates/verify.py`, plus `tools/visual_diff.py` (pixel-comparison helper)
- Test:
  - Unit: passing test output → pass; missing → fail; before/after images visually identical → fail (visual diff <0.05); visually different → pass
- Done when: tests pass + manual smoke with two known-different screenshots

### Step 1C.7 — Review activity + remediation activity + gates
- Output: `activities/review.py`, `activities/remediation.py`, `gates/remediation.py`
- Test:
  - Unit `review`: mock review tool, verify comments parsed and severity classified
  - Unit `remediation`: gate fails when blocking comments unaddressed, passes when all addressed
- Done when: tests pass

### Step 1C.8 — Submission activity + gates (`no_upstream_refs`, `pr_template_compliance`, `submission_judge`)
- Output: `activities/submission.py`, `gates/submission.py`, `temporal/pr_body_builder.py`
- Test:
  - Unit `pr_body_builder`: takes structured payload, renders against a fixture PR template, verifies all sections filled
  - Unit `no_upstream_refs`: 3 positive (URL leak, short ref, keyword) and 3 negative cases
  - Unit `pr_template_compliance`: missing required section fails; all sections present passes
  - Unit `submission_judge`: mock judge, test pass/defer paths
  - **Integration**: feed the markitdown#183 leak as a test fixture; verify `no_upstream_refs` catches it
- Done when: all 5 tests pass

### Step 1C.9 — Watcher activities (notify_human_comments)
- Output: `activities/watchers.py` — wraps `helpers/notifications.py`
- Test:
  - Unit: mock `gh` poll, verify Discord webhook is called for new human comments only (no bot-comments)
  - Verify the existing `notify_human_comments` test suite still passes when called from the new activity
- Done when: tests pass; existing notification tests untouched

### Step 1C.10 — Inbox activities
- Output: `activities/inbox.py`
- Test: unit test that `enqueue_for_human_review` writes the right inbox entry to evidence and emits a `notify_inbox_queue` Discord call
- Done when: test passes

---

## Phase Gate: 1C → 1D

- [ ] All 10 activity test files pass
- [ ] All 11 gate test files pass
- [ ] **`diff_non_empty` test fixtures include all 6 jade-hare empty-PR examples**
- [ ] **`no_upstream_refs` test fixtures include the 3 jade-hare leak examples** (markitdown#183, mermaid#4099, hoppscotch#3331)
- [ ] `input_context_clean` gate test rejects all 3 leak forms (URL, short ref, bare slug)
- [ ] Visual diff helper produces correct scores for known image pairs
- [ ] Operator writes "Phase Gate 1C → 1D: PASS"

---

## Phase 1D — Workflows + Worker

### Step 1D.1 — `IssueWorkflow` implementation
- Output: `temporal/workflows/issue_workflow.py` — full implementation with state transitions, gate runs, signal handling
- Test: `tests/temporal/test_issue_workflow.py` using Temporal's `WorkflowEnvironment`:
  - **Happy path**: NoopAgent + mock gates that all pass → workflow reaches `submitted`
  - **Gate failure path**: one gate fails → workflow ends in `aborted` with right reason
  - **Defer path**: one judge gate defers → workflow pauses → operator signal → workflow resumes
  - **Inbox abort**: defer → operator signals `abort` → workflow ends in `aborted`
- Done when: 4 workflow tests pass

### Step 1D.2 — `BatchWorkflow` implementation
- Output: `temporal/workflows/batch_workflow.py`
- Test: spawns N child IssueWorkflows; verifies fanout, collects results
- Done when: test with 3 NoopAgent issues completes successfully

### Step 1D.3 — `temporal/worker.py` implementation
- Output: full worker entry point; connects to cluster, registers workflows, processes tasks
- Test: integration test starts the worker, dispatches a NoopAgent issue, verifies completion
- Done when: integration test passes

### Step 1D.4 — `routes/temporal_routes.py` wired into `routes/__init__.py`
- Output: Flask blueprint registered, all endpoints implemented
- Test: `tests/test_temporal_routes.py`:
  - GET `/api/temporal/health` returns cluster + worker status
  - GET `/api/temporal/batches` returns empty list when no batches exist
  - POST `/api/temporal/dispatch` starts a NoopAgent batch
  - GET `/api/temporal/inbox` returns empty when no defers
  - POST `/api/temporal/issue/.../signal` resolves a deferred workflow
- Done when: 5 endpoint tests pass

---

## Phase Gate: 1D → 1E

- [ ] All 4 IssueWorkflow tests pass
- [ ] BatchWorkflow test passes
- [ ] Worker integration test passes
- [ ] All 5 route tests pass
- [ ] Operator writes "Phase Gate 1D → 1E: PASS"

---

## Phase 1E — Integration smoke + judge calibration + durability

This is where we prove the system actually works end-to-end before
moving to Phase 2 (UI work).

### Step 1E.1 — End-to-end smoke with NoopAgent
- Output: an end-to-end run from `dispatch` through `submitted` using NoopAgent
- Test: `tests/temporal/test_e2e_noop.py` — full pipeline with mocked external services, but real EvidenceStore / sanitizer / gates
- Done when: a fake issue walks every state and produces an evidence directory matching the expected layout

### Step 1E.2 — End-to-end smoke with CopilotAgent on a private test issue
- Output: one issue dispatched against a private fork of vibedispatch with a deliberately injected bug
- Test: operator dispatches the issue, watches it run, verifies it reaches `submittable` (does not actually submit upstream)
- Done when: evidence directory contains all expected artifacts; gates all pass

### Step 1E.3 — Durability test (THE Temporal payoff test)
- Output: proof that durable execution actually works
- Test:
  1. Dispatch a NoopAgent workflow
  2. After it transitions to `fixed`, send `pm2 restart vibedispatch-temporal`
  3. Verify the workflow resumes automatically and finishes successfully
  4. Verify `transitions.jsonl` has no duplicate or out-of-order entries
- Done when: workflow survives a worker restart mid-stage with no manual intervention

### Step 1E.4 — Inbox signal flow test
- Output: proof that operator signals from the API actually unblock workflows
- Test:
  1. Dispatch an issue with a judge gate set to always defer (mocked)
  2. Verify the workflow pauses
  3. Verify the inbox API shows the entry
  4. POST `/api/temporal/issue/.../signal` with `decision: approve`
  5. Verify the workflow resumes and completes
- Done when: the round trip works

### Step 1E.5 — Judge calibration
- Output: hand-scored fixture set + measured judge agreement
- Test:
  1. Pick 20 hand-scored examples (10 for `relevance_v1`, 10 for `submission_v1`) covering pass / borderline / fail
  2. Hand-score each with operator's verdict
  3. Run the actual judge against each
  4. Measure agreement rate (within ±0.15 of operator score)
- Done when: agreement rate ≥ 80% on both rubrics; if <80%, iterate on the rubric markdown until threshold is hit

### Step 1E.6 — Sanitizer fixture test
- Output: 10 real diffs from jade-hare PRs (including the ones with leaked refs) tested through sanitizer
- Test: each diff sanitizes cleanly; the 3 leak fixtures are caught either by the rewriter or the defense-in-depth scan
- Done when: 10/10 fixtures pass

---

## Phase Gate: 1E → 2

- [ ] End-to-end NoopAgent test passes (test_e2e_noop.py)
- [ ] End-to-end CopilotAgent run against a private test issue reaches `submittable`
- [ ] Durability test passes (workflow survives a worker restart)
- [ ] Inbox signal flow test passes
- [ ] Judge agreement ≥ 80% on both rubrics
- [ ] Sanitizer catches all 3 jade-hare leak fixtures
- [ ] Operator writes "Phase Gate 1E → 2: PASS"

**This is the most important gate in the entire build.** If any of
these fail, the system isn't ready for UI work — fix Phase 1 first.

---

## Phase 2 — Operator UI

### Step 2.1 — API client + endpoints types
- Output: `frontend/src/api/endpoints.ts` adds `temporal/*` endpoints; `frontend/src/api/types.ts` adds the response types
- Test: `tests/temporal/test_api_types.py` (mirror Python types to TS) ensures parity
- Done when: types compile + parity test passes

### Step 2.2 — Zustand store
- Output: `frontend/src/store/temporalStore.ts`
- Test: vitest unit tests for store actions (mock fetch, verify state mutations)
- Done when: store tests pass

### Step 2.3 — Display components (StateBadge, GateResultRow)
- Output: presentational components
- Test: vitest snapshot tests for each visual variant (passing, failing, deferring)
- Done when: snapshot tests pass

### Step 2.4 — EvidencePreview
- Output: file-type-aware inline renderer (diff, image, JSON)
- Test: vitest tests for each file type with sample fixtures
- Done when: tests pass for all 3 types

### Step 2.5 — IssueDetail page
- Output: per-issue view with timeline, evidence, gates, transitions log
- Test: e2e Playwright test `frontend/e2e/local/temporal-issue-detail.spec.ts` — render with mocked API, verify all sections present
- Done when: e2e test passes

### Step 2.6 — PipelineInbox
- Output: inbox view with approve/abort/retry buttons
- Test: e2e Playwright test `frontend/e2e/local/temporal-inbox.spec.ts`:
  - Loads inbox with 3 mocked entries
  - Click approve → verify signal API called with right payload
  - Click abort → verify signal API called with right payload
  - Click retry → verify signal API called with right payload
- Done when: 4 e2e assertions pass

### Step 2.7 — TemporalPipelineView + PipelineSelectView tile
- Output: main view + integration into the picker
- Test: e2e Playwright test `frontend/e2e/local/temporal-pipeline-select.spec.ts`:
  - Picker shows 3 tiles
  - Click crimson-kitty tile → navigates to `/temporal`
- Done when: e2e test passes

### Step 2.8 — RetroView tab strip
- Output: tabs for Legacy / Temporal in `RetroView.tsx`; lazy-loaded content
- Test: e2e Playwright test `frontend/e2e/local/retro-tabs.spec.ts`:
  - Tab strip renders
  - Default tab loads legacy data
  - Clicking Temporal tab loads temporal data
- Done when: e2e test passes

---

## Phase Gate: 2 → 3

- [ ] All vitest unit tests pass (store, components)
- [ ] All Playwright e2e tests pass (5 files)
- [ ] Manual smoke: operator can navigate the entire crimson-kitty UI from picker → inbox → issue detail → approve a deferred mock workflow
- [ ] Operator writes "Phase Gate 2 → 3: PASS"

---

## Phase 3 — Pipeline correctness smoke test

**This phase tests pipeline mechanics, not merge rate.** Merge rate is
out of our control. What we can measure is: did every issue transition
correctly, did every gate fire correctly, did the operator inbox
behave correctly.

### Step 3.1 — Pick smoke targets
- Output: 5 issues hand-picked from vibecheck output against `hadoku-*` repos. **"Easy" means easy for the agent**, not the operator.
- Test: each picked issue has a clear scope + a known fix exists (operator could fix it manually in <30 min)
- Done when: 5 issue refs recorded in `state/crimson-kitty/smoke-targets.md`

### Step 3.2 — Dispatch and observe
- Output: 5 issues run through the pipeline
- Test: per-issue, record:
  - Did it reach a terminal state? (`merged`, `closed_by_upstream`, `aborted`, OR still `submitted` after 48h)
  - If `aborted`, was the abort reason clear and correct?
  - If `submittable`, did all 9 mechanical gates run and pass?
  - If `submitted`, did the upstream PR contain zero leaked refs?
  - Did the operator inbox surface the right defers (if any)?
- Done when: per-issue report written for all 5

### Step 3.3 — Surprise log
- Output: list of every observed behavior the operator did NOT expect
- Test: operator manually reviews each surprise and decides "fix in v1" / "fix in v2" / "won't fix"
- Done when: surprise log committed

### Step 3.4 — Fix top-3 surprises
- Output: code fixes for the 3 highest-impact surprises
- Test: re-run affected issues; verify behavior matches expectation
- Done when: re-runs match expected behavior

---

## Phase Gate: 3 → 4

- [ ] **5 of 5 smoke issues reached a clean terminal state OR `submittable`** (correctness, not merge rate)
- [ ] Zero cross-reference leaks observed across all 5 issues
- [ ] Zero empty PRs observed across all 5 issues
- [ ] Surprise log committed; top-3 surprises fixed
- [ ] Operator writes "Phase Gate 3 → 4: PASS"

---

## Phase 4 — First real batch (crimson-kitty)

### Step 4.1 — Dispatch the crimson-kitty batch
- Output: ~25 issues dispatched against external upstream repos selected via aggregator scoring
- Test: real-time monitoring; operator works the inbox in real time
- Done when: all 25 reach a terminal state OR `submittable` within 7 days

### Step 4.2 — Run `temporal_retro_report.py crimson-kitty`
- Output: full retrospective on the batch
- Test: report includes per-issue funnel, gate firing counts, judge agreement check, leak count (must be 0), empty PR count (must be 0)
- Done when: report committed

### Step 4.3 — Compare against jade-hare baseline
- Output: side-by-side: jade-hare vs crimson-kitty
- Test: confirm the bug classes from jade-hare are eliminated:
  - Cross-reference leaks: jade-hare 3 → crimson-kitty 0 (REQUIRED)
  - Empty PRs: jade-hare 6 → crimson-kitty 0 (REQUIRED)
  - "Completed without PR": jade-hare 17 → crimson-kitty 0 (REQUIRED, structural)
  - AI-slop callouts: jade-hare 5 → crimson-kitty target ≤1
  - Merge rate: jade-hare 1.8% → crimson-kitty target ≥10% (aspirational, not gating)
- Done when: comparison committed to `state/crimson-kitty/comparison-vs-jade-hare.md`

### Step 4.4 — Iteration round
- Output: top-5 fixes from the comparison
- Test: each fix has its own gate or test added
- Done when: fixes shipped; ready for batch 2

---

## Phase Gate: 4 → done

- [ ] 0 cross-reference leaks
- [ ] 0 empty PRs
- [ ] 0 "completed without PR" cases
- [ ] AI-slop callouts ≤ 1
- [ ] Comparison doc committed
- [ ] Top-5 fixes shipped
- [ ] Operator writes "crimson-kitty v1 SHIPPED"

---

## Test plan summary

Every test file we'll write across all phases.

### Unit tests (`backend/tests/temporal/`)
- `test_config.py` — config loading + validation
- `test_evidence_store.py` — file/dir/JSONL helpers
- `test_evidence_scanner.py` — leak detection (positive + negative)
- `test_judge.py` — canary, parse safety, exception classes
- `test_sanitizer.py` — git filter-branch rewrites + defense-in-depth
- `test_agent_protocol.py` — protocol satisfied by NoopAgent
- `test_noop_agent.py` — canned responses
- `test_copilot_agent.py` — mocked gh commands
- `test_activity_eligibility.py` — dossier + brief + contributing scan
- `test_activity_fork.py` — ensure_fork, create_branch, scrub_brief
- `test_activity_environment.py` — install + dev server logs
- `test_activity_repro.py` — evidence presence
- `test_activity_fix.py` — diff + commits + relevance
- `test_activity_verify.py` — test output + visual diff
- `test_activity_review.py` — comment parsing + severity
- `test_activity_remediation.py` — blocker resolution
- `test_activity_submission.py` — pr_body_builder + materialize
- `test_activity_watchers.py` — notify_human_comments wrapping
- `test_activity_inbox.py` — enqueue + Discord notify
- `test_gate_eligibility.py`
- `test_gate_input_context_clean.py`
- `test_gate_environment.py`
- `test_gate_repro.py`
- `test_gate_fix.py` (diff_non_empty + relevance) — **includes 6 jade-hare empty-PR fixtures**
- `test_gate_verify.py`
- `test_gate_remediation.py`
- `test_gate_submission.py` (no_upstream_refs + pr_template + submission_judge) — **includes 3 jade-hare leak fixtures**

### Integration tests (`backend/tests/temporal/`)
- `test_judge_integration.py` — real `claude` CLI call
- `test_e2e_noop.py` — full pipeline with NoopAgent
- `test_e2e_copilot.py` — full pipeline with real Copilot, manual fixture
- `test_durability.py` — workflow survives worker restart
- `test_inbox_signal.py` — defer + signal + resume

### Workflow tests (`backend/tests/temporal/`)
- `test_issue_workflow.py` — happy path, gate fail, defer, inbox abort
- `test_batch_workflow.py` — fanout

### Route tests (`backend/tests/`)
- `test_temporal_routes.py` — 5 endpoints

### Frontend unit tests (`frontend/src/`, vitest)
- `store/temporalStore.test.ts`
- `components/temporal/StateBadge.test.tsx`
- `components/temporal/GateResultRow.test.tsx`
- `components/temporal/EvidencePreview.test.tsx`

### Frontend e2e tests (`frontend/e2e/local/`, Playwright)
- `temporal-pipeline-select.spec.ts`
- `temporal-issue-detail.spec.ts`
- `temporal-inbox.spec.ts`
- `retro-tabs.spec.ts`

### Test fixtures (`backend/tests/temporal/fixtures/`)
- `jade-hare-empty-prs/` — 6 real diffs from jade-hare empty PRs
- `jade-hare-leaks/` — 3 real PR titles/bodies from leaked PRs
- `judge-calibration/relevance/` — 10 hand-scored examples
- `judge-calibration/submission/` — 10 hand-scored examples
- `visual-diff/` — known image pairs with expected scores

---

## Phase gate review process

Phase gates are not paperwork. They are the only thing standing between
"we built something that works" and "we built something that fails in
production." Every gate has the same review structure:

1. **Operator runs through the checklist** in person (locally), checking
   each item against the actual state of the system, not just the test
   logs
2. **All checked items go in a commit message** (or chat acknowledgment
   for non-code gates) so the gate is auditable later
3. **Any unchecked item halts the next phase** until resolved or
   explicitly waived in writing
4. **Waivers are allowed** but require a short justification recorded in
   the gate's audit log; waivers count as risk debt and are tracked

The gates are listed by phase in this doc. The operator is the only
person who can sign off on a gate.

---

## Things that are NOT in v1

To be explicit about scope cuts:

- **No replacement for Copilot.** The Agent adapter exists, but only
  CopilotAgent is implemented. Claude/local SWE agents are v2+.
- **No automated rubric tuning.** Judge rubrics are written and tuned
  by hand. Calibration step (1E.5) is a one-time hand-scoring effort.
- **No retroactive cleanup of legacy state.** Old `state/` JSONs are
  read by the legacy retro tool but never migrated.
- **No multi-operator support.** Single-operator inbox.
- **No SLA on judge response time.** 30-60 seconds is fine.
- **No automated rollback on bad batches.** Operator decides manually.
- **No upstream submission until Phase 3.2 explicitly enables it.**
  Phase 1E.2 deliberately stops at `submittable` and does NOT submit.

## Risk register

| Risk | Mitigation | Detected by |
|---|---|---|
| Temporal Cluster eats too much memory on the WSL host | Memory limit in compose; monitor; fall back to dedicated VM if needed | Phase 1A.2 manual smoke + ongoing host metrics |
| `claude` CLI auth on production server is fragile | Canary check on every judge call instantly catches it; gate auto-defers with `system:judge_unreachable`; manual fallback re-runs OAuth from runbook | Phase 0.10 + ongoing canary in 1A.7 |
| Claude Max usage cap hit mid-batch | Semaphore cap=3; canary catches the cap; affected gates defer to inbox | Phase 1A.7 unit tests |
| Claude CLI emits non-JSON garbage on stdout | `--output-format json` envelope + try/catch + `JudgeParseError` defer (no crash) | Phase 1A.7 unit tests |
| PostgreSQL data wiped on pm2 restart | Named volume `temporal-postgres-data` is a hard requirement | Phase 1A.2 down/up cycle test |
| `git filter-branch` produces a different SHA tree that breaks something downstream | Defense-in-depth scan after rewrite; sanitizer fixture test | Phase 1B.1 + 1E.6 |
| Aggregator endpoints (Q3) take longer than Phase 0 to ship | Crimson-kitty Phase 1 can technically run with inline fallbacks; uglier but unblocks | Phase 0.7 deadline |
| Smoke test reveals the agent can't reproduce its own bugs | Expected — that's what the smoke test is for. Tune the repro instruction and the rubric. | Phase 3.3 surprise log |
| Judge calibration falls below 80% agreement | Iterate on rubric markdown until threshold is hit; if no improvement after 3 iterations, escalate to operator decision (drop the gate or accept lower threshold) | Phase 1E.5 |
| Durability test fails (workflow doesn't resume after restart) | Investigate Temporal config; this is a Temporal misconfig, not a design failure. Likely a missing namespace or task queue setting. | Phase 1E.3 |
