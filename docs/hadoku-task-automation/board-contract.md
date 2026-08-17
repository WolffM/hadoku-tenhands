# Reply to hadoku-task — automation board contract

**Re:** `docs/planning/tenhands-board-schema.md` @ `5989a0d`, §9.
**From:** TenHands. **Date:** 2026-07-24.

> **Superseded 2026-07-24 — everything in §4 shipped the same day.** Kept as the design review and
> the record of what was asked. §1 has been updated with the as-shipped API and is the part still
> worth reading; §4's asks are annotated with what landed. Current build state is in
> [README.md](README.md) §7.

We read your code before writing this, not just the doc — findings in §1, and several of the
questions we were going to ask turned out to be already answered there. Two asks were blocking
(§4.1, §4.2); everything else was confirmation or a nice-to-have.

Our pipeline is [hadoku-task-automation](README.md). It runs the **same engine** as crimson-kitty —
the OSS-contribution pipeline your doc inferred lane names from — with two ends swapped: the board
replaces the aggregator as the source of work, and "merge to our own `main`, then watch production"
replaces "open an upstream PR, then watch the maintainer." crimson-kitty is not moving to boards.

**The board is a state projection, not our database.** Temporal and our evidence store stay the
source of truth for pipeline state. The board is where that state becomes visible and steerable from
a phone, and the claim is the lock that keeps two of our runners off one task.

---

## 1. What we found in your code

**Updated 2026-07-24, post-delivery.** The table below was written against
`origin/main` *before* hadoku-task shipped the automation surface; it's kept
because several rows are still the operative facts. Rows marked → NOW SHIPPED
have since landed. The as-shipped shapes we build against:

| Call | Shape |
|---|---|
| `GET /boards/:ref` | `{board:{id,name,handle,repo,mode,lanes,schemaId,schemaVersion,access,ownerUserId}, tasks:[…,claimed], version}` |
| `POST /agent/claim` | `{board, taskId, lane?, leaseSeconds?, agentId?}` → `{token}` |
| `POST /agent/heartbeat` | `{board, taskId, token, leaseSeconds?}` |
| `POST /agent/set-lane` | `{board, taskId, token, lane}` |
| `POST /agent/release` | `{board, taskId, token, lane?, notes?, outcome?, metadata?, complete?, ifCurrentLane?}` |
| `GET /agent/history` | `?board=&task=` |
| `GET /changes` | `?since=<updatedAt>,<id>&limit=` |
| `POST /agent/cancel` | owner-only; we never call it, we observe it as `LEASE_LOST` |

**Every agent endpoint requires `board`**, which the design doc's
`{taskId, lane?}` did not. Leases: default 1800 s, max 3600 s, server-clamped.

Original findings:

| Thing | Reality |
|---|---|
| `notes` | **Live**, cap is `MAX_NOTES_BYTES = 64 KiB` (`src/domain/types.ts:204`), 413 `NOTES_TOO_LARGE` enforced at `handlers.ts:43` |
| `metadata` | **Live**, arbitrary JSON (`z.record(z.string(), z.unknown())`) |
| Task creation | **Live**, and `title` + `notes` + `tag` + `metadata` all land in **one write** — both HTTP and the MCP `create_task` tool |
| Tags | A **space-separated string** in a single `tag` column, not an array. So a "lane" is a token in that string — which is what makes your `LANE_INVALID` (zero or two lane tags) a real failure mode rather than a theoretical one |
| `boards.repo` | **Was:** column existed in migration `0002` and was `SELECT`ed, but `rowToBoard()` never mapped it — present but dead. **Now:** returned by `GET /boards/:ref` |
| `GET /boards/:ref` | **Was:** absent; `GET /boards` was the only board read and returned no hydrated tasks. **Now:** shipped, fully hydrated — config, lanes, tasks |
| Claim state on a task | **Was:** absent; `task_claims` pre-provisioned but empty. **Now:** per-task `claimed` boolean on the board read — what per-repo serialisation needs |
| Automation surface | **Was:** entirely absent, T1–T4 only. **Now:** T5–T8 shipped — activation, lane enforcement, claim/lease runtime, sharing, cancel |
| Error codes | Real in code: `TASK_NOT_FOUND`, `VERSION_CONFLICT`, `NOTES_TOO_LARGE`. Doc-only: `CLAIM_HELD`, `LEASE_LOST`, `LANE_NOT_EDITABLE`, `LANE_UNKNOWN`, `LANE_INVALID` |
| Rate limiting | **Was:** 300/120/60 per min by tier, auto-blacklist after 3 violations, and a 429 with no machine-readable code. **Now:** service tier at 600/min and the 429 carries `code: "RATE_LIMITED"` |

