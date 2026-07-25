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
its own gates and its own way of asking you a question (§1.1–1.2).

**The human left the loop.** crimson-kitty ends at a PR someone reviews. Here the work merges
unreviewed, so safety can't rest on a reviewer — it rests on landing being automatically
reversible (§4).

---

## 1. The loop

**The human gate is before the work, not after it.** You converse about the plan — which is a good
thing to do on a phone — and once you approve it, nothing else is asked of you. Reviewing a diff on
a phone is miserable; reading a plan and answering three questions is not.

```
  phone                     board                          tenhands
  ─────                     ─────                          ────────
  dump 7 thoughts ───▶  Inbox (untagged)
                            │  claim
                            ▼
                       planning (agent) ──────▶ read it, work out the target,
                            │                   triage: trivial or worth a conversation?
              ┌─────────────┴──────────────┐
      trivial │                            │ vague · big · subjective · "already done?"
              │                      plan-review (user) ─────▶ you answer / disagree
              │                            │        │
              │                     happy  │        │  answered
              │                            │        ▼
              │                            │     replan (user) ──┐
              │                            ▼                     │
              └──────────────────▶   approved (user) ◀───────────┘
                                          │
                                          │  ── nothing more is asked of you ──
                                          ▼
                                     working (agent) ──▶ repro → fix → verify → gates
                                          │               └─ remediation, capped at 3
                                          ▼
                                     landing (agent) ──▶ merge → deploy → watch prod
                                          │                          │ red
                       ┌──────────────────┴────────┐                 ▼
                       ▼                           ▼            auto-revert
                  landed (user)              stalled (user) ◀────────┘
                  merged + prod green        needs a laptop
                  or "no change required"
```

Eight lanes, three of them `agent`. The board is [hadoku-task](https://hadoku.me/task); the
contract is [board-contract.md](board-contract.md); the activation payload is
[schemas/autoland-v1.json](schemas/autoland-v1.json), which we also publish for hadoku-task to
fetch ([preset-endpoint.md](preset-endpoint.md)) so nobody keeps a pasted copy of it.
Intake is §1.1, the planning loop §1.2.

**One board per repo.** Board identity is repo identity — the board carries `repo` in its
activation payload, so a runner maps board → checkout without parsing display names, and the
repo (the one piece of context you always know) is never inferred.

### 1.1 Intake: what a task actually looks like

Tasks arrive already atomic — one per line, filed by hand on the repo's board:

```
make coffee theme default
bug-wooshing starts before music starts
category headers look like buttons
needs starter prompt instead of "the stage is yours. make your move."
```

**The task is the unit of work and the unit of landing.** No splitting, no parent/child — the human
already decided where the boundaries are, and second-guessing that would create board cruft for no
gain.

Some tasks are a single line and one change. Others are multi-line and need several changes to be
done — `reorganize categories, interesting stuff front and center` is one goal that touches a
handful of files. Those stay **one task**: the plan enumerates the sub-changes, each gets its own
acceptance check (§ [gates.md](gates.md) G2), and the gates run over the combined diff against the
union of the declared blast radii.

**Landing is all-or-nothing per task.** If a three-change task verifies two and fails one, the
whole thing routes to `plan-review` — *"these two work, this one doesn't, here's why: want me to
land the two and hand the third back?"* Partial silent landing would leave the board saying `landed`
about a task that isn't, and "is this done" is the one question the board has to answer honestly.

**`bug-` is your own convention and we use it verbatim.** You already distinguish
`bug-wooshing starts before music starts` from `make coffee theme default`, and that distinction is
exactly the one the gates need:

- **`bug-` prefixed** → a claim that something is broken. Repro-first: demonstrate it red, fix it,
  demonstrate it green (gates G2/G3/G8).
- **unprefixed** → a change request. There's nothing to reproduce, because nothing is claimed to be
  broken. Verification is "the described end state is now true," not a red→green transition.

This resolves a tension in the first draft of the gates, which demanded a reproduction from
everything and would have stalled `make coffee theme default` forever for lack of a bug to
reproduce.

**Triage decides whether the planning conversation happens at all.** Forcing
`hide 'generating with GLM-5'` through a plan-review round trip is pure friction — there is nothing
to ask. So intake sorts each item onto one of two paths:

| | Fast path — released straight to `approved` | Conversation path — via `plan-review` |
|---|---|---|
| Looks like | names its own target, one obvious change, small blast radius, no taste involved | vague, subjective, large, or several plausible readings |
| From your examples | `make coffee theme default`, `hide 'generating with GLM-5'`, `needs starter prompt instead of "the stage is yours. make your move."` (quotes the exact current string — greppable) | `too much wooshing`, `redo the profile feature so it actually works`, `reorganize categories, interesting stuff front and center` |

The fast path releases to `approved` rather than jumping into `working` directly. `approved` is a
`user` lane, so an auto-approval is *visible* on the board and the ordinary claim-from-approved path
picks it up — one mechanism, no special case, and you can see what got waved through.

A fast-path task that fails its gates falls back to the conversation path rather than straight to
`stalled` — the pipeline's confidence that something was trivial is itself a guess worth revisiting.

**Never dismiss a task unilaterally.** You flagged the real tension: trust the board as real work,
but don't build cruft. Some items will be already done (`make coffee theme default` — is it
already?), some aren't bugs, and `pygmalion missing theme?` is a *question*, not a task at all.

