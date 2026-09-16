# Autoland v3 — one board, repo lanes

**Date:** 2026-09-15. **From:** TenHands. **Status:** built on both sides;
awaiting hadoku-task's deploy (§11).
**Supersedes the lane model in** [`schemas/autoland.json`](schemas/autoland.json) (`schemaVersion` 2).
**Companion:** [`board-contract.md`](board-contract.md) is the v1/v2 design review and still the
reference for the claim protocol, which **does not change**.

> **On the version number.** This is `schemaVersion` **3**, not 2. The payload has been at 2 since
> `3afc6f7` ("the pipeline opens a pull request, it does not merge"); the filename
> `autoland.json` never followed and has been wrong ever since — the schema is loaded by glob
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

> **All shipped, 2026-09-15**, in hadoku-task's `autoland-v3` branch
> (`@wolffm/task@5.13.0`), and matched on this side. Two came back different
> from the ask and both are improvements — §5.3 on the status vocabulary, §5.4
> on the semantic change we had to mirror. One defect found in §5.1 afterwards
> is in §11.

In priority order. One blocking, the rest ranked by how much they improve the result.

### 5.1 Fire the wake when a notes write closes an open question — ✅ shipped, ⚠ see §11

`notifyLaneWrite` is only reached when the update carries a tag: `tasks.ts:221` builds `laneOpts`
from `'tag' in input`, so a **notes-only edit dispatches nothing**. Today that's invisible, because
every human handoff in v1 is a drag. In v3 the primary human action is answering in the notes, and
without this it waits on our backstop cron — a ~15 minute median — instead of the ~18 second
`repository_dispatch` path.

**Don't dispatch on every notes save** — that's every autosave keystroke. Dispatch when the write
**closes an open question**, which is a predicate you already own: `questionsAnswered` in
`src/domain/planNotes.ts`. Zero new vocabulary, and it is exactly the semantic event.

### 5.2 `ifNotesHash` on release — ✅ shipped

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

### 5.3 `status` on the task, and the chip that renders it — ✅ shipped

Per §3.1. Server-side it slots into the same UPDATE-builder in `releaseClaim` that already handles
`notes` / `metadata` / `complete`, on the same authorisation (the claim, not the lane). Also worth
accepting on `set-lane`, so a long job can report progress without releasing.

**Publish the `kind` vocabulary rather than hardcoding it.** We already serve our lane contracts at
`GET /tenhands/api/automation/presets` byte-for-byte from disk, precisely so a lane rename is not a
pasted copy going stale (`backend/services/automation_presets.py`). The status vocabulary belongs
in the same document, and the chip styling should key off data you fetched.

### 5.4 Checkbox rendering and the Approve control — ✅ shipped

Per §4. `planNotes.ts` already has `LIST_ITEM`; this adds `- [ ]` / `- [x]` recognition and makes
those rows tappable in `NotesPopout` / `PlanMarkdown`, plus one primary button when an unticked
approval item exists. The write is an ordinary notes update, so it inherits §5.1's wake for free.

### 5.5 Surface `claimed` on the card — ✅ shipped

Nothing in the UI renders it — we grepped `src/components`, `src/hooks` and `src/domain/types.ts`
and the only hit is the `CLAIM_HELD` error string. The board read has carried a per-task `claimed`
boolean since v1 and we rely on it heavily for selection, but a human looking at the board has no
way to see "the agent is on this one right now". With state leaving the lanes, that gap stops being
cosmetic.

### 5.6 Bless a per-lane `repo` — not needed, as expected

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
**All landed 2026-09-15.** 1662 tests, 0 skipped.

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
| `schemas/autoland.json` → `autoland.json` | `schemaVersion: 3`, lanes generated per repo, status vocabulary published alongside. See §10. |

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

## 9. Resolved: lock ordering for unrouted tasks

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

**Resolved: (2), and hadoku-task agreed independently** — *"'briefly pins a task' is exactly the kind
of exception that stops being brief once something in the routing path starts doing IO."* Built as
`make_route_job`, which runs the agent in an empty scratch directory against the lane list alone. A
router that could read repos would be a router that sometimes reads the wrong one for ten minutes.

## 10. Resolved: what a "preset" means when lanes are per-board

`automation_presets.py` publishes a **lane vocabulary** and strips `repo` specifically because it is
per-board (`_BOARD_SPECIFIC_KEYS`). In v3 the *entire lane set* is per-board — your repos, not
anyone's — so there is no fixed list left to publish.

The preset has to become a **shape**: `schemaId`, `schemaVersion`, a declared `laneKind: "repo"`,
and the `status.kind` vocabulary, with activation filling in the lanes from an operator's repo list.

Concretely blocking that: our own `validate_lane_set` requires a non-empty `lanes` array, and so
does theirs. A shape-preset with `lanes: []` fails both.

**Resolved — and neither of the two options above.** hadoku-task split it at a seam we had missed:
the *contract a provider publishes* and the *lane set a board is activated with* are the same
document today and genuinely diverge under v3. So `validateLaneSet` keeps requiring a non-empty
`lanes` (it guards **activation**, and a board with an empty tag vocabulary is meaningless), and
`lanes` becomes **optional on a PRESET**, where its absence plus `laneKind: "repo"` means "generate
these at activation time". The relaxation lives in the preset reader, not the validator.