None of that is a complaint — your doc is honest that §6–§8 is the next build. It does mean the
contract below is a design review, and the two items in §4 are worth settling *before* T5 rather
than after.

---

## 2. Confirming the mechanism

| Thing | Verdict |
|---|---|
| Activation payload shape | Works. Ours is [`schemas/autoland-v1.json`](schemas/autoland-v1.json) |
| `dryRun` → digest → commit | Good, and the echo-back digest is the right call — we'd have shipped this wrong |
| claim → heartbeat → set-lane → release | Works. `job_id` = claim token maps cleanly onto our dispatcher interface |
| Atomic claim, server-clamped lease | The part we didn't want to build ourselves. Thank you |
| `notes` as markdown, 64 KiB | Right primitive, and the cap is generous — see §3 |
| Owner-only activation | Agreed and correct. We'll hand you payloads |
| Poll, no change feed, for v1 | Fine — **don't build webhooks for us**, but see §4.3 on poll budget |

`editableBy` genuinely is enough permission model. We went looking for the case that needs more and
didn't find one — "a human can drag out of an agent lane once no claim is live" does the work an
`onFailure` would have, without us teaching you a routing policy.

> **Correction, 2026-07-26.** The "once no claim is live" half of that sentence was our assumption,
> not their behaviour: `assertHumanLaneWrite` validates the **destination** lane only, and the human
> write path consults no claim state at all. A human can drag a task out from under a *live* claim.
>
> That's the better design — the escape hatch works even when a runner is wedged mid-job — but it
> means the agent has to find out at handback, and ours wasn't asking. `ProgressSink.finish` now
> sends `ifCurrentLane`, so a retag answers `409 LANE_CHANGED` and the release writes nothing
> instead of moving the task back and overwriting the human's `notes`. Nothing is asked of
> hadoku-task; the gap was entirely on our side.

---

## 3. Our configuration

One named config, `autoland` v1 — full payload in
[`schemas/autoland-v1.json`](schemas/autoland-v1.json). Eight lanes, three `agent`:

| `tag` | `editableBy` | What it means |
|---|---|---|
| _(Inbox)_ | — | Untagged capture. **We claim straight from untagged**, after a settle delay |
| `planning` | **agent** | Interpreting the task into a plan + clarifying questions → `notes` |
| `plan-review` | user | The plan and its questions. Answer, then drag to `replan` or `approved` |
| `replan` | user | "I answered / I disagree." Hand back for another pass. We claim from here |
| `approved` | user | Signed off. **From here nothing is asked of the human.** We claim from here |
| `working` | **agent** | Implementing end to end; capped remediation on gate failure |
| `landing` | **agent** | Merging to `main`, then watching the deploy + health signal |
| `landed` | user | Merged and production verified. **A notification, not a queue** |
| `stalled` | user | Gate failed after remediation, planning hit its cap, or it was auto-reverted |

**The planning loop is the heart of it, and your primitives cover it exactly** — including one thing
we'd otherwise have had to build. The plan lives in `notes` and iterates: we write a plan and
questions, the human answers, we re-plan, until nobody has an open question. Because we can only
write `notes` while holding a claim, and only hold one while the task is in `planning`, there is
never a moment when both sides write the same field. **The lane model gives us mutual exclusion on
a shared document for free.** We didn't expect that, and it's the reason this design works.

`notes` is rewritten each pass rather than appended, so it stays phone-legible — and at 64 KiB the
cap is a non-issue. History lives in our evidence store and your claim log.

