# Architecture

## Five principles

These are load-bearing. Every component in this design follows from them. If
we relax any of them, the design needs to be revisited.

### 1. Every issue is an explicit state machine

The current pipeline is a sequence of stages that fire in order. There is no
single source of truth for "where is this issue right now." Stage 5 can fire
while Stage 3 silently failed. `completed_at` can be set without a PR existing.

The new pipeline models each issue as a Temporal workflow whose state is a
labeled node in a DAG. Every state transition is a recorded event with:
`{from_state, to_state, reason, evidence_path, decided_by, timestamp}`. The
orchestrator never asks "what stage runs next?" — it asks "what state is this
issue in, and what's the legal next state?"

See [state-machine.md](state-machine.md) for the state list.

### 2. Evidence is mandatory for every transition

Today, "swe_done_at" is a timestamp. Useless — it doesn't tell us *what* the
SWE step produced. The new design requires that every transition into a new
state is accompanied by an artifact written to the evidence store under
`state/{batch}/{issue}/{state}/`.

Examples:
- `reproduced/` → failing test file, screenshot, or browser trace
- `fixed/` → diff, list of files touched, commit SHAs
- `verified/` → passing test output OR an "after" screenshot visually
  different from the "before"
- `submittable/` → PR body draft, cross-ref scan results, template compliance
  check

If a stage cannot produce its evidence, the transition is rejected. This
single principle would have killed every empty PR in jade-hare.

### 3. Gates are first-class, declared, and uniform

In jade-hare, validation logic was scattered across five different mechanisms:
`_sanitize_upstream_refs` buried in `oss_service.py`, `is_bot` in
`bot_filter.py`, idempotency checks in stage handlers, comment scans in
notification code, and various `if` statements in the pipeline loop.

The new design has **one gate registry**. Each gate is:

```python
@gate(after=State.FIXED, kind="mechanical")
def diff_non_empty(issue, evidence) -> GateResult:
    diff = evidence.read("fixed/diff.patch")
    if not diff.strip():
        return Fail("no commits ahead of base")
    return Pass()
```

The orchestrator runs every registered gate after every state transition.
You can grep for every check in one file. You can write tests in isolation.
You can reason about which gates fired for which issue.

See [gates.md](gates.md) for the registry.

### 4. The agent is untrusted

