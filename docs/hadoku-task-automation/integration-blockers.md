# TenHands → hadoku-task: what we need to integrate

**Date:** 2026-07-24. **From:** TenHands. **Read cold** — this doc is self-contained.
**Companion:** [`board-contract.md`](board-contract.md) is the full design review;
[`schemas/autoland-v1.json`](schemas/autoland-v1.json) is the activation payload we want supported.

We reviewed `docs/planning/tenhands-board-schema.md` @ `5989a0d` **and your code on `origin/main`**.
The mechanism you designed works for us — activation payload, claim → heartbeat → set-lane →
release, the error codes, `notes`. This doc is only the delta: things that must exist before we can
build against you, in priority order.

**Already understood to be in flight, so not listed as blockers:** `boards.repo` being mapped
through to the `Board` type, and `GET /boards/{handle}`. We're assuming both land — see §2 and §3
for what we need *in* them.

---

## 1. A cancel path — the one thing not in your design

**Status: blocking. Not currently designed, so this is a genuine addition rather than a nudge.**

There is no way to stop in-flight work. Once we hold a claim, the task sits in an `agent` lane a
human can't drag out of. That rule is correct — it's what stops a human yanking live work — but it
leaves no way to say *"stop, I changed my mind"* to a running job. We checked: the only documented
ways a claim ends are a voluntary `release` or lease expiry.

Our pipeline merges to `main` without human PR review. So the realistic scenario is: file a task on
a bus, realise two minutes later it's wrong or already done, and be able to do nothing but watch it
land and get reverted.

**What we'd like, using machinery you already have:** let the **board owner force-drop a live
claim**. Our next `heartbeat` then returns `409 LEASE_LOST`, we abort and write nothing — behaviour
you've already specified and we have to implement anyway. The task becomes an ordinary unclaimed
task in an `agent` lane, which your §3 says a human can then drag out.

No new error code, no new state, no new concept. In the UI it's a "release" action on your own
board. A `cancelRequested` flag surfaced in the heartbeat response would work identically; force-drop
is simply cheaper for both of us.

---

## 2. Programmatic activation, alongside the Edit-Boards UI

**Status: blocking for rollout, not for the first board.**

Your §6 makes activation owner-only, and we agreed with the reasoning: a compromised service key
must not be able to restructure someone's work. That still holds. But "owner-only" and "human-only"
aren't the same thing, and we need both surfaces:

- **In the Edit-Boards menu** — converting a board to an automation board, picking the configuration.
  This is the normal path and how the first boards get created.
- **As an API endpoint** — so a board can be converted programmatically, called **with an owner
  credential**, not our service key. We're not asking to weaken §6; we're asking that the owner be
  able to automate their own action.

The reason is rollout. There will be one board per repo across a dozen-plus repos, and a config
change means re-activating every one of them with a bumped `schemaVersion`. Doing that by hand
through a menu, repeatedly, is exactly the chore that makes people skip the upgrade.

Your `dryRun` → digest → commit flow already makes this safe to automate: the preview digest has to
be echoed back, so an automated activation still can't silently reshape a board nobody looked at.

**The configuration itself is ours to define and yours to store verbatim.** That's the split your
doc proposes and we think it's right. [`schemas/autoland-v1.json`](schemas/autoland-v1.json) is the
static contract — eight lanes, three `editableBy: agent` — and it should need no code change on your
side beyond structural validation.

---

## 3. `GET /boards/{handle}` — two things we need in the response

**Status: blocking. Understood to be in flight.**

Your doc names this our read primitive and says never to call `GET /boards`; today `GET /boards` is
the only board read and it returns no hydrated tasks. Two fields decide whether the runner's read
loop works:

- **`repo`** — our board → checkout mapping. The D1 column exists (migration `0002`, line 28) and is
  already `SELECT`ed in `d1-storage.ts:166`; it just isn't mapped in `rowToBoard()` or declared in
  `BoardSchema`. If you'd rather we carry it as an unknown-key extra on the activation payload
  instead, that's fine — we only need it readable without parsing a display name.
- **Per-task claim state — even just a boolean.** We serialise ourselves to one task in flight per
  repo, because several tasks on a board often touch the same files and concurrent diffs collide.
  Without a claim flag we'd infer "someone is working" from lane membership, which is wrong in
  exactly the case that matters: a task sitting in an `agent` lane whose claim has already expired.

We don't need the holder identity or the expiry timestamp. A boolean is enough.

---

## 4. A service tier that isn't rate-limited like a browser