Tasks arrive already atomic, one per line, filed by hand. **We don't split them and we don't create
child tasks** — an earlier draft of this reply asked you for that, and it was us solving a problem
you don't have. A task that needs several changes stays one task; our plan enumerates the
sub-changes and landing is all-or-nothing per task.

---

## 4. What we need from you

### 4.1 A cancel path — ~~blocking~~ ✅ shipped as `POST /agent/cancel` (owner-only; we see it as `LEASE_LOST`)

**There is no way to stop in-flight work**, and — we checked — your design doc doesn't describe one
either. The only documented ways a claim ends are a voluntary `release` or lease expiry. Once we
hold a claim the task sits in an `agent` lane a human can't drag out of, which is the correct rule
and exactly what stops a human yanking live work.

For a pipeline that merges to `main` unreviewed, that gap is real. The scenario isn't exotic: you
file a task on a bus, realise two minutes later it's wrong or already fixed, and can do nothing but
watch it land and get reverted.

**What we'd like, using machinery you already have:** let the **owner force-drop a live claim**. Our
next `heartbeat` then returns `409 LEASE_LOST`, and we abort writing nothing — behaviour you've
already specified and we've already got to implement. The task becomes an ordinary unclaimed task in
an `agent` lane, which your §3 says a human can then drag out.

No new error code, no new state. In the UI it's "release this task" on your own board. A
`cancelRequested` flag surfaced in the heartbeat response would work identically; force-drop is just
cheaper for both of us.

### 4.2 `GET /boards/{handle}` — ~~blocking~~ ✅ shipped as `GET /boards/:ref`, with `repo` and per-task `claimed`

Your doc names this our read primitive and explicitly says never to call `GET /boards`. It isn't
built — `GET /boards` is currently the only board read, and it returns no hydrated tasks. We're
happy to wait for it, we just can't build the runner's read loop against anything else.

Two things we need in the response when it lands:

- **`boards.repo`**, which is our board → checkout mapping. The column already exists and is already
  selected; it just needs mapping in `rowToBoard()` and adding to `BoardSchema`. If you'd rather we
  hang `repo` off the activation payload as an unknown-key extra, that works too — we only need it
  readable without parsing a display name.
- **Per-task claim state**, even just a boolean. We serialise ourselves to one task in flight per
  repo, because several tasks on one board often touch the same files and concurrent diffs collide.
  Without a claim flag we'd be inferring "someone is working" from lane membership, which is wrong in
  exactly the case that matters — a task in an `agent` lane whose claim already expired.

### 4.3 Poll budget — ✅ service tier now 600/min, and the 429 carries `code`

Your throttle is 120/min for a friend-tier session and auto-blacklists after 3 violations. That's
plenty for one runner polling one board, but we'd rather agree a number than discover the ceiling in
production. **Is a poll every 30 s per board acceptable?** With one board per repo and a handful of
automated repos, that's well under 120/min in aggregate — but the blacklist behaviour makes a
mistake expensive, so we'd like it in writing.

Also: the 429 body has no machine-readable `code`. We'll branch on HTTP 429 + `retryAfter` rather
than a code string. Flag it if you plan to add one, so we don't hardcode the shape.

### 4.4 Can a claim holder write `Task.metadata`? — ✅ yes, `release` accepts `metadata`

We need to persist a **Temporal workflow ID** on the task, so a tenhands restart re-correlates a
claimed task to its in-flight workflow instead of starting a duplicate.

`release` takes `{token, lane, notes?}` — no metadata. And `update_task` into an `agent` lane is
refused. So it's ambiguous whether we can write `metadata` on a task *sitting in* an `agent` lane
while *holding its claim*. Our read is that the claim is precisely what authorises writes there, but
the spec describes the refusal in terms of the lane. **Please make it explicit either way** — if the
answer is no, an optional `metadata` merge on `set-lane` or `release` covers us.

