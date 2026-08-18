# Runbook: debugging a taskauto task

You are looking at one task — on a board, in a PR, or archived — and something
about it is confusing: the notes read oddly, you're not sure it was gated, or
you can't tell whether it deployed. This is where to start, so you never have to
reconstruct it from the source again.

Three things make a taskauto task hard to read after the fact, and each has a
section below:

1. **A task's `notes` are rewritten at every phase**, so what you see depends on
   *when* you look — the planning document, the in-flight status, or the
   archived record are three different documents in the same field.
2. **The telemetry lives in two places** — the board (hadoku-task) holds the
   task and its claim log; GitHub holds the diff, the checks, and the deploy —
   and no single view joins them. `/api/taskauto/task/...` is the closest thing.
3. **How you *edit* a task depends on whether it's still active**, and the
   obvious path (`claim`/`release`) silently fails on a completed task.

---

## 1. Why the notes look like that — the `notes` lifecycle

`notes` is one field that holds a *different document* at each phase. The
headings tell you which phase you're looking at. See
[plan_notes.py](../../backend/temporal/taskauto/plan_notes.py) for the renderer
and [reconcile.py](../../backend/temporal/taskauto/reconcile.py) /
[jobs.py](../../backend/temporal/taskauto/jobs.py) for who writes each one.

| Phase | Written by | `## Outcome` | `## What I think you want` | `## Plan` |
|---|---|---|---|---|
| **Planning** (`planning`→`plan-review`) | `jobs.plan_job` | — | the agent's restatement of your task | the numbered plan it proposes |
| **In flight** (PR open, `landed` lane, not merged) | `jobs.implement_job` | status: "pushed as a PR, auto-merge armed…" + PR URL | preserved from planning | the **execution log** (committed / pushed / opened-PR), *not* the plan |
| **Archived** (PR merged, `Completed`) | `reconcile._merged_notes` | `Merged via <url>.` + file count | dropped | dropped (the execution log is bookkeeping the claim log already keeps) |

**The key gotcha:** by landing time the `## Plan` section holds the pipeline's
*execution log*, because `implement_job` overwrites it with the checklist it
prints while working. So a merged task showing "committed on… / pushed… /
opened pull request…" under **Plan** is expected — that is the log, not a plan.

**Status belongs under `## Outcome`, never under `## What I think you want`.**
That heading means "what the task is *for*"; a status line under it reads as
nonsense. If you see `## What I think you want\n\nMerged. <url>` on any task,
that is the pre-2026-08-17 bug — the fix routes every terminal/in-flight status
through `## Outcome` and preserves the understanding. `blast_radius` carries the
changed files as the summary of what shipped.

To regenerate what the *current* code would render for a merged task:

```python
from temporal.taskauto import reconcile
from temporal.taskauto.reconcile import PRRef
print(reconcile._merged_notes(task, PRRef("WolffM/<repo>", <pr_number>)))
```

### The notes are not what the planner read

A task seeded by the board's **"automate open items"** button — titled
`Address #19` or `Address PR #21` — carries only a **280-character preview** of
the GitHub item in its notes (`_BODY_SNIPPET_MAX`, `routes/taskauto_routes.py`).
Do not read those notes as the planner's input.

Since 2026-08-18 the planner is handed the item **re-fetched in full** by the
parent process ([`github_item.py`](../../backend/temporal/taskauto/github_item.py)),
because the agent itself holds no `gh` and no token by design (`agent.py`,
containments 1–2) and never can. To see what it actually read:

```python
# from backend/
from temporal.taskauto import github_item
print(github_item.hydrate("WolffM/<repo>", "<task title>"))
```

Empty output means the title is not a seeded one and no item was involved. A
block reading **`COULD NOT BE FETCHED`** means `gh` failed and the planner was
told so explicitly — that is the designed behaviour, not a bug: an omitted
block would have read to the agent as "the preview is the whole story", which
is the failure this replaced. If a plan invents review comments or failing
checks that don't exist, check this output first; the item block states absent
status as absent (`checks: NONE REPORTED`) precisely to prevent it.

---

## 2. Fetching a task's real state

### 2a. The joined view — `/api/taskauto/task/<board>/<task_id>`

The tenhands backend already assembles the plan, every claim, and the PR into
one answer. This is the debugging entry point, not the code.

- `GET /tenhands/api/taskauto/status` — every board, its lanes, its open PRs,
  and roll-up metrics (agent-seconds, plan passes).
- `GET /tenhands/api/taskauto/task/<board>/<task_id>` — one task end to end: its
  plan, its claim history (timeline), and every PR ever opened for it.