They also killed our option (a) with a fact we did not have: `detectPresetUpdate` calls
`countStranded(preset.lanes, taskTags)` on every hydrated board read (`preset-update.ts:78`), so an
example lane set nobody activates verbatim would make every v3 board report every one of its tasks
as about to be stranded, and offer a migration that looks catastrophic and is fiction.

**Not blocking v3, by their recommendation and ours:** `laneKind` needs a new activation flow — the
panel has to collect a repo list and build the lane set before it can preview a digest — which is
real design, not a footnote. Until it exists, an operator activates one lane set by hand.
`schemas/autoland.json` carries `laneKind: "repo"` and one example lane today, with a `_lanes` note
saying exactly that.

---

## 11. A defect in §5.1, found after it shipped — ✅ fixed both sides

`parsePlanNotes` has no concept of our `— pass N` footer, so it lands **inside
`## Questions`** whenever that is the last section — which it is for every plan
that proposes no acceptance criteria. `parseQuestionsBody` then reads it as the
human's trailing reply. Measured against their branch:

```
ANSWERED n=0  prose question, Questions last        ← wrong
open     n=1  prose question, Acceptance after      ← fine
open     n=1  unticked approval, Questions last     ← fine
open     n=1  prose + unticked approval             ← fine
ANSWERED n=0  sentinel, Questions last              ← wrong

wake fires on the human's reply: false
```

That last line is the consequence, and it defeats the whole point of §5.1:
`notesWriteClosesQuestions` needs a `false → true` transition, the footer makes
it already true when we render, so when the human actually answers there is no
transition and **no dispatch fires**. The ~15-minute cron tail comes back
silently, for exactly the case §5.1 was built to fix.

The blast radius is limited by luck: an unticked box short-circuits before the
reply check, so the **approval flow — the primary path — is safe**. It is
prose-question plans and the `_No open questions._` sentinel that break.

**Fixed in hadoku-task `13b862a` (`@wolffm/task@5.13.1`), 2026-09-16.** They
stripped it before sectioning, and departed from the suggested patch in three
ways, one of which was a correction to us:

- **Stripped wherever it stands, not only when trailing.** Their
  `appendAnswerToNotes` inserts a reply before the next `##` heading, so on a
  Questions-last plan — the broken shape — the reply lands *after* our footer.
  A trailing anchor would stop matching at the exact moment someone answers.
- **Fence-aware**, so a plan documenting the footer format keeps it.
- The suggested regex used `/m` with a single `.replace()`, which strips the
  first footer-shaped line anywhere: neither trailing-only nor all. They kept
  the permissive-on-values advice and tightened the structure instead.

It also un-hid an under-report: a footed section with both a prose question and
an unticked box read as 1 open ask instead of 2, because the footer zeroed the
prose half while the box kept counting.

### The mirror image, which they asked us to check

Their `appendAnswerToNotes` shape puts a reply after our footer, so a
trailing-anchored strip on OUR side would fail the same way. Checked, and it
holds — `parse` and `_questions_section` both use `re.sub`, which is
position-independent — but checking it found a real defect next door:

**`parse` read the FIRST footer; `with_trailing_note` writes before the LAST.**
The two disagreed about which is authoritative, and `with_trailing_note` has
always documented the case ("a human may have pasted an older one above"). A
pasted `— pass 1` above ours made a third pass report as its first, uncapping
the planning loop — the same failure the permissive `\S+` exists to prevent,
reached from the other direction. `parse` takes the last footer now.

Pinned in `test_plan_notes_checklists.py`, using their fixture verbatim, and
each test verified to fail against the unfixed parser rather than assumed to.

### The footer format is a contract now

It was never written down as one, which is how it reached their parser
unannounced. It is:

```
— pass <N>
— pass <N> · confidence <X>
```

`—` is U+2014 EM DASH and `·` is U+00B7 MIDDLE DOT. Both sides match
permissively on the **values** (deliberately: a strict `[0-9.]+` once made the
whole footer fail to match on junk confidence, silently resetting
`pass_number` to 1 and uncapping the loop) and tightly on the **shape**, so a
human's `— pass the buck to legal` stays their text.

**If this gains a variant — another separator, a second field — tell
hadoku-task before shipping it.** Permissiveness on values does not extend to a
new separator character, and their parser would fall straight through.

---

## 12. Deploy order

**Migration 0007 must be applied to production D1 BEFORE hadoku-task's worker
ships.** `status` is in the `SELECT` list of every task read, so a worker
carrying it against a pre-0007 database answers **500 on `GET /boards` and the
app does not load at all** — measured, not inferred. Nothing in CI runs those
migrations and the worker does not self-migrate.

Our side is ordered the other way and is safe either way round: `_status_from`
degrades an unreadable or absent status to `None`, and a board with no repo
lanes is declined rather than misread, so this code running against a v2 board
does nothing rather than doing something wrong.