Today we trust Copilot's output. In jade-hare, that trust failed:
- We trusted PR titles wouldn't leak refs (mermaid#4099 leaked via the title)
- We trusted commits would be real fixes (≥6 PRs were empty)
- We trusted the agent reproduced the issue (puppeteer didn't, then claimed
  fixes that didn't work)
- We trusted the diff would be on-topic (markitdown got unrelated import
  cleanup mixed in)

The new design assumes the agent produces dirty output. Every artifact gets
sanitized and validated *before* it reaches anything GitHub indexes. Concretely:

- Copilot pushes to **quarantine** repos in `WolffM-temporal` (private,
  separate org from `WolffM`)
- Branch names are hashed, never `fix-issue-1234`
- Commit messages and PR titles are rewritten via `git commit-tree` before
  being pushed to the public `WolffM/{repo}` fork
- The public fork is only created/updated at the very end, after all gates
  have passed
- The upstream PR is opened from the public fork only after `no_upstream_refs`
  gate passes

See [quarantine.md](quarantine.md).

### 5. Throughput is the wrong metric — confidence is

55 dispatched, 1 merged is a 1.8% confidence rate. We dispatched 55 things
we weren't confident about.

The new design treats dispatch as a high-bar filter. The pipeline rejects
any issue that can't pass a confidence threshold at multiple checkpoints.
Aborts are **first-class**, not failures: an issue we abort cleanly is a
better outcome than an issue we submit and embarrass ourselves over.

The retro tool will track abort reasons as carefully as merge reasons.

## Why Temporal

We considered three options: Temporal, Prefect, and a custom SQLite state
machine. Temporal won on five criteria.

| Criterion | Temporal | Prefect | Custom |
|---|---|---|---|
| Durable execution (frame-perfect resume after crash) | ✓ | partial | ✗ |
| Long-running workflows (hours-days) | ✓ | ✓ | partial |
| Pause-and-resume on human input (signals) | ✓ | ✓ | manual polling |
| Versioning (in-flight workflows survive code changes) | ✓ | partial | manual migrations |
| Observability UI (free) | ✓ | ✓ | build it ourselves |

The killer feature is **durable execution**. Copilot SWE steps take 30-180
minutes. Full pipelines take a day. The orchestrator pm2 process restarts on
every deploy. With Temporal, a workflow mid-step survives the restart and
picks up exactly where it was. With anything else, we re-implement that
property poorly with idempotency keys and state recovery code.

The killer pattern is **signals for the human inbox**:

```python
@workflow.defn
class IssueWorkflow:
    async def run(self, issue: IssueRef) -> IssueResult:
        # ... pipeline runs ...
        if gate_result.kind == "human_review":
            # Workflow sleeps until operator clicks approve/abort.
            decision = await workflow.wait_condition(
                lambda: self.human_decision is not None,
                timeout=timedelta(days=7),
            )
        # ... continue ...

    @workflow.signal
    def submit_human_decision(self, decision: HumanDecision):
        self.human_decision = decision
```

Three lines of code for the inbox model. No polling, no DB scanning, no
"awaiting_review" flag table.

**Operational cost:** one Docker Compose file (PostgreSQL + 4 Temporal
services + UI). ~2GB RAM. Runs alongside vibedispatch on the same pm2 host.
Self-hosted; no Temporal Cloud bill.

## High-level diagram

```
                          ┌──────────────────────────────┐
                          │     hadoku-aggregator        │
                          │  /recon/{slug}/health        │
                          │  /recon/{slug}/dossier       │
                          │  /recon/{slug}/issue-brief   │
                          └──────────────┬───────────────┘
                                         │ HTTP
                                         ▼
┌──────────────────┐    ┌───────────────────────────────────────┐
│  Operator UI     │    │           vibedispatch backend         │
│ (Pipeline Inbox) │◄──►│                                        │
│                  │    │  ┌────────────────────────────────┐   │
│                  │    │  │  Temporal worker process       │   │
│                  │    │  │  (pm2: vibedispatch-temporal)  │   │
│                  │    │  │                                │   │
│                  │    │  │  Workflows:                    │   │
│                  │    │  │   - IssueWorkflow              │   │
│                  │    │  │   - BatchWorkflow              │   │
│                  │    │  │  Activities:                   │   │
│                  │    │  │   - fetch_dossier              │   │
│                  │    │  │   - fork_to_quarantine         │   │
│                  │    │  │   - assign_copilot             │   │
│                  │    │  │   - poll_copilot               │   │
│                  │    │  │   - run_sanitizer              │   │
│                  │    │  │   - run_gates                  │   │
│                  │    │  │   - submit_upstream_pr         │   │
│                  │    │  │   - notify_human_comments      │   │
│                  │    │  └────────────────┬───────────────┘   │
│                  │    │                   │                    │
│                  │    │                   ▼                    │
│                  │    │  ┌────────────────────────────────┐   │
│                  │    │  │  Evidence store                │   │
│                  │    │  │  state/{batch}/{issue}/...     │   │
│                  │    │  └────────────────────────────────┘   │
│                  │    │                                        │
│                  │    │  Flask API (existing):                 │
│                  │    │   /dispatch/api/temporal/* (new)       │
│                  │    │   /dispatch/api/oss/* (legacy, stays)  │
│                  │    │   /dispatch/api/vibecheck/* (stays)    │
│                  │    └───────────────────┬────────────────────┘
│                  │                        │
│                  │                        │ Temporal gRPC
│                  │                        ▼
│                  │    ┌────────────────────────────────┐
│                  │    │   Temporal Cluster             │
│                  │    │   (Docker Compose)             │
│                  │    │    - PostgreSQL                │
│                  │    │    - frontend / matching /     │
│                  │    │      history / worker services │
│                  │    │    - Temporal Web UI :8233     │
│                  │    └────────────────────────────────┘
│                  │
└──────────────────┘
        │
        │ webhook
        ▼
   Discord (notifications, human comments alerts)
```

## Three-layer architecture

| Layer | Responsibility | Examples |
|---|---|---|
| **Workflows** | Orchestration logic. Deterministic. No I/O. Decide which activity to call next. | `IssueWorkflow`, `BatchWorkflow` |
| **Activities** | Side effects. Talk to GitHub, the aggregator, the file system, Discord. Wrap reusable utilities from `helpers/` and `services/`. | `fetch_dossier`, `assign_copilot`, `run_gate` |
| **Gates** | Pure functions over evidence. Decide pass/fail/defer. | `diff_non_empty`, `no_upstream_refs`, `pr_template_compliance` |

Activities are the thin layer where we wrap existing vibedispatch utilities.
They give us reuse without paying the cost of refactoring the utilities
themselves. `services/oss_firewall.py` becomes a one-line import inside an
activity.
