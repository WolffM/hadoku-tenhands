# Ask: fire a GitHub `repository_dispatch` when a human moves a task into a user lane

**From:** TenHands · **Date:** 2026-07-29 · **Read cold** — self-contained. Small change,
one new outbound call and one binding.

> **AMENDED 2026-07-31 — implemented, then widened.** This ask shipped as written, and the
> `user`-lane-only predicate below turned out to be wrong in one specific way: it excluded a
> **fresh capture into the Inbox**, which is the most common thing a person does on a board. That
> left creating a task as the only action with no fast path, so it fell through to the backstop
> cron — whose shortest observed gap across 73 consecutive delivered runs was **24 minutes**, mean
> ~45. The predicate is now "a human wrote something", with `agent` lanes as the only exclusion:
> `isUserLaneWrite` returns `true` for an empty tag instead of `false`.
>
> The settle delay that motivated the exclusion is unchanged in spirit and now **1 minute**; it is
> enforced on the TenHands side by sleeping before the sweep (`taskauto.yml`, "Let a fresh capture
> settle"), which keeps runner policy out of the worker exactly as this doc argues it should be.
> Everything else below — payload, token, fire-and-forget posture, no-authority framing — still
> holds as written.

---

## The ask

When a **human-path write** lands a task in a **`user` lane** on an **automation board that
records a `repo`**, the worker should `POST` a `repository_dispatch` to that repo:

```http
POST https://api.github.com/repos/{cfg.repo}/dispatches
Authorization: Bearer {token}
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
User-Agent: hadoku-task-worker

{
  "event_type": "taskauto",
  "client_payload": {
    "boardId":  "<owner-scoped board slug>",
    "handle":   "<board handle>",
    "taskId":   "<task id>",
    "lane":     "<destination lane tag>",
    "at":       "<ISO-8601>"
  }
}
```

Fire-and-forget, off the response path. A `204` is success; anything else is logged and dropped.
**A failed dispatch must never fail the human's write.**

That is the whole change. Everything below is why, where, and the edges.

## Why

TenHands' pipeline runs as an ephemeral GitHub Actions job on a `*/15` cron
(`.github/workflows/taskauto.yml`). It does not need to be told a task exists — a fresh run sweeps
every board on its first tick. It needs to be told **sooner**.

The cron is not delivering. Measured over 63.5 hours of real run history on `WolffM/tenhands`:

| | |
|---|---|
| Scheduled runs expected at `*/15` | 254 |
| Scheduled runs GitHub actually delivered | **78** (31%) |
| Median gap between runs | **46 min** |
| p90 gap | 75 min |
| Max gap | 89 min |

Every run succeeded in ~18s with 0s queue time, so this is not a busy runner — GitHub deprioritises
the `schedule` trigger and drops roughly two of every three events. **A task dragged to `approved`
currently waits a median of ~23 minutes, and up to ~89, before anything looks at it.**

Tightening the cron does not help: the throttle is on delivery, not on the schedule expression.
`repository_dispatch` is **not** throttled that way — it starts a run immediately, and the runner is
self-hosted and idle, so the observed start latency is seconds.

The pipeline's own scheduler already reached this conclusion and never got the other half built —
`backend/temporal/taskauto/scheduler.py:32`:

> **push for latency, poll for correctness.** […] If a webhook is added later it should *wake the
> loop early* — never replace it.

This ask is exactly that half. The cron stays as the backstop; TenHands drops it to hourly, which is
close to what GitHub is really giving it today, so nothing is lost if a dispatch goes missing.

## Why the worker stays policy-free

The obvious version of this is "fire when a task hits `approved` or `replan`". **Don't do that** —
it would put pipeline policy in the worker, which `worker/src/routes/agent.ts:9` explicitly refuses:

> The worker performs no orchestration: it hands out leases and records outcomes. "Eligible" is the
> runner's business, so there is no /agent/eligible.

Which lanes are claimable is TenHands' business and it changes on TenHands' schedule (today
`approved` and `replan`, per `backend/temporal/taskauto/selection.py:59-62`). So the predicate here
is deliberately structural rather than semantic:

> a human wrote a task into a lane a human is allowed to write, on a board wired to a repo.

The worker says *"something a person did moved on this board"*. TenHands decides whether that is
actionable. An idle run costs 18 seconds, so over-firing is cheap and under-firing is not; and when
TenHands adds a lane, no change lands here.

## Where

`assertHumanLaneWrite` already marks every human-path lane write, and there are exactly two call
sites. Both need the hook, so put it in a shared helper next to `assertHumanLaneWrite` in
`worker/src/routes/board-automation.ts` rather than at each site.

| Path | Call site |
|---|---|
| HTTP | `worker/src/routes/route-utils.ts:267-269` (`handleBoardOperation`, `'laneTag' in opts && ctx.mode === 'automation'`) |
| MCP | `worker/src/mcp/tools.ts:215` and `:250` |

`handleBoardOperation` has `ctx.ownerId` / `ctx.boardId` / `ctx.mode` / `ctx.lanes` (`BoardCtx`,
`route-utils.ts:18-30`) but **not** `repo` or `handle` — those come from
`getBoardConfig(env.DB, ownerId, boardId)` (`board-automation.ts:135`).

Fire **after** the write commits, not before. A dispatch for a write that then failed validation
sends the pipeline looking for a task that never moved.

### The exact predicate

Fire when **all** hold:

1. `cfg.mode === 'automation'`
2. `cfg.repo` is non-empty (format `owner/name`, per `schemas/autoland-v1.json`)
3. the destination tag is **non-null** and resolves to a lane with `editableBy === 'user'`

Point 3 does the real filtering:

- **Untagged Inbox writes do not fire.** `assertHumanLaneWrite` permits a null tag, and the Inbox is
  where half-formed thoughts land — TenHands deliberately waits 5 minutes of no edits before
  planning one (`selection.py:45`). Pushing on every keystroke-completing save would defeat that,
  and the backstop sweep picks settled tasks up anyway.
- **Agent-lane writes do not fire.** They are the pipeline's own writes; it does not need waking up
  to hear from itself.
- Writes that do not touch the tag (complete, delete, schedule) omit `laneTag` entirely and are
  already outside this path.

## The token

`worker/src/types.ts:21` already binds `GITHUB_READ_TOKEN`, resolved from the `HADOKU_SITE_TOKEN`
vault key (already in this repo's `.devvault.json`), used today by `validateRepo`
(`routes/automation.ts:215`). **It is the same PAT TenHands' workflow runs as** — `taskauto.yml`
passes `secrets.HADOKU_SITE_TOKEN` as `GH_TOKEN` — so no new secret has to be minted or granted.

- **Scope: verified, nothing to do.** `HADOKU_SITE_TOKEN` reports
  `x-oauth-scopes: repo, write:packages`, and `POST /repos/{o}/{r}/dispatches` needs `repo`. So the
  existing binding is sufficient — no new secret to mint, no grant to request, no ACL change. (Worth
  having checked: tenhands is a private repo, so an under-scoped token would have failed with a
  silent `404` rather than a `403`.)
- **Name.** Using a binding called `GITHUB_READ_TOKEN` for a write makes the name a lie. Prefer a
  second binding `GITHUB_DISPATCH_TOKEN` mapped to the same vault key, so the two uses can be
  scoped apart later without a code change.

If the binding is absent, skip silently — same posture as `GITHUB_READ_TOKEN` today. An
unconfigured install must not start failing board writes.

## Off the response path — reuse the existing idiom

Use `c.executionCtx.waitUntil`, and copy the hazard handling from `warmPresets`
(`worker/src/routes/preset-update.ts:91-118`) rather than rediscovering it:

> `c.executionCtx` is a **THROWING GETTER**, not a possibly-undefined property —
> `c.executionCtx?.waitUntil(p)` reads as safe and is not, it raises "This context has no
> ExecutionContext" wherever one isn't supplied (the dev stack, and any direct `app.request()`
> caller).

So: `try`/`catch` the getter, bail if there is no `waitUntil`, and hand it a promise that never
rejects. Give the `fetch` a short timeout (~5s) — a hung dispatch must not hold a `waitUntil` open.

Under the MCP path there may be no `ExecutionContext` at all; awaiting the dispatch inline there is
acceptable if it is timeout-bounded and its failure is swallowed.

## Non-goals

- **Not a general webhook system.** One event type, one destination derived from `cfg.repo`, no
  subscriber registry, no user-configurable URLs.
- **No delivery guarantee.** No retries, no queue, no dead-letter. The cron backstop is the
  guarantee; this is the fast path. Do not build durability here.
- **Not a replacement for `GET /changes`.** TenHands keeps polling it. This ask only shortens the
  wait for the first look.

## Optional: coalesce

Dragging three tasks to `approved` fires three dispatches. TenHands' workflow has
`concurrency: { group: taskauto, cancel-in-progress: false }` and each run drains up to 8 tasks, so
the extras queue behind the first run and mostly find nothing — harmless, just noisy.

If that noise bothers you, a ~10s debounce per `repo` in `TASKS_KV` collapses a burst into one
dispatch. **Ship without it first.** It trades a real correctness property (every human action wakes
the pipeline) for tidiness, and the noise may well not be worth it.

## What TenHands does on its side

**Already landed** (`taskauto.yml`, as of 2026-07-29) — so the receiving end is live and waiting:

1. `on: repository_dispatch: { types: [taskauto] }`. **`event_type` must be exactly `taskauto`.**
2. `client_payload` is logged for tracing but **not** trusted or acted on — the run does its normal
   board sweep. That keeps the dispatch a pure wake signal, so a malformed or duplicated payload
   cannot make the pipeline do the wrong thing. It is passed through `env`, never interpolated into a
   shell line, because this job holds a PAT that can push to `main`.
3. The cron **stays at `*/15`** — correcting what an earlier draft of this doc said about relaxing it
   to hourly. An untagged Inbox write deliberately does not dispatch, so the cron is the *only* path
   that gets an Inbox task planned; relaxing it would have traded latency you can see for latency you
   can't. Nothing in this ask depends on that choice either way.

Point 3 is the security posture worth stating plainly: the dispatch carries no authority. It says
"look now", never "do this".

Note that `repository_dispatch` only triggers a workflow whose file exists on the repo's **default
branch** — this is already true for `taskauto.yml`, but it is the usual reason a first test appears
to do nothing.

## Acceptance

- [ ] Dragging a task to `approved` on the TenHands automation board starts a `taskauto` run within
      ~10s of the drag.
- [ ] Creating or editing an untagged Inbox task fires **nothing**.
- [ ] A pipeline write into `working` / `planning` / `landing` fires **nothing**.
- [ ] A lane write on a `standard` (non-automation) board fires nothing, and one on an automation
      board with no `repo` fires nothing.
- [ ] With the token binding removed, board writes still succeed.
- [ ] With the token invalid (GitHub returns `404`), the board write still succeeds and the failure
      is logged with the repo and status.
- [ ] Unit coverage for the predicate alongside the existing lane-write tests; `worker/test/` has
      the shape to copy (`agent-claim-verify.ts`, `presets-verify.ts`).