Both are `friend`-tier GETs behind the auth gate, served from the running
backend. In dev, `python3 app.py` then hit `http://localhost:5024/tenhands/...`
with your key as `?key=` or the `X-User-Key` header.

### 2b. Straight to the board — hadoku-task API

When the backend isn't running, or you need the raw task, go to the board API
directly. **Base:** `https://hadoku.me/task/api` · **spec:**
[`/openapi.json`](https://hadoku.me/task/api/openapi.json).

**Auth is a service-tier key, and you already have one.** The 36-char `key` in
`.devvault.local.json` is the `tenhands-service-key` identity, which holds
shares on every automation board. Export it and
[`TaskBoardClient`](../../backend/services/task_board.py) just works — no vault
unlock needed for reads.

```bash
export HADOKU_SERVICE_KEY=$(python3 -c "import json;print(json.load(open('.devvault.local.json'))['key'])")
```

```python
# from backend/, with HADOKU_SERVICE_KEY exported
from services.task_board import TaskBoardClient
c = TaskBoardClient()
for b in c.automation_boards():          # every board you can see
    print(b.handle, b.repo)
full = c.get_board("<board_handle>")     # one board, all lanes
task = next(t for t in full.tasks if t.id[:12].lower() == "<branch-id>")
print(task.lane(full.lanes), task.state, task.claimed)
print(task.notes)
c.history("<board_handle>", task.id)     # the claim log / timeline
```

**Branch ↔ task id:** the pipeline's branch is `taskauto/<first-12-chars-of-ULID,
lowercased>` (`jobs._branch_for`). So branch `taskauto/msxkqdnvnn7a` ⇒ match the
task whose id *starts with* `MSXKQDNVNN7A`. An exact-id match against the branch
suffix will always miss — the branch only carries 12 of the 26 characters.

---

## 3. Was it gated? Was it deployed?

### Gating

A "**NO TEST COMMAND — nothing verified this change**" line in the notes does
**not** mean the change was ungated. It means the *agent* had no local test
command configured, so it ran no suite while implementing — which is by design
in `pr` mode: the PR's own **required status checks** are the gate
([landing.py](../../backend/temporal/taskauto/landing.py), §"suite skipped").

Check the repo's actual gate:

```bash
gh api repos/WolffM/<repo>/branches/main/protection \
   --jq '.required_status_checks.contexts'          # e.g. ["frontend-build","python-tests"]
gh api repos/WolffM/<repo>/commits/<pr-head-sha>/check-runs \
   --jq '.check_runs[] | "\(.name): \(.conclusion)"'
```

If a repo has **no** required checks, the pipeline refuses to arm auto-merge and
the notes say "**auto-merge HELD… a human merges this one**" — so an armed
auto-merge is itself proof a real CI gate existed.

### Deploy

A merge to `main` fires the repo's redeploy workflow. Confirm it ran on the
*merge commit*:

```bash
gh api "repos/WolffM/<repo>/actions/runs?per_page=15" \
   --jq '.workflow_runs[] | select(.event=="push") | "\(.name) \(.conclusion) \(.head_sha[0:9]) \(.created_at)"'
# look for the redeploy on the PR's merge_commit_sha, seconds after mergedAt
```

Runtime confirmation (the change is actually visible) still needs driving the
app — CI green proves it compiles, not that the behaviour changed.

---

## 4. Editing a task's notes

**Active task** (a lane where a claim can be held) — the agent path, atomically:

```python
token = c.claim(board, task_id)
c.release(board, task_id, token, lane="<same-lane>", notes=new_notes,
          if_current_lane="<same-lane>", complete=<bool>)
```

**Completed / archived task** — `claim` raises `TaskNotFound` (it only sees
`active_tasks`). Use the **human PATCH path** instead, which edits regardless of
lane or completed state and preserves both:

```python
c._call("PATCH", f"/{task_id}", json_body={"boardId": board, "notes": new_notes})
```

`PATCH /task/api/{id}` accepts `title`, `notes`, `tag`, `date`, `metadata`. It is
the endpoint the board UI uses when you type in a task's notes field.

---

## See also

- [hadoku-task-automation/README.md](../hadoku-task-automation/README.md) — the pipeline itself; §1.2 for the planning-phase notes.
- [board-contract.md](../hadoku-task-automation/board-contract.md) — the board API contract.
- `CLAUDE.md` → *Development* — the production-checkout hazard (uncommitted work gets eaten by a deploy; work in a worktree).
