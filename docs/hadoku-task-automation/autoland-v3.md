# Autoland v3 — one board, repo lanes

**Date:** 2026-09-15. **From:** TenHands. **Status:** design, not built.
**Supersedes the lane model in** [`schemas/autoland-v1.json`](schemas/autoland-v1.json) (`schemaVersion` 2).
**Companion:** [`board-contract.md`](board-contract.md) is the v1/v2 design review and still the
reference for the claim protocol, which **does not change**.

> **On the version number.** This is `schemaVersion` **3**, not 2. The payload has been at 2 since
> `3afc6f7` ("the pipeline opens a pull request, it does not merge"); the filename
> `autoland-v1.json` never followed and has been wrong ever since — the schema is loaded by glob
> and keyed by `schemaId`, so nothing depended on the name and nothing caught it.
>
> Rename it to `autoland.json` when v3 lands: the version belongs in the payload, encoding it in
> the filename has already drifted once, and there are 14 references to update — which is why it
> is part of the implementation rather than of this document.

---

## 1. What changes, and why

v1/v2 put **one board per repo** and used the eight lanes as **pipeline state**. Both halves are
now wrong for how this is actually used:

- **One board per repo doesn't scale to a human.** Finding where the work is means flipping
  through a board per repo. The boards are identical in structure and differ only in which repo
  they point at, which is exactly the thing a column is for.
- **Six of the eight lanes are telemetry nobody reads.** `planning`, `working` and `landing` are
  agent lanes a human never acts on. `landed` and `stalled` are notifications. Only
  `plan-review` / `replan` / `approved` ask anything, and only one of those is a decision.

So v3 turns the axis ninety degrees:

| Axis | v2 | v3 |
|---|---|---|
| Lane / tag | 8 pipeline states | **one per repo** — `hadoku-conjure`, `hadoku-aggregator`, … all `editableBy: user` |
| Inbox (untagged) | capture | capture, **unrouted** — the pipeline picks the repo and moves the card |
| Pipeline state | the lane | **`task.status`** chip, plus the `## Outcome` line in `notes` |
| "Needs you" | the `plan-review` lane | the **`❓N` badge** `TaskItem.tsx` already renders from `## Questions` |
| Approval | drag to `approved` | **an Approve control inside the task item** |
| Done | the `landed` lane, swept by hand | `complete: true` on release → archived, fades out in 24h |

**The claim protocol is untouched.** claim → heartbeat → set-lane → release, the error codes, the
lease clamp, `ifCurrentLane`, `complete: true` — all of it works as specified. What changes is what
a lane *means*, and that is entirely our side of the contract.

---

## 2. The one server rule that forced this shape

**On an automation board a task carries exactly one tag, and it must be a lane.** Both write paths
enforce it independently:

- `assertHumanLaneWrite` (`worker/src/routes/board-automation.ts:94`) throws `LANE_INVALID` on any
  whitespace in the tag. A human cannot put two tags on a task.
- `agentLaneTag` (`worker/src/routes/board-claims.ts:52`) normalises to a single token and requires
  it to be a known lane.

So there is **one axis, not two**. "Repo as a tag, state as a tag" is not available. Repo wins the
axis, and state has to leave the tag system altogether rather than move to a second tag.

Two consequences worth stating plainly, because they are the costs of this design:

1. **`notes` loses mutual exclusion.** [`board-contract.md`](board-contract.md) §3 called this out
   as the reason v1 worked: the plan document is safe because the agent only writes it while the
   task sits in an `agent` lane a human cannot write. With every lane `editableBy: user`, that
   guarantee is gone. See §5.4 — this is the one ask we would call blocking.
2. **"What needs me" stops being a pile and becomes a badge.** Deliberate, and accepted: a column
   whose contents you have to scan is not obviously better than a count you can see from the board
   view. But it is a real trade and the badge has to be good.

### Incidental: a docstring of ours is wrong

`BoardTask.lane_tags` in `backend/services/task_board.py` says "a user is free to add their own
(`urgent`, `someday`) alongside a lane tag". That is true on a **standard** board and false on an
**automation** board. Fix it with this work.

---

## 3. State, concretely

### 3.1 `task.status` — the chip

A new first-class field on the task, written by the claim holder exactly as `notes` is:

```json
{
  "kind": "working" | "waiting" | "blocked" | "done",
  "label": "implementing · 3 files",
  "href": "https://github.com/WolffM/hadoku-conjure/pull/42"
}
```

- `kind` is a **closed set** the UI styles as a chip. Four states, because four is what a human
  distinguishes at a glance: it's moving / it wants me / it's stuck / it's finished.
- `label` is free text the agent writes. Never parsed by anyone.
- `href` is optional and makes the chip a link — the PR, most of the time.

**This is a generic board primitive, not an autoland concept.** "An agent reports status on a task"
is the same shape any pipeline would want. That is why it should not be
`metadata.autoland.status`: that would work today with no schema change at all, and it would couple
a generic card renderer to one pipeline's metadata key.

