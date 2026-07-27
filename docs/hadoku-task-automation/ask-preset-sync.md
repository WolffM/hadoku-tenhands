# Ask: tell a board when its provider's contract has moved

**From:** TenHands · **Date:** 2026-07-26 · **Read cold** — self-contained. Small change,
built entirely from pieces you already have.

---

## The ask

`GET /task/api/boards/:ref` should say when the board's lane set is behind the provider preset it
was activated from:

```jsonc
"presetUpdate": {
  "providerId": "tenhands",
  "schemaId": "autoland",
  "schemaVersion": 2,        // what the provider publishes now
  "label": "Autoland",
  "safe": true               // applying it moves no task — see below
}
```

Absent when the board is current, when its `schemaId` matches no configured provider, or when the
board isn't an automation board. Then the activation panel can offer *"TenHands published v2 —
apply"*, and the existing owner-only `activate-automation` does the write.

**No privilege change.** Every write stays owner-initiated; this only tells the owner there is
something to click.

## Why — the concrete instance, today

Our pipeline's final step changed: it now opens a pull request instead of merging to `main` and
watching production. Two lane descriptions and the preset's own description had to change with it,
so we bumped `schemaVersion` 1 → 2 and pushed. Your picker had the new contract within its TTL —
that part worked exactly as designed, with no message between us.

The live board is still on v1, and the only way to move it is `dryRun` → read `preview.digest` →
commit, by hand, as the owner. That's fine once. It isn't fine as the standing cost of every lane
edit, and it quietly re-creates the thing the preset endpoint was built to kill: a copy of our
contract that drifts, with nobody told.

This particular drift is cosmetic — tags, orders and `editableBy` are unchanged, so the board
behaves identically and only its stored description text is stale. That's exactly the case worth
automating, because it's the common one.

## Why we can't do it from our side

Verified, not assumed — we tried it:

```
POST /task/api/boards/:ref/activate-automation   (dryRun, as tenhands-service)
403  {"error": "Only the board owner can activate automation", "code": "FORBIDDEN"}
```

That's the right rule and we asked for it ([board-contract.md](board-contract.md) §2). We are not
asking you to relax it, and we don't want an owner credential — a pipeline holding the key that
can rewrite its own board's lane set is precisely what owner-only prevents.

## You already hold every piece

| Piece | Where |
|---|---|
| The provider's current contract, cached and revalidated | `listPresets` (`worker/src/routes/board-presets.ts`) |
| The board's `schemaId` + `schemaVersion` | `worker/src/routes/agent.ts:343`, `d1-storage.ts:131` |
| Whether applying it would strand a task | `buildPreview` → `{ digest, mapping, toInbox, collisions }` (`board-automation.ts:236-247`) |

So detection is comparing two numbers you both already have, and `safe` is `toInbox === 0` from a
preview you can already compute. Note `buildPreview` needs the active task tags — which
`GET /boards/:ref` has already loaded to hydrate its response, so `safe` costs no extra query.

`toInbox === 0` is the whole of it: every active task's current tag survives into the new lane set,
so applying the preset relabels columns and moves no work. A change that *would* clear tasks to the
Inbox is a real migration and should keep stopping for a human — that's `safe: false`.

We deliberately don't propose gating on `collisions`. It reports overlap between the lane tags and
`cfg.tags`, the board's free-form tag list — which is about tag *names*, not about any task moving,
and we haven't traced what it contains on a board that is already in automation mode. If it should
also gate, that's your call; `toInbox` is the field that answers "does anything move".

## Optional second step, and the question it raises

Once the flag exists, auto-applying a `safe: true` update is a small addition — probably a per-board
opt-in, off by default.

We'll name the objection rather than let you find it: that would be **the server performing an
owner-privileged mutation with no owner present**. We think it's defensible when the migration
provably moves no task and the change is recorded, but it is your rule and your call, and the flag
alone gets us most of the value. Ship the flag; treat auto-apply as a separate decision.

## What we are explicitly not asking for

- **No webhooks or push.** Your existing 5-minute revalidation is plenty. We don't need to know
  faster than a human notices.
- **No auto-applying an unsafe migration.** Ever. If a lane tag disappears, a human should see
  which tasks land in the Inbox before it happens.
- **No way for a contributor to activate.** Owner-only stays.
- **No new provider endpoint.** What we serve today is sufficient — the version is already in it.

## Where we are

Our contract is live and will keep moving as the pipeline evolves:

```
https://dispatch.hadoku.me/tenhands/automation/presets
https://dispatch.hadoku.me/tenhands/automation/openapi.json   ← OpenAPI 3.1, both routes
```

Details of what we publish and why are in [preset-endpoint.md](preset-endpoint.md).
