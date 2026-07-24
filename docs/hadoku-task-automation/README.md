# hadoku-task-automation

**[crimson-kitty](../crimson-kitty/README.md)'s engine, with the two ends swapped.** Work arrives
from a [hadoku-task](https://hadoku.me/task) board instead of the aggregator, and lands by merging
to our own `main` instead of opening an upstream PR. The middle — clone, reproduce, fix, verify,
review — is the same proven code (§2).

| | crimson-kitty | hadoku-task-automation |
|---|---|---|
| Repo | someone else's, via a fork | ours |
| Input | aggregator CVS score + a rich issue brief | a sentence you typed on your phone |
| Output | an upstream PR a maintainer may merge | a merge to `main`, then a deploy |
| Optimises for | *confidence before dispatch* | *recoverability after landing* |

Two consequences drive everything below.

**The input got thin.** crimson-kitty's risk is "is this issue worth doing," answered from a rich
brief. This pipeline starts from eight words — *"fix the production CI workflow bug"* — so its risk
is **"do I even know what you're talking about."** That's why scoping is a first-class stage with
its own gates and its own way of asking you a question (§1, `needs-info`).

**The human left the loop.** crimson-kitty ends at a PR someone reviews. Here the work merges
unreviewed, so safety can't rest on a reviewer — it rests on landing being automatically
reversible (§4).

---

## 1. The loop

**The human gate is before the work, not after it.** You converse about the plan — which is a good
thing to do on a phone — and once you approve it, nothing else is asked of you. Reviewing a diff on
a phone is miserable; reading a plan and answering three questions is not.

```
  phone                       board                         tenhands
  ─────                       ─────                         ────────
  spitball a thought ──▶  Inbox (untagged)
                              │  claim
                              ▼
                     ┌──▶ planning (agent) ────────▶ interpret intent, design a plan,
                     │        │                      write plan + questions to notes
                     │        ▼
                     │   plan-review (user)  ──────▶ you answer / disagree
                     │      │        │
     answer, hand back│      │        │ happy
                     └── replan      ▼
                       (user)    approved (user) ───▶ ── nothing more is asked of you ──
                                     │  claim
                                     ▼
                                 working (agent) ───▶ repro → fix → verify → gates
                                     │                 └─ remediation loop, capped
                                     ▼
                                 landing (agent) ───▶ merge → deploy → watch prod
                                     │                            │ red
                     ┌───────────────┴───────┐                    ▼
                     ▼                       ▼               auto-revert
                landed (user)          stalled (user) ◀───────────┘
                merged + prod green    needs a laptop
```

Eight lanes, three of them `agent`. The board is [hadoku-task](https://hadoku.me/task); the
contract is [board-contract.md](board-contract.md); the activation payload is
[schemas/autoland-v1.json](schemas/autoland-v1.json). The planning loop is §3.

**One board per repo.** Board identity is repo identity — the board carries `repo` in its
activation payload, so a runner maps board → checkout without parsing display names, and the
repo (the one piece of context you always know) is never inferred.

### 1.1 The planning conversation

The plan lives in `notes`, and the loop runs until neither side has an open question.

**The lane model already solves the concurrent-write problem, for free.** The agent can only write
`notes` while holding a claim, and it only holds one while the task is in `planning`. You only edit
while it's in `plan-review`, where no claim is live. The handoff is a drag, so there is never a
moment where both sides are writing. That's worth noticing — it's the kind of thing that would
otherwise need a lock we'd have had to invent.

**Each pass rewrites `notes`, it does not append.** Three rounds of plan-then-answer would otherwise
grow into something you can't read on a phone, and would eventually trip `NOTES_TOO_LARGE`. The
planning agent re-emits one canonical document each time:

```markdown
## What I think you want
<one paragraph, in your terms>

## Plan
1. …

## Questions          ← the only part that needs you
1. …

## Settled            ← so you can see your earlier answers were heard
- <question> → <your answer>

## Blast radius
- path/to/file

— pass 2 · confidence 0.8
```

Full history stays in the evidence store and the board's claim log; `notes` stays legible.

**You answer however you like.** Inline under Questions, or a sentence dumped at the top — the
planning agent reads the whole field and works out what changed. Requiring a format from someone
typing on a bus would defeat the point.

**Two ways out of `plan-review`, both a single drag:**

- → `replan` — "I answered, or I disagree." Another planning pass.
- → `approved` — "Go." From here nothing else is asked of you.

Approving with questions still open is an **override, not an error**. You've decided they don't
matter; the pipeline records that in the evidence and proceeds. The alternative — bouncing your
approval back — would mean the pipeline second-guessing an explicit human decision, which is
exactly the wrong instinct in a system built to run without you.

**The loop is capped** (3 passes by default). Hitting the cap means the task isn't converging in
this medium, and the honest move is `stalled` — "this needs a laptop" — rather than a fourth round
of questions.

**Pickup from the Inbox is automatic, after a settle delay.** Untagged capture is the raw queue, and
the pipeline claims from it once a task has been untouched for a few minutes, so a half-typed
thought doesn't immediately get planned at. This is the one place we're guessing at your habits;
if it turns out you want an explicit "go" tap instead, that's one extra `user` lane and no other
change.

---

## 2. This is crimson-kitty with a different source and a different sink

The middle of the pipeline — clone, reproduce, fix, verify, review — is the same work regardless of
who filed the issue or where the result goes. That middle transfers **nearly whole**. What differs
is the two ends:

```
        crimson-kitty                                hadoku-task-automation
        ─────────────                                ──────────────────────
SOURCE  aggregator CVS score                  ◀──▶   hadoku-task board
        + upstream GitHub issue                      + one-line task text

        ┌──────────────────────── shared ────────────────────────┐
MIDDLE  │ environment → reproduce → fix → verify → review        │
        │ evidence store · gate registry · judge · Agent proto   │
        └────────────────────────────────────────────────────────┘

SINK    open upstream PR                      ◀──▶   merge to main
        watch the maintainer                         watch production, revert if red
        state lives in evidence + Temporal           state also projects onto board lanes
```

So the build is **three adapters around an existing workflow**, not a second pipeline:

| Seam | crimson-kitty | hadoku-task-automation |
|---|---|---|
| `TaskSource` — where work comes from | aggregator + GitHub issue | board poll + claim |
| `ProgressSink` — where state is published | evidence store + Temporal only | …plus board lane + `notes` |
| `Landing` — what "done" means | upstream PR, watch maintainer | merge to `main`, watch prod, auto-revert |

**The board is a state projection, not a database.** Temporal and the evidence store remain the
source of truth for pipeline state, exactly as today. The board is where that state becomes visible
and steerable from a phone — and the claim/lease is the lock that keeps two runners off one task.
That means `ProgressSink` is genuinely additive: a lane update after each transition we already
record.

### What actually gets deleted

Only the two things that would be *wrong* to run, not merely unnecessary:

| Component | Why it can't run |
|---|---|
| `sanitizer.py`, `oss_firewall.py`, `gates/input_context_clean.py` | Scrubbing upstream refs out of your own repo's task text corrupts it — the refs are legitimate |
| `oss_fork.py`, `oss_runner_setup.py` | We own the repo; there's no fork and nothing to hide from |
| `gates/submission.py` (491 lines) | Every check in it is about upstream PR etiquette and cross-ref leakage |
| `issue_workflow_post.py` (492 lines) | Maintainer-watching. **Replaced** by the prod watcher (§4), same polling shape |

Everything else — `activities/environment.py`, `test_runner.py`, `test_command_synthesizer.py`,
`review.py`, `agent.py`, `evidence/`, `judge.py`, and 7 of the 13 gates in
[gates.md](gates.md) — is reused, most of it unchanged. `issue_workflow.py`'s
`_transition(target, activity, arg) → record → run_gates` machinery is already generic over the
state name; it doesn't know or care that the states came from an OSS flow.

---

## 3. The agent is swappable

The existing `Agent` protocol (`backend/temporal/agents/__init__.py`) is already the right seam —
`assign` / `poll` / `harvest`, no Temporal imports, no global state. v1 ships a **`ClaudeCodeAgent`**
alongside the existing `CopilotAgent`, selected by config, not by import site.

```
TASKAUTO_AGENT=claude   # claude | copilot | noop
```

`ClaudeCodeAgent` runs headless `claude -p` inside a **git worktree** per task, so concurrent tasks
on one repo never collide and the main checkout is never touched — the same rule the humans follow.
It can read the whole repo, run the real test suite, and iterate, which is exactly what a one-line
task requires and what an issue-assignment agent cannot do.

Two protocol details need widening for a local agent, both additive:

- `IssueRef` is fork/upstream-shaped (`fork_slug`, `upstream_slug`, `upstream_number`) — and it
  appears in *two* places already (`agents/__init__.py` and `gates/__init__.py`), which is a
  duplication we should fix rather than triple. **Generalise it to one `WorkRef`**: `repo_slug`
  (where the work happens) plus an opaque `source_ref` (an upstream issue number, or a board task
  id) plus the upstream fields as optionals. crimson-kitty maps its existing fields in unchanged;
  the gates that actually need upstream identity are the ones being deleted anyway (§2).
- `AgentResult.exit_reason` gains `needs_info`, so an agent can report "I don't know what this
  means" as a first-class outcome rather than as an error.

### The anti-duplication rule

crimson-kitty's middle is proven code that survived a real batch and several retros. Copying it to
change three lines would throw that away and leave two things to fix every time a bug is found.

So: **the seams in §2 are parameterization, not forks.** Concretely, and these are testable claims,
not aspirations —

- **One copy of every gate module.** `fix.py`, `repro.py`, `verify.py`, `actionability.py` are not
  duplicated. They take config; the pipeline namespace (§5) decides which ones *run*, not which
  *version* runs.
- **Rubrics are data, not code.** G1 and G10 need different judge prompts, and that's a prompt file
  keyed by pipeline — not a second judge, and not an `if pipeline == …` inside `judge.py`.
- **One `_transition` implementation.** The `ProgressSink` is a constructor argument; crimson-kitty
  passes a no-op and is otherwise untouched.
- **If a step needs a module copied, the seam is in the wrong place.** That's the review question
  for every PR in this build, and specifically the acceptance test for step 6 in §7.

The honest risk is the opposite failure: contorting shared code with pipeline conditionals until
both callers are worse. If a module ends up with branching on pipeline identity in more than one
place, that module wanted splitting after all — but we find that out by trying to share first.

Swapping in a future agent means implementing three methods and adding one config value. Nothing
in the workflow, the gates, or the board integration knows which agent ran.

---

## 4. Auto-merge is safe because auto-revert is automatic

This is the load-bearing decision, and it is not "the gates are good enough."

Work lands on green with no human PR review. The gates in [gates.md](gates.md) are a real filter,
but no pre-merge gate set catches everything, and pretending otherwise is how you get a bad night.
What makes landing-without-review acceptable is that **the pipeline watches production after the
merge and reverts itself**:

1. Merge to `main`. Deploy fires (per repo, that's already the normal path).
2. Watch the deploy run and the service health signal for a fixed window.
3. Red deploy, red health check, or an error-rate spike inside the window →
   `git revert` the merge commit, push, move the task to `stalled` with the evidence.

Every landing is reversible by a follow-up commit, automatically, without your phone. That's the
same test your working agreement already applies to irreversible actions — this pipeline just
enforces it mechanically.

**The corollary is a per-repo eligibility bar.** A repo can only auto-land if it has:

- a test command that can go green, and
- a health signal worth watching (an endpoint, a deploy conclusion, a smoke test).

Without both, "on green" asserts nothing and revert has no trigger. Repos that don't clear the bar
don't get an auto-land board — they stay manual, or run the gated lane set noted in
[board-contract.md](board-contract.md). Rollout is therefore **per repo, starting with the ones
that already have CI**, not a flag day.

---

## 5. Two pipelines, one gate registry

`gates/__init__.py` holds `_registry` as a module-level list, and `run_gates(state, ...)` filters it
by state name only. Two pipelines importing gate modules into one worker process would cross-fire:
a state named `fixed` exists in both, and crimson-kitty's `submission` gates would run against a
task that has no upstream.

Before any gate code lands, `gate()` and `run_gates()` take a **pipeline namespace**:

```python
@gate(pipeline="taskauto", after="fixed", kind="mechanical")
def blast_radius_respected(task, evidence) -> GateResult: ...
```

Existing crimson-kitty gates default to `pipeline="crimson-kitty"`, so the change is mechanical and
the current registry snapshot is unchanged. `registry_snapshot()` grows a pipeline column, which the
retro tooling reads.

This is the one piece of shared code that must change before the new pipeline is safe to run in the
same worker. It is not optional and it is not a later cleanup.

---

## 6. Naming

Temporal namespace and queues follow the crimson-kitty convention:

```
TEMPORAL_NAMESPACE   = hadoku-task-automation
TEMPORAL_TASK_QUEUE  = hadoku-task-automation-tq
TEMPORAL_AGENT_QUEUE = hadoku-task-automation-agent-tq   # capped concurrency
```

Batch/run vocabulary from crimson-kitty (`/active`, `/inbox`, `/retro-batch`) does not carry over —
this pipeline is a continuous queue, not a batch. Its operational surface is the board itself, which
is the point: the status view is something you can read on a phone.

---

## 7. Status

Design. Nothing is built. hadoku-task's automation surface (activation, claim/lease runtime) is
also not built — they are blocked on our answer, which is [board-contract.md](board-contract.md).

Build order, once the contract is agreed. Note how little of it is new pipeline and how much is
adapters around the existing one:

1. **Namespace the gate registry** (§5) — unblocks everything, touches crimson-kitty, do it first.
2. **`TaskSource` seam + board client** — poll → claim → heartbeat → set-lane → release. The new
   input end (§2).
3. **`ProgressSink` seam** — mirror each recorded transition onto a board lane. Additive to
   `_transition`; crimson-kitty gets a no-op sink and is otherwise untouched.
4. **`TaskRef` + `ClaudeCodeAgent`** against the existing `Agent` protocol (§3).
5. **Scoping stage** — `actionability.py` with a new rubric, plus `repro_possible`. The cheapest
   place to stop a task, and the one that makes the phone loop work.
6. **Middle: reuse as-is** — environment → repro → fix → verify. This is the step that should be
   mostly configuration, and if it isn't, the seams in §2 are in the wrong place.
7. **`Landing` seam** — merge, prod watcher, auto-revert (§4). The new output end.

Steps 2, 3 and 7 are the actual new work. Step 6 is the test of whether this framing was right.