### 3.2 `## Outcome` — the human-legible line

Already exists (`plan_notes.py`, `H_OUTCOME`) and already renders first in the popout. The chip is
the glanceable form; `## Outcome` is the sentence. No new mechanism.

### 3.3 `metadata.taskauto` — machine state

Unchanged in kind, extended in content: Temporal workflow id, PR number, pass count, timings, and
now the **repo memo** and the **notes hash** (§5.4). Invisible on the board card — `metadata` only
renders in the calendar agenda view — which is correct. It is not for a human.

---

## 4. Approval, contained in the task item

The pipeline still asks for sign-off before it implements. What changes is that the signal is a
control **inside the item**, not a lane to drag to.

The agent's plan ends `## Questions` with a task-list item:

```markdown
## Questions

- Should the TTL apply to negative lookups too?
- [ ] Approve this plan
```

The popout renders task-list items as tappable checkboxes, and shows a primary **Approve** button
when an unticked one is present. Tapping writes `- [x]` — **the same bytes a human typing into the
notes would produce.**

That last point is the whole design. `questionsAnswered` stays the single predicate on both sides.
There is no approvals table, no `metadata.approved`, no second channel carrying the same fact. The
button is a typing shortcut over a format both repos already parse, plus a wake (§5.1).

"Send it back" needs no control at all: the human answers a question and leaves the approval
unticked, which is already `questionsAnswered && has_open_questions`.

---

## 5. What we need from hadoku-task

In priority order. One blocking, the rest ranked by how much they improve the result.

### 5.1 Fire the wake when a notes write closes an open question — **highest leverage**

`notifyLaneWrite` is only reached when the update carries a tag: `tasks.ts:221` builds `laneOpts`
from `'tag' in input`, so a **notes-only edit dispatches nothing**. Today that's invisible, because
every human handoff in v1 is a drag. In v3 the primary human action is answering in the notes, and
without this it waits on our backstop cron — a ~15 minute median — instead of the ~18 second
`repository_dispatch` path.

**Don't dispatch on every notes save** — that's every autosave keystroke. Dispatch when the write
**closes an open question**, which is a predicate you already own: `questionsAnswered` in
`src/domain/planNotes.ts`. Zero new vocabulary, and it is exactly the semantic event.

### 5.2 `ifNotesHash` on release — **blocking**

`ifCurrentLane` exists because a human can retag a task out from under a live claim, and a release
that overwrote their change would be a silent data loss. In v3 the same hazard moves to `notes`: no
agent lanes means a human can edit the plan at any moment, including mid-claim.

We want the identical guard, on the identical terms: an optional `ifNotesHash` on
`POST /agent/release`; a mismatch answers `409 NOTES_CHANGED` and the release **writes nothing**.
We already handle the `ifCurrentLane` branch of that (`RELEASE_ABORTED` in
`backend/services/task_board.py`) and would handle this one the same way.

Without it, we can only hash-compare-then-write, which is a race rather than a guard. Calling this
blocking because losing the human's reply is a failure mode with no recovery path — the text is
simply gone.

### 5.3 `status` on the task, and the chip that renders it

Per §3.1. Server-side it slots into the same UPDATE-builder in `releaseClaim` that already handles
`notes` / `metadata` / `complete`, on the same authorisation (the claim, not the lane). Also worth
accepting on `set-lane`, so a long job can report progress without releasing.

**Publish the `kind` vocabulary rather than hardcoding it.** We already serve our lane contracts at
`GET /tenhands/api/automation/presets` byte-for-byte from disk, precisely so a lane rename is not a
pasted copy going stale (`backend/services/automation_presets.py`). The status vocabulary belongs
in the same document, and the chip styling should key off data you fetched.

### 5.4 Checkbox rendering and the Approve control

Per §4. `planNotes.ts` already has `LIST_ITEM`; this adds `- [ ]` / `- [x]` recognition and makes
those rows tappable in `NotesPopout` / `PlanMarkdown`, plus one primary button when an unticked
approval item exists. The write is an ordinary notes update, so it inherits §5.1's wake for free.

### 5.5 Surface `claimed` on the card

Nothing in the UI renders it — we grepped `src/components`, `src/hooks` and `src/domain/types.ts`
and the only hit is the `CLAIM_HELD` error string. The board read has carried a per-task `claimed`
boolean since v1 and we rely on it heavily for selection, but a human looking at the board has no
way to see "the agent is on this one right now". With state leaving the lanes, that gap stops being
cosmetic.

### 5.6 Bless a per-lane `repo`

