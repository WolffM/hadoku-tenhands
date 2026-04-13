# Phase 1 build plan

Given the locked decisions and the four blocking follow-ups (F1-F4) that
need answers first, here's the ordered plan once we have those.

## Phase 0 — Prerequisites (this week, before any new code lands)

| Step | Owner | Output |
|---|---|---|
| 0.1 | Operator | ✓ F1-F5 answered (2026-04-13) |
| 0.2 | Operator | Create `WolffM-temporal` GitHub org (private) |
| 0.3 | Operator | Create `TEMPORAL_QUARANTINE_PAT`, add to local `.env` and to hadoku_site secret store |
| 0.4 | Code (in vibedispatch) | Implement `scripts/cleanup_legacy_forks.py` (backup + dry-run + delete with `--confirm`) — **deletes ALL forks, no exclusion for open PRs** (F2c) |
| 0.5 | Operator | Run `cleanup_legacy_forks.py --dry-run`, review, run with `--confirm` |
| 0.6 | Code (in hadoku-aggregator) | File 5 issues for new endpoints (Q3) |
| 0.7 | Code (in hadoku-aggregator) | Implement the 5 new endpoints |
| 0.8 | Code (in hadoku-aggregator) | Deploy aggregator with new endpoints; verify from vibedispatch |
| 0.9 | Operator (on prod host) | Install `claude` CLI: `npm install -g @anthropic-ai/claude-code@<pinned>` (F1a) |
| 0.10 | Operator (on prod host) | Run `claude` OAuth flow once; document steps in `docs/runbooks/claude-cli-prod-auth.md` (F1b) |
| 0.11 | Operator | Verify canary works on prod: `claude -p "respond with OK" --model haiku --output-format json` returns within 10s |

Phase 0 is **not Temporal work** — it's the prereqs that unblock Phase 1.

## Phase 1 — Foundations (week 1)

| Step | Module | Output |
|---|---|---|
| 1.1 | Infra | Add `pyproject` deps: `temporalio>=1.5.0` |
| 1.2 | `hadoku_site/services/temporal-cluster/docker-compose.yml` | Temporal Cluster (`temporalio/auto-setup` image, version-pinned to match SDK) on the same host as vibedispatch. **Must include a named volume `temporal-postgres-data` for `/var/lib/postgresql/data`** (F4) so workflow history survives `docker compose down && up` cycles triggered by pm2 restarts. |
| 1.3 | `hadoku_site/services/mgmt-api/deploy-config.json` | Add `temporal-cluster` and `vibedispatch-temporal` entries. The `vibedispatch-temporal` setup script must `npm install -g @anthropic-ai/claude-code@<pinned>` and verify with the canary command (F1a). |
| 1.4 | `backend/temporal/config.py` | Implement (currently a stub) |
| 1.5 | `backend/temporal/evidence/store.py` | Full `EvidenceStore` implementation, file I/O, JSONL append helpers |
| 1.6 | `backend/temporal/evidence/scanner.py` | `scan_for_url`, `scan_for_short_ref`, `scan_for_keyword_ref`, `scan_commit_messages` |
| 1.7 | `backend/temporal/sanitizer.py` | Full implementation, including `git filter-branch` rewrite + defense-in-depth scan |
| 1.8 | `backend/temporal/agents/copilot.py` | Wraps existing dispatcher logic in an `Agent` adapter |
| 1.9 | `backend/temporal/agents/noop.py` | Noop adapter for tests |
| 1.10 | `backend/temporal/judge.py` | claude CLI subprocess wrapper with semaphore (cap=3), canary check (10s timeout), `--output-format json`, parse-safe with `JudgeUnreachable` and `JudgeParseError` exceptions both deferring to inbox. + 2 rubrics: `relevance_v1.md`, `submission_v1.md`. |
| 1.11 | `backend/temporal/worker.py` | Worker entry point: connects to cluster, registers workflows + activities |
| 1.12 | `backend/temporal/workflows/issue_workflow.py` | `IssueWorkflow` end-to-end |
| 1.13 | `backend/temporal/workflows/batch_workflow.py` | `BatchWorkflow` fanout |
| 1.14 | `backend/temporal/activities/*.py` | All 12 activity modules from components.md |
| 1.15 | `backend/temporal/gates/*.py` | All 11 gate modules from gates.md |
| 1.16 | `backend/routes/temporal_routes.py` | Wire into `routes/__init__.py`, implement endpoints |
| 1.17 | `backend/tests/temporal/test_*.py` | Test suite (gates, sanitizer, evidence store, end-to-end with mocks) |

**Exit criteria for Phase 1**:
- A test issue can be dispatched against a private repo of yours
- It walks through every state successfully or aborts with a clear reason
- The Pipeline Inbox shows it correctly
- Discord notifications fire for each transition
- The retro tool reads its evidence store

## Phase 2 — Operator UI (week 2)