The rule is: **the pipeline may never conclude a task is garbage.** It can only report *"I checked,
and here's what I found"* — with evidence — and route to `plan-review`, which is already the lane
that means "I need something from you." You either approve the finding, and it moves to `landed`
with `no change required` in the notes, or you say "no, it really is broken, here's how to see it,"
and the existing loop takes it from there.

Every dismissal is therefore human-confirmed, and it costs no new lane. The failure mode this
avoids is the bad one: a pipeline that quietly decides your bug report was mistaken.

**One task in flight per repo.** Several of the hadoku-site items touch the same UI, and independent
concurrent diffs against overlapping files would collide. Claims give us per-task locking; per-repo
serialisation we enforce ourselves by declining to claim while another task on that board sits in an
`agent` lane. At the volumes here that costs nothing and removes a whole class of merge conflicts.

### 1.2 The planning conversation

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

- ~~Generalise `IssueRef` into one `WorkRef`~~ — **tried and reversed during the build.** The idea
  was to avoid a third copy of a ref type. But writing both field sets out, they overlap on almost
  nothing: crimson-kitty needs `fork_slug` / `upstream_slug` / `upstream_number`, this pipeline
  needs `repo_slug` / `board` / `task_id` / `notes_at_claim` / `policy`. The union would be a type
  where half the fields are always `None` and every gate has to know which half applies to it.
  Two small honest types beat one dishonest one, so `taskauto/refs.py` defines its own `TaskRef`
  and `run_gates` takes the subject as an opaque value. The anti-duplication rule below is about
  not forking shared *behaviour* — `fix.py`, `repro.py`, the judge — and that still holds.
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

### 4.1 The daily canary is the prerequisite, and it doesn't exist yet

We decided against duplicating the ecosystem into a pre-prod environment: the catastrophic-failure
set is small and specific (edge-router, session/auth, vault broker, mgmt-api, cloudflared tunnel),
those five should never be autonomous whether or not a PPE exists, and everything else is revertible
in minutes. A standing duplicate would cost weeks up front and then drift — and a PPE that has
drifted is worse than none, because a green run there buys false confidence.

What replaces it is **one e2e test per product**, used at two different cadences. These are the same
artifact and it's worth being precise that they are not the same mechanism, because an earlier draft
of this section ran them together:

| | Trigger | Answers | Latency that matters |
|---|---|---|---|
| **Post-merge health check** (G12) | on demand, right after a merge deploys | "did *this* change break it?" | minutes — it gates the auto-revert |
| **Daily canary** | cron | "did anything break without us noticing?" | a day — it's a fire alarm |

A daily schedule can't drive auto-revert; by the time it fires, the revert window is long gone and
several other changes have landed. So G12 runs the spec **on demand** against the freshly deployed
service, and the cron run is the independent backstop for slow-burn breakage — including breakage
from things this pipeline never touched.

Building the spec once buys both.

Current state in `hadoku_site`, which is worse than it looks:

- **16 Playwright specs exist** (`e2e/`), covering roughly half the surface: contact-api,
  monitoring-api, printtool-api, resume-api, task-api, tunnel-routes, hydration, the vault tiers,
  pm2 controls, deployment flow.
