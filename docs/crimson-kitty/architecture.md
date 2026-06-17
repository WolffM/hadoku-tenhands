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

The new design assumes the agent produces dirty output AND assumes the agent
echoes whatever it was shown. Both ends of the pipeline get sanitized:

- **Input scrubbing** (primary): the issue brief is stripped of every real
  upstream URL, slash-form short ref, slug, and identifying issue number
  *before* it's passed to Copilot. The agent fixes the bug without knowing
  the upstream issue identity, so it cannot echo what it was never given.
- **Output sanitizer at submission** (defense in depth): the PR title, PR
  body, and all commit messages are scanned for real upstream refs at the
  `submittable → submitted` transition. Any real ref blocks the upstream
  PR open. Hallucinated refs (numbers the agent invented that don't match
  a real upstream issue) are tolerated as cosmetic noise.
- The agent's branches live directly on the existing `WolffM/{repo}` forks.
  No quarantine org, no PAT separation, no commit rewriting.
- The upstream PR is opened from the existing fork only after
  `no_upstream_refs` gate passes.

See [cross-ref-isolation.md](cross-ref-isolation.md).

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

There are two distinct uses of the `submit_human_decision` signal in the
state machine. Both use the same mechanism but model different operator
intents:

1. **Judge defer** — A judge gate (relevance after `fixed`,
   submission_judge after `submittable`) returns verdict=`defer` because
   it can't make a confident pass/fail call. The operator sees the
   judge's reasoning + score and decides. This is recovery from
   borderline machine output.

2. **Operator signoff** — Submittable gates have all passed, the
   replicate step has produced an operator-authored preview PR on the
   fork. The pipeline pauses at `awaiting_signoff` for a human
   go/no-go on actually opening the upstream PR. This is the
   intentional final-review gate — there's no judge defer here, the
   operator is just exercising final say-so.

The signoff use case has one extra invariant: when the operator
signals `approve`, `submit_upstream_pr` does NOT use the snapshot
in `09-submittable/pr_body.md`. It re-fetches the fork preview PR's
LIVE title and body via `gh api` (the operator may have edited
freely on GitHub between submittable and signoff — added screenshots,
expanded prose) and re-runs the output sanitizer on that live
content before opening upstream. Operator edits flow upstream
verbatim; an operator who pasted an upstream URL while editing
still trips the sanitizer and the workflow goes to `aborted`
without shipping.

Three lines of code for the inbox model. No polling, no DB scanning, no
"awaiting_review" flag table.

**Operational cost:** one Docker Compose file (PostgreSQL + 4 Temporal
services + UI). ~2GB RAM. Runs alongside tenhands on the same pm2 host.
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
│  Operator UI     │    │           tenhands backend         │
│ (Pipeline Inbox) │◄──►│                                        │
│                  │    │  ┌────────────────────────────────┐   │
│                  │    │  │  Temporal worker process       │   │
│                  │    │  │  (pm2: tenhands-temporal)  │   │
│                  │    │  │                                │   │
│                  │    │  │  Workflows:                    │   │
│                  │    │  │   - IssueWorkflow              │   │
│                  │    │  │   - BatchWorkflow              │   │
│                  │    │  │  Activities:                   │   │
│                  │    │  │   - fetch_dossier              │   │
│                  │    │  │   - fork_and_scrub_brief       │   │
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
│                  │    │   /tenhands/api/temporal/* (new)       │
│                  │    │   /tenhands/api/oss/* (legacy, stays)  │
│                  │    │   /tenhands/api/vibecheck/* (stays)    │
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

Activities are the thin layer where we wrap existing tenhands utilities.
They give us reuse without paying the cost of refactoring the utilities
themselves. `services/oss_firewall.py` becomes a one-line import inside an
activity.

### Long-activity poll pattern

The agent-driven activities (`request_repro`, `request_fix`, `request_verify`,
`request_remediation`) wait on Copilot to produce a PR, which can take
30+ minutes. They share one structure:

```
async def request_<phase>(agent, issue, brief, evidence, *, heartbeat):
    job = await asyncio.to_thread(agent.assign, issue, brief=brief, ...)
    result = await _wait_and_harvest(agent, job, heartbeat=heartbeat)
    # write evidence files + download files Copilot touched
    return {"ok": ..., "exit_reason": result.exit_reason}


async def _wait_and_harvest(agent, job, max_polls=90, poll_interval_s=20, *, heartbeat):
    for i in range(max_polls):
        heartbeat(f"poll {i + 1}/{max_polls}")
        status = await asyncio.to_thread(agent.poll, job)
        if status.state == "done": return await asyncio.to_thread(agent.harvest, job)
        if status.state == "failed": return <error result>
        await asyncio.sleep(poll_interval_s)
    return <timeout result>
```

Three non-obvious requirements this pattern satisfies:

1. **Don't starve the event loop.** `agent.poll()` and `agent.harvest()`
   call `gh` subprocesses that block. Wrapping them in `asyncio.to_thread`
   keeps the worker's asyncio loop free to serve workflow tasks for
   peer child workflows. Without this the worker deadlocks whenever any
   activity runs long: workflow tasks back up behind the blocked activity,
   hit the 10 s sticky-task timeout, and the workflow replay itself fails
   in a 10 s loop forever.
2. **Heartbeat every iteration.** The workflow sets
   `heartbeat_timeout=timedelta(minutes=2)` on these activities. Without
   a regular heartbeat Temporal treats the activity as dead and fires a
   `Heartbeat` timeout. 20 s polls + one heartbeat each keeps us well
   inside the window.
3. **Bounded wall clock.** `max_polls=90 × 20 s = 30 min` per phase. This
   caps the total history size for a single issue and prevents the old
   `max_polls=1000` runaway that produced ~2.7 hr activities.

The retry policy on long activities is `RetryPolicy(MaximumAttempts=1)`.
A worker restart mid-poll is deliberately a terminal workflow failure,
not a retry — Copilot has already been assigned the fork issue and
restarting the activity would create a second assignment + duplicate PR.
Operators accept that a worker restart costs in-flight work.