| Step | Module | Output |
|---|---|---|
| 2.1 | `frontend/src/api/endpoints.ts` | New `/api/temporal/*` endpoints |
| 2.2 | `frontend/src/store/temporalStore.ts` | Zustand slice |
| 2.3 | `frontend/src/components/temporal/StateBadge.tsx` | Color-coded state badge |
| 2.4 | `frontend/src/components/temporal/EvidencePreview.tsx` | Diff/image/JSON inline renderer |
| 2.5 | `frontend/src/components/temporal/GateResultRow.tsx` | Gate result row |
| 2.6 | `frontend/src/components/temporal/IssueDetail.tsx` | Per-issue page: timeline, evidence, gates, transitions log |
| 2.7 | `frontend/src/components/temporal/PipelineInbox.tsx` | Inbox with approve/abort/retry buttons |
| 2.8 | `frontend/src/views/TemporalPipelineView.tsx` | Main view |
| 2.9 | `frontend/src/views/PipelineSelectView.tsx` | Add the third tile |
| 2.10 | `frontend/src/views/RetroView.tsx` | Add tab strip (Legacy / Temporal) |

**Exit criteria for Phase 2**:
- Operator can select crimson-kitty from the picker
- Inbox shows pending issues, evidence renders inline
- Approve/abort/retry buttons send Temporal signals correctly
- Retro view shows both legacy and temporal batches

## Phase 3 — Smoke test (week 3)

| Step | Output |
|---|---|
| 3.1 | Query vibecheck output for issues filed against `hadoku-*` repos. Pick 3-5 with small scope (small fix label or equivalent). **"Easy" means easy for the agent**, not the operator — we're testing whether Copilot SWE can navigate an unfamiliar codebase through the full state machine. |
| 3.2 | Dispatch those issues through crimson-kitty manually |
| 3.3 | Watch them run; tune gates and rubrics based on what we see |
| 3.4 | Document what worked, what didn't, what needs adjustment |
| 3.5 | Fix the highest-impact issues from 3.4 |

**Exit criteria for Phase 3**: at least 2 of the 5 smoke-test issues
reach `merged` state. (A high bar — we're testing the pipeline as much
as the agent.)

## Phase 4 — First real batch + iteration (week 4)

| Step | Output |
|---|---|
| 4.1 | Dispatch the first crimson-kitty batch — `crimson-kitty` itself, the existing batch with 1 issue, expanded to ~25 |
| 4.2 | Monitor closely; operator works the inbox in real time |
| 4.3 | After 48h, run `temporal_retro_report.py crimson-kitty` |
| 4.4 | Identify the top 3 surprises and write fixes |
| 4.5 | Ship the fixes |

**Exit criteria for Phase 4**: merge rate ≥ 10% (vs jade-hare's 1.8%).
If we don't hit 10%, we keep iterating before opening a public second
batch.

## Things that are NOT in v1

To be explicit about scope cuts:

- **No replacement for Copilot.** The Agent adapter exists, but only
  CopilotAgent is implemented. Claude/local SWE agents are v2+.
- **No automated rubric tuning.** Judge rubrics are written by hand.
  Tuning happens by reading retro reports and editing the markdown.
- **No retroactive cleanup of legacy state.** Old `state/` JSONs are
  read by the legacy retro tool but never migrated.
- **No multi-operator support.** Single-operator inbox. Multi-user comes
  later if needed.
- **No SLA on judge response time.** Subprocess can take 30-60 seconds,
  that's fine because issues take hours.
- **No automated rollback on bad batches.** If a batch goes badly, the
  operator runs `temporal_retro_report` and decides what to do manually.

## Risk register

| Risk | Mitigation |
|---|---|
| Temporal Cluster eats too much memory on the WSL host | Set cluster memory limit in docker-compose; monitor; fall back to dedicated VM if needed |
| `claude` CLI auth on production server is fragile | Canary check on every judge call catches it instantly; gate auto-defers with `system:judge_unreachable`. Manual fallback: re-run OAuth from runbook. |
| Claude Max usage cap hit mid-batch | Semaphore (cap=3) limits parallel calls; canary catches the cap; affected gates defer to inbox; operator can resume after cap resets |
| Claude CLI emits non-JSON garbage on stdout | `--output-format json` envelope + try/catch + `JudgeParseError` defer (no crash) |
| PostgreSQL data wiped on pm2 restart | Named volume `temporal-postgres-data` is a hard requirement on the Compose file (F4) |
| `git filter-branch` rewrite produces a different SHA tree that breaks something downstream | Defense in depth: scan rewritten history before push; compare materialized branch against quarantine via diff |
| Aggregator endpoints (Q3) take longer than a week | Phase 1 can ship without them by inlining fallbacks in vibedispatch; uglier but unblocks Phase 2 |
| Smoke test reveals the agent can't reproduce its own bugs | Expected — the smoke test is meant to find this. Tune the repro instruction and rubric. |
| A jade-hare bug class we missed | retro_report on first crimson-kitty batch will surface it; iterate |