- **`test.yml` does not run them.** It runs workers-vitest and the hydration/scaffolding validators
  only. The Playwright suite executes when a human runs it by hand on the dev box — which is
  precisely the rot `test.yml`'s own header comment was written to stop, recurring one layer up.
- **The only scheduled workflow in the repo is `runner-diag.yml`** (daily 08:15), a runner
  diagnostic, not a product check.
- **No canary at all** for tenhands, watchparty, conjure, pygmalion, promptsmith, games-host,
  dataplatform, jobplatform-api, prompt-api, oss-issues-api, prefs-api, game-api, or
  watchparty-stats-api — about fourteen products.

So the work is two-part, and the first part is nearly free: **schedule what already exists**, then
fill the gaps one product at a time. Scheduling first is worth doing on its own merits — sixteen
specs that nothing runs are already a liability, independent of this pipeline.

A repo has no business auto-landing until its product has a canary. That's the eligibility bar
above, made concrete.

### 4.1b Mapping the board's `repo` to a checkout we own

The board carries a *remote* ref (`WolffM/tenhands`). The pipeline maps it
mechanically to `~/.taskauto/repos/<owner>/<name>` — outside `~/repos`, so it never
appears in a repo listing or gets mistaken for a working checkout.

**A dedicated clone, not the human's.** The pipeline needs `reset --hard`,
`clean -fdx` and force-checkout to guarantee a clean tree, and in a shared checkout
those destroy uncommitted work with nobody present to stop them. It also makes G9
meaningful: `suite_green_on_merge_result` proves nothing in a tree that also contains
somebody's half-finished work, and a red result would blame the wrong change. And
recovery from a wedged pipeline clone is `rm -rf` plus a re-clone rather than an
evening.

**The disk objection doesn't survive measurement.** `.git` is tiny everywhere; the
bulk of a working directory is untracked build output, which a clone doesn't get.
Measured 2026-07-25: hadoku_site is 7.4 GB on disk but an 80 MB clone (the rest is
`.claude`, `actions-runner`, `node_modules`, `pocs`); hadoku-conjure is 181 GB on
disk but ~880 MB of history. The real recurring cost is a second `node_modules` /
`.venv` per repo — which is *correct*, since testing against possibly-stale deps
would be a false signal.

**We still borrow from a local copy when there is one.** `git clone
--reference-if-able <local> --dissociate <remote>` uses the local object store for
speed, then copies what it used and drops the link. No lasting coupling: if the
local repo later prunes, moves, or is deleted, our clone doesn't care.

The whole thing is built so **"no local copy" is the ordinary path**, not an error —
any newly automated repo starts there. We decline a local reference when it isn't
the same project (checked via `origin`), when it's shallow, or when it simply isn't
a git repo; and if a reference clone fails anyway, we retry without it rather than
lose the task.

### 4.2 The repo lock has to span the watch window, and that costs throughput

Auto-revert only works if a prod failure can be **attributed to a specific merge**. If task B lands
while task A is still inside its watch window and health goes red, we don't know which one did it —
and reverting the wrong commit is worse than not reverting.

So the per-repo lock from §1.1 can't be released at merge; it has to be held until the watch window
closes. The honest consequence: **one task per repo per cycle**, where a cycle is suite + merge +
deploy + watch — realistically 30–60 minutes. Seven tasks on one repo is most of a day.

That's acceptable here — the work arrives at human-typing rates, and tasks on *different* repos run
concurrently — but it is a real ceiling and it's the price of sound attribution. The tempting
optimisation (release the lock at merge, watch asynchronously) quietly breaks auto-revert, so it
isn't available.

### 4.3 The unmitigated risk is where the agent runs, not what it merges

Everything above is about the change. The bigger exposure is the **process**: `ClaudeCodeAgent` runs
headless `claude -p` on the production host, which is the same box as the vault key, the `gh` token,
the pm2 services, and every other repo's checkout. That is arbitrary code execution next to the
credentials, and no gate on this page constrains it — gates inspect the *diff*, and by then the
process has already run.

crimson-kitty never had this problem: its agent was Copilot, executing on GitHub's infrastructure.
Moving to a local agent is a genuine escalation that the swap to "same engine, different ends"
otherwise disguises, because the *pipeline* looks unchanged.

This is unresolved and it should be resolved before the agent runs unattended. The options, roughly
in order of cost:

- **Scope the credentials.** A dedicated GitHub token limited to the repos with auto-land boards,
  not the ambient user token. Cheap and worth doing regardless.
