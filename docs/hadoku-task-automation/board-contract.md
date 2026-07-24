# Reply to hadoku-task — automation board contract

**Re:** `docs/planning/tenhands-board-schema.md` @ `5989a0d`, §9.
**From:** TenHands. **Date:** 2026-07-24.

Short version: **the mechanism works, we'll take it as designed, and we have one blocking gap** —
there is no way for a human to cancel work that's already in flight (§3.1). For a pipeline that
merges to `main` without review, that's the difference between "I changed my mind" costing a tap
and costing a revert.

Our pipeline is [hadoku-task-automation](README.md). It runs the **same engine** as crimson-kitty —
the OSS-contribution pipeline your doc inferred lane names from — with two ends swapped: the board
replaces the aggregator as the source of work, and "merge to our own `main`, then watch production"
replaces "open an upstream PR, then watch the maintainer." crimson-kitty itself is not moving to
boards; it keeps its existing input.

Worth stating plainly, because it shapes what we need from you: **the board is a state projection,
not our database.** Temporal and our evidence store stay the source of truth for pipeline state.
The board is where that state becomes visible and steerable from a phone, and the claim is the lock
that keeps two of our runners off one task. That's why §3.1 below is the blocking item — a
projection you can watch but not interrupt is only half the value.

That difference explains why our lane set looks nothing like your `tenhands-v1.json` draft: no
`plan-review`, no `pr-review`, no `submit`/`submitted`. Those are human approval gates, and the
entire point of this pipeline is that no human is available to staff them.

---

## 1. Confirming the mechanism

| Thing | Verdict |
|---|---|
| Activation payload shape (`schemaId` / `schemaVersion` / `lanes`) | Works. Ours is [`schemas/autoland-v1.json`](schemas/autoland-v1.json) |
| `dryRun` → digest → commit | Good. We'd have shipped this wrong; the echo-back digest is the right call |
| claim → heartbeat → set-lane → release | Works. `job_id` = claim token maps cleanly onto our dispatcher interface |
| Atomic claim, server-clamped lease | This is the part we didn't want to build. Thank you |
| Error codes | Adopted as distinct branches, one note below |
| `notes` as markdown | Right primitive. Our scoping plan and every stall reason live here |
| Owner-only activation | Agreed, and correct. We'll hand you payloads |
| Poll, no change feed, for v1 | Fine — **don't build webhooks for us.** Board-per-repo means we poll one small board |

Two notes on the error table:

- **`LEASE_LOST` is our cancel signal**, if you take §3.1 — see below. Today we'd treat it as an
  abort-and-write-nothing, which is already the right behaviour; we'd just also want it to be
  *reachable on purpose*.
- **`LANE_UNKNOWN` on release after re-activation** is exactly the behaviour we want. Aborting into
  a `422` beats writing into a phantom lane. Confirmed as suitable (your §6, last bullet).

`editableBy` genuinely is enough permission model. We spent a while looking for the case that needs
more and didn't find one — the "human can drag out of an agent lane once no claim is live" rule
does the work an `onFailure` would have, without us having to teach you a routing policy.

---

## 2. Our configuration

One named config, `autoland` v1 — full payload in
[`schemas/autoland-v1.json`](schemas/autoland-v1.json). Seven lanes, three `agent`:

| `tag` | `editableBy` | What it means |
|---|---|---|
| `todo` | user | Filed from a phone. We claim from here |
| `scoping` | **agent** | Turning one sentence into a concrete target + plan → `notes` |
| `needs-info` | user | We couldn't disambiguate. Question in `notes`; answer and drag back |
| `working` | **agent** | Reproduce → fix → verify, in a worktree |
| `landing` | **agent** | Merging to `main`, then watching the deploy + health signal |
| `landed` | user | Merged and production verified. **A notification, not a queue** |
| `stalled` | user | A gate failed, or it landed and was auto-reverted. Evidence in `notes` |

`order` interleaves the two tracks so the left/right pairing in your §2 diagram reads as the actual
flow: `todo → scoping`, `needs-info ← scoping`, `working`, `landing → landed`, `stalled` catching
failures from anywhere.

**`needs-info` is the lane that makes this work on a phone.** A one-line task is often ambiguous —
*"fix the production CI workflow bug"* names neither a run nor a file. The scoping agent's cheapest
correct move is to ask, and `notes` plus a drag back to `todo` is a complete round trip on a
phone-sized screen. It's the single most-used human interaction in the design, and your existing
primitives cover it exactly.

**One board per repo**, per your §2. We carry `repo` as a top-level extra on the activation payload
(§3.3).

We don't need a second named config yet. If a repo turns out to want a human PR gate, that's an
`autoland-gated` variant with two extra `user` lanes and no change on your side — which is the
property you built this for.

---

## 3. What we need from you

### 3.1 A cancel path — **blocking**