**Status: blocking, and cheap.**

Your throttle is per-session: 300/min admin, 120/min friend, 60/min public, with an auto-blacklist
after 3 violations (`worker/src/throttle.ts:41`). Those are sensible numbers for a browser. They're
the wrong shape for a service.

We won't be doing more than **~2 actions/sec** — but 2/sec *is* 120/min, which lands exactly on the
friend-tier ceiling with zero headroom, and the penalty for a burst isn't a 429, it's a blacklist
after three of them. A poll loop plus a claim plus a heartbeat can spike past a per-minute average
without being remotely abusive.

**What we're asking for:** a distinct limit for **service-tier keys** — the credential class we'll
authenticate with — set high enough that normal operation can't approach it. Something like 600/min
would give us 5× headroom over our own worst case.

Related: the 429 body is `{error, message, retryAfter}` with **no machine-readable `code`**;
`RATE_LIMITED` exists only as a human-facing string in `constants.ts:127`. We'll branch on HTTP 429
plus `retryAfter` rather than a code string — flag it if you plan to add one, so we don't hardcode
the wrong shape.

---

## 5. An OpenAPI document generated from your zod schemas

**Status: not blocking. Highest-leverage item on this page.**

We want this integration to be **api-to-api**, with as little hand-maintained translation as
possible. You already have zod schemas as the source of truth; the missing step is emitting them as
a spec (`zod-to-openapi` or equivalent), versioned alongside `@wolffm/task`.

This matters more here than it usually would because **our side is Python**. We can't import your
TypeScript types the way another TS consumer would, so without a spec we are hand-transcribing your
schemas into Python models and discovering drift at runtime — the worst place to discover it.

With a spec, we generate our client, and every future change to the task or board shape becomes a
regenerate-and-typecheck on our side instead of a doc read and a guess.

---

## 6. Smaller confirmations

Not blocking, but they'd stop us guessing:

- **Can a claim holder write `Task.metadata`?** `release` takes `{token, lane, notes?}` — no
  metadata — and `update_task` into an `agent` lane is refused. So it's unclear whether we can write
  `metadata` on a task *sitting in* an `agent` lane while *holding its claim*. Our read is that the
  claim is what authorises writes there, but the spec describes the refusal in terms of the lane.
  **If the answer is no, that's fine** — we'll keep the correlation in our own store. We just need to
  know which. (We're not asking to write metadata without a claim; that should stay refused.)
- **Can we claim an untagged Inbox task, naming a destination lane in the same write?** Your `claim`
  takes `{taskId, lane?}`, so we believe yes. It matters because untagged isn't a lane, so a claimed
  untagged task wouldn't be protected by lane-based write refusal — we'd always move it into
  `planning` in the claim itself. If the Inbox is structurally not claimable, we'll add a `queued`
  user lane; that costs one tap, not a redesign.
- **`landed` accumulates.** Your §7 reserves `complete_task` / `delete_task` for humans, which we
  understand. But under our design most tasks end in `landed`, a notification lane where nothing is
  asked of the human — so it grows unbounded and gets archived by hand, on a phone. A `complete:
  true` option on `release` (still requiring a live claim, still audited) would fix it. We'll accept
  the manual sweep if you'd rather not.

---

## 7. What we're not asking for

So you don't build it:

- **No change feed or webhooks.** Poll + claim is fine for v1.
- **No `/eligible` endpoint.** Eligibility is pipeline knowledge and it's ours.
- **No task splitting or child-task creation.** Tasks arrive atomic, one per line.
- **No board creation by us.** A human creating a board per repo is fine.
- **No weakening of owner-only activation.** §2 asks for an owner-callable API, not a service-key one.

---

## 8. Summary

| # | Item | Blocking | Notes |
|---|---|---|---|
| 1 | Owner can force-drop a live claim | **yes** | Not in your design today |
| 2 | Programmatic activation, owner-credentialled | **yes**, for rollout | Plus the Edit-Boards UI path |
| 3 | `GET /boards/{handle}` returning `repo` + claim state | **yes** | In flight |
| 4 | Service-tier rate limit | **yes** | 2/sec sits exactly on the friend-tier cap |
| 5 | OpenAPI from zod | no | Highest leverage; our side is Python |
| 6 | metadata-write / Inbox-claim / `landed` cleanup | no | Confirmations |

Nothing is built on our side either — we're sequencing our build behind your T5–T7, so items 1–4 are
worth settling before those tranches start rather than after.