- **Deny the agent the vault.** It has no legitimate need for `.devvault.local.json`; the worktree
  should not be able to read it.
- **Containerise the agent** — its own filesystem namespace with just the worktree mounted.
- **Move it off the prod host** to a disposable runner, which also neatly solves the ephemeral
  per-task environment from §4.1.

The last two overlap heavily with work we want anyway, which is an argument for doing them properly
rather than bolting on a restriction.

---

## 5. Two pipelines, one gate registry — **shipped**

`gates/__init__.py` held `_registry` as a module-level list and `run_gates(state, …)` filtered it by
state name only. Two pipelines importing gate modules into one worker process would cross-fire: a
state named `fixed` exists in both, and crimson-kitty's `submission` gates would have run against a
task that has no upstream.

Every registration and lookup now names its pipeline:

```python
@gate(pipeline=TASK_AUTOMATION, after="fixed", kind="mechanical")
def protected_paths_untouched(task, evidence) -> GateResult: ...
```

**`pipeline` is a required keyword** on both `gate()` and `run_gates()`. The draft of this section
proposed defaulting it to crimson-kitty so the change stayed mechanical; that was wrong, and it was
the bug in miniature — a new gate that forgot the argument would have silently registered into the
other pipeline and run against work it was never written for. All 18 crimson-kitty gates were
updated explicitly instead, with a test pinning the exact `(state, name)` set so drift is caught.

`GateInput` *does* carry a default, deliberately: it crosses the Temporal serialization boundary, so
a required field would fail to deserialize for workflows already in flight across a deploy.

**One thing this turned up.** `_clear_registry_for_tests()` is destructive and *not* reversible by
re-importing — `@gate` runs at module import and Python caches modules, so any test that cleared it
left every later test looking at an empty registry. Latent until a test depended on real
registrations. Replaced by `isolated_registry()`, which saves and restores.

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

## 7. Status — **live in production**

Shipped 2026-07-25. `31dde08` merged the pipeline; `6a67656` added the scheduler.
Seven commits have reached `main` autonomously — see
[run-report-2026-07-25.md](run-report-2026-07-25.md).

| Step | State |
|---|---|
| 1. Namespace the gate registry | ✅ (§5) |
| 2. `TaskSource` + board client | ✅ `services/task_board.py`, `taskauto/selection.py` |
| 3. `ProgressSink` seam | ✅ `taskauto/progress.py` |
| 4. `TaskRef` + `ClaudeCodeAgent` | ✅ `taskauto/refs.py`, `taskauto/agent.py` |
| 5. Intake + planning | ✅ `taskauto/jobs.py`, gates G2/G6 |
| 6. Middle: reuse as-is | ✅ — the agent works in a pipeline-owned checkout |
| 7. `Landing` seam | ✅ `taskauto/landing.py` + `watch.py` (auto-revert) |
| 8. Scheduler | ✅ `taskauto/scheduler.py`, pm2 `tenhands-taskauto` |

**How to run it.** Boards are discovered, not configured: share a board with the
service key at `contributor`, activate it with
[schemas/autoland-v1.json](schemas/autoland-v1.json) — or, once hadoku-task points at
[our preset endpoint](preset-endpoint.md), pick *TenHands · Autoland* from their picker
and skip the paste — and it gets driven.

```
node ../hadoku_site/scripts/secrets/dev-vault.mjs -- \
    .venv/bin/python backend/run_taskauto.py          # dry run
TASKAUTO_LIVE=1 …                                     # actually pushes
```

Under pm2 it is `tenhands-taskauto`, defaulting to `TASKAUTO_LIVE=0`.

### What is deliberately not done yet

- **The fast path is disabled.** Every task goes through `plan-review`, even
  trivial ones. §1.1 describes intake releasing straight to `approved`; the job
  does not make that call unattended yet.
- **No parallelism.** One task in flight per repo. Note a task parked in
  `plan-review` does *not* block — only a live claim does. To parallelise: a
  worktree per task, and serialise **only the landing**, because two commits
  inside one prod-watch window cannot be attributed if health goes red (§4.2).
- **§4.3 is open** — the agent runs on the prod host with a scrubbed environment
  but no filesystem or network containment.
- **A stuck claim on a shared board needs the owner.** `POST /agent/cancel` is
  owner-only, so a crash mid-landing means waiting out the lease.