(We're not asking to write metadata without a claim. That should stay refused.)

### 4.5 Machine-readable contract — ⬜ still open, still the highest-leverage item

The strong preference on our side is that tenhands and hadoku-task talk **API to API**, with as
little hand-maintained translation as possible. You already have zod schemas as the source of truth;
the missing step is emitting them.

**If you publish an OpenAPI document generated from those zod schemas** (`zod-to-openapi` or
equivalent, versioned alongside `@wolffm/task`), we generate our client from it and the contract
becomes machine-checked. That matters more than usual here because our side is **Python**, so we
can't import your TypeScript types the way another TS consumer would — without a spec we're
hand-transcribing your schemas into Python and finding drift at runtime.

This is the highest-leverage non-blocking thing on the list. It turns every future change to the
task shape into a regenerate-and-typecheck instead of a doc read.

### 4.6 `landed` accumulates — ✅ `release` accepts `complete: true`, which archives the task

Your §7 is clear that `complete_task` / `delete_task` are human actions. Understood, and we're not
asking you to relax it lightly — but `landed` is a **notification lane, not an approval queue**, and
under this design most tasks end there. Over months it becomes a list archived by hand, on a phone,
which is the chore the pipeline exists to remove.

Options in our order of preference, **none blocking**:

1. Let a claim holder pass `complete: true` on `release`. Narrow, still needs a live claim, still
   auditable in the claim log.
2. A board setting that auto-archives tasks resting in a nominated lane for N days. Purely yours;
   we'd never call it.
3. Nothing — we accept the manual sweep.

---

## 5. What we don't need

Explicitly, so you don't build it:

- ~~**No change feed / webhooks for v1.**~~ You built one anyway (`GET /changes?since=`), and on
  reflection we'll take it — polling one board per repo is cheap, but a cursor feed is cheaper once
  more than a couple of repos are automated.
- **No `/eligible` endpoint.** Agreed with your reasoning — eligibility is pipeline knowledge.
- **No task splitting or child-task creation.** Tasks arrive atomic; §3.
- **No board *creation* by us.** A human creating a board per repo is fine. We do want an
  owner-credentialled **activation** endpoint alongside the Edit-Boards UI, so config rollout across
  a dozen boards isn't a manual chore — see [integration-blockers.md](integration-blockers.md) §2.
  That is not a request to weaken owner-only activation.
- **Nothing that a lane extra or `Task.metadata` can't carry** — beyond §4.4's write question, the
  four-field lane is sufficient.

---

## 5b. Activation runbook — verified end to end 2026-07-24

Dry-run against our own service account's `main` board, then torn back down. Every check passed:
board resolves, `repo` set, 8 lanes matching `autoland-v1`, claim → heartbeat → set-lane → release,
and a second claim correctly refused with `CLAIM_HELD`.

Four things that cost us a round trip each. None are bugs; all are worth knowing before doing this
on a real board:

1. **The dry-run digest is nested.** It comes back at `preview.digest`, not top level. Echo *that*
   on the committing call.
2. **`POST /task/api` creates a task; `POST /task/api/` 404s.** The trailing slash matters, and the
   failure is a generic "endpoint does not exist" rather than anything pointing at the slash.
3. **`id` is required on task create** (`CreateTaskInputSchema`), not server-generated. Callers mint
   the ULID.
4. **`deactivate-automation` does not clear `repo`.** After teardown the board is back to
   `mode: standard` with zero lanes, but still carries the `repo` it was activated with. Harmless
   for us — we only read `repo` on automation boards — but it means `repo` outlives the config that
   set it, which may not be what you intended.

For the record, the sequence that worked:

```
POST /task/api/boards/:ref/activate-automation  { schemaId, schemaVersion, lanes, repo, dryRun: true }
POST /task/api/boards/:ref/activate-automation  { schemaId, schemaVersion, lanes, repo, digest }
POST /task/api/boards/:ref/shares               { name: "tenhands-service", level: "contributor" }
```

---

## 6. What we're building against this

Design in [README.md](README.md); the gates that must be right before anything auto-merges in
[gates.md](gates.md). Nothing is built on our side either — we're sequencing behind your automation
surface, so §4.1 and §4.2 are worth resolving before the T5–T7 tranches start.