Not required. `validateLaneSet` preserves unknown keys verbatim ("we validate the four we interpret
and keep the rest"), so we can hang `"repo": "WolffM/hadoku-conjure"` on each lane object today and
it round-trips through `activate-automation` and back out of `GET /boards/:ref`. Making it
first-class would just mean it is checked rather than merely carried.

Note the knock-on: `POST /boards/{ref}/repo` calls `grantRepoServiceKeyShare`, so connecting a repo
auto-grants that repo's service key. Per-lane repos would not get that. It does not affect us — we
drive every board as the one `tenhands-service-key` identity — but if per-repo agents are ever
expected to read the board, the grant needs a home.

---

## 6. What we are not asking for

- **No change to the claim protocol.** It was right in v1 and it is right now.
- **No relaxation of the one-tag rule.** A second tag axis would give us repo *and* state as tags,
  and `getTasksByTag` already splits multi-tag correctly, so the UI would cope. We considered it and
  we do not want it: two axes on one card is more model than this needs, and the one-tag invariant
  is load-bearing for `LANE_INVALID` being a real check.
- **No per-repo boards, and no board creation by us.** Unchanged from
  [`board-contract.md`](board-contract.md) §5.
- **No new state machine on your side.** `status.kind` is a label you render. Which kind means what,
  and when it changes, stays pipeline knowledge — the same reasoning that keeps `isUserLaneWrite`
  structural rather than naming `approved`.

---

## 7. What changes on our side

Recorded here so the split of work is explicit; none of it needs review from hadoku-task.

| Module | Change |
|---|---|
| `taskauto/selection.py` | The lane-priority table goes entirely. Selection becomes per-repo-lane over (claim state, question state, approval tick, settle). **One task in flight per repo lane**, not per board. |
| `run_taskauto.py` | Runners keyed by repo lane. The "one board per repo" duplicate guard becomes "one lane per repo". `POLICIES` / `HEALTH` keep their `owner/repo` keys unchanged. |
| `taskauto/scheduler.py` | **Hoist the board read.** N repo-runners each calling `get_board` on one board is N identical reads per tick; read once and pass the snapshot down. And stop discarding `tag` from the change feed — see §8. |
| `taskauto/runner.py` | Routing an unrouted Inbox task; see §9 for the ordering problem it creates. |
| `taskauto/reconcile.py` | Writes `status` and questions instead of moving lanes. A merged PR releases with `complete: true`. |
| `taskauto/progress.py` | `ProgressSink.lane()` becomes `ProgressSink.status()`. A rename — **not** a second channel alongside it. |
| `taskauto/plan_notes.py` | Render the approval checkbox; parse ticked / unticked. |
| `services/task_board.py` | `status` on `BoardTask`; `ifNotesHash` on release; fix the `lane_tags` docstring (§2). |
| `schemas/autoland-v1.json` → `autoland.json` | `schemaVersion: 3`, lanes generated per repo, status vocabulary published alongside. See §10. |

---

## 8. One board is *cheaper*, not more expensive

Worth recording, because "one board for everything" sounds like it should cost more:

- **Fewer reads.** Today each board runner does its own `GET /boards/:ref`. One board with N repo
  lanes is one read per tick serving all of them, once §7's hoist lands.
- **Better change-feed resolution, for free.** `getChanges` already returns `tag` per row
  (`board-claims.ts:414`). With lanes as repos, **`tag` is the repo** — so the feed tells us exactly
  which repos moved, which is strictly better than today's per-board granularity. Our
  `Scheduler._changed_boards` currently throws it away (`{c.get("boardId") for c in changes}`); that
  is a one-line fix and it means a quiet repo is never swept.

---

## 9. Open: lock ordering for unrouted tasks

`Runner.turn()` takes the checkout lock **before** claiming, deliberately — losing that race costs
nothing, because we hold no claim and so leave no task pinned in a lane waiting out a lease. Claim
first and the same contention strands one.

An unrouted Inbox task breaks that ordering: its repo is not known until an agent has read it, so
there is no checkout to lock first. Two ways out:

1. **Claim-then-lock for routing only**, accepting that a routing job can briefly pin a task.
   Routing is seconds, and the lease is the backstop.
2. **Split routing into a job that touches no checkout** — read the task, pick the lane, release.
   Planning then starts on the next turn with the ordering intact.

(2) is more code and one extra turn of latency; (1) weakens an invariant that was chosen carefully.
Leaning (2), undecided.

## 10. Open: what a "preset" means when lanes are per-board

`automation_presets.py` publishes a **lane vocabulary** and strips `repo` specifically because it is
per-board (`_BOARD_SPECIFIC_KEYS`). In v3 the *entire lane set* is per-board — your repos, not
anyone's — so there is no fixed list left to publish.

The preset has to become a **shape**: `schemaId`, `schemaVersion`, a declared `laneKind: "repo"`,
and the `status.kind` vocabulary, with activation filling in the lanes from an operator's repo list.

Concretely blocking that: our own `validate_lane_set` requires a non-empty `lanes` array, and so
does theirs. A shape-preset with `lanes: []` fails both. So either the preset carries an example
lane set that nobody activates verbatim, or `laneKind` becomes a recognised alternative to `lanes`
on both sides. Undecided, and worth settling before any code is written — it is the one part of
this that changes what an existing endpoint *means*.