**There is no way to stop in-flight work.** Once we hold a claim, the task sits in an `agent` lane
that the owner cannot drag out of while the claim is live (§3, your table). That rule is correct —
it's what stops a human yanking live work — but it leaves the human with no way to say *"stop, I
changed my mind"* to a running job.

For a pipeline that merges to `main` unreviewed, that's a real gap. The realistic scenario isn't
exotic: you file a task on a bus, realise two minutes later it's wrong or already fixed, and the
only thing you can do is watch it land and get reverted.

**What we'd like, and we think you already have the machinery:** let the **owner force-drop a live
claim.** Then our next `heartbeat` returns `409 LEASE_LOST`, and we abort and write nothing —
which is behaviour you've already specified and we've already got to implement. The task falls back
to being an ordinary claimed-by-nobody task in an `agent` lane, which your §3 says a human can then
drag out.

No new error code, no new state, no new concept for us to learn. In the UI it's "release this task"
on an owner's own board. If you'd rather express it as a `cancelRequested` flag surfaced in the
heartbeat response, that also works — we'd honour it identically. The force-drop is simply cheaper
for both of us.

### 3.2 Can a claim holder write `Task.metadata`?

We need to persist a **Temporal workflow ID** on the task, so that after a tenhands restart we can
re-correlate a claimed task to its in-flight workflow rather than starting a duplicate.

`release` takes `{token, lane, notes?}` — no metadata. And `update_task` is refused into `agent`
lanes with `403 LANE_NOT_EDITABLE`. So it's ambiguous whether we can write `metadata` on a task
that is *sitting in* an `agent` lane while we *hold its claim*.

Our read of the intent is that the claim is exactly the thing that authorises writes there, so it
should be allowed — but the spec describes the refusal in terms of the lane, not the claim. **Please
make it explicit either way.** If the answer is no, `set-lane` or `release` growing an optional
`metadata` merge would cover us.

(We're not asking to write metadata without a claim. That should stay refused.)

### 3.3 Does `repo` round-trip on the activation payload?

Your §2 says "the board records which repo it drives," but the JSON Schema has no `repo` field —
just `additionalProperties: true`. We're hanging it off the top level of the payload:

```jsonc
{ "schemaId": "autoland", "schemaVersion": 1, "repo": "WolffM/tenhands", "lanes": [ … ] }
```

Confirm that comes back verbatim on `GET /task/api/boards/{handle}` and we're done — that's our
board → checkout mapping. If you'd rather it were a first-class board field, we'd take that too;
we just need it readable without parsing a display name.

### 3.4 `landed` accumulates, and we can't clear it

Your §7 is clear that `complete_task` / `delete_task` are human actions and the automation flow only
changes lanes. We understand the reasoning and we're not asking you to relax it lightly.

But: `landed` is a **notification lane, not an approval queue** — nothing is asked of the human, and
under this design most tasks end there. Over a few months it becomes an unbounded list that has to
be archived by hand, on a phone, which is precisely the chore the pipeline exists to eliminate.

Options, in our order of preference — **your call, none of these are blocking**:

1. Let a claim holder pass `complete: true` on `release`. Narrow, still requires a live claim,
   still auditable via the claim log.
2. A board setting: auto-archive tasks that have sat in a nominated lane for N days. Purely a
   hadoku-task feature; we'd never call it.
3. Nothing — we accept the manual sweep, and drop `landed` in favour of releasing to a lane you
   periodically clear yourself.

### 3.5 Two sizing questions

- **What's the `notes` ceiling** that trips `NOTES_TOO_LARGE`? Our scoping plan is a few KB of
  markdown — understanding, evidence links, blast radius. We'll link out to the evidence store for
  diffs and logs rather than inlining them; we just want to know the budget before we design the
  truncation.
- **What's the maximum lease** after clamping? Our agent runs are 30–180 minutes. We'll heartbeat
  rather than requesting one enormous lease, but we'd like to know the ceiling so we can set the
  heartbeat interval with real headroom rather than guessing.

---

## 4. What we don't need

Explicitly, so you don't build it:

- **No change feed / webhooks for v1.** Polling one board per repo is cheap and we're fine with it.
- **No `/eligible` endpoint.** Agreed with your reasoning — eligibility is pipeline knowledge.
- **No board provisioning by us** (your old §6.3). A human creating and activating a board per repo
  is fine; that's a rare, deliberate act, and owner-only activation is worth more than the
  convenience.
- **Nothing that a lane extra or `Task.metadata` can't carry** — beyond §3.2's write question, the
  four-field lane is sufficient. We checked for the case that needs more and didn't find one.

---

## 5. What we're building against this

Design is in [README.md](README.md); the gate set that has to be right before anything auto-merges
is in [gates.md](gates.md). Nothing is built on our side either — we're sequencing our build behind
your automation surface, so §3.1 is worth resolving before you start the claim/lease tranche.
