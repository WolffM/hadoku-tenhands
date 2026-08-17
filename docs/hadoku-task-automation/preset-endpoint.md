# Reply to hadoku-task — `GET /automation/presets`

**From:** TenHands · **Date:** 2026-07-25 · **Re:** your ask for a fetchable lane contract.

Shipped. Point `AUTOMATION_PRESET_SOURCES` at:

```json
[{ "id": "tenhands", "label": "TenHands", "url": "https://dispatch.hadoku.me/tenhands/automation/presets" }]
```

The contract is also machine-readable, at
`https://dispatch.hadoku.me/tenhands/automation/openapi.json` — §6.

---

## 1. Why that host, and not `hadoku.me/tenhands`

`hadoku.me/tenhands/*` is the **dashboard SPA**, served from GitHub Pages and gated at edge-router
at `friend` tier. It never reaches this Flask app, and an anonymous fetch there gets a 401 from the
edge before we see it.

The backend is the cloudflared tunnel origin, `dispatch.hadoku.me`. It is https, publicly routable
and unproxied by the tier manifest — which is exactly why the app gates *itself* by delegating to
`/session/whoami` (`backend/middleware/whoami.py`). This one path is on that gate's `_PUBLIC_PATHS`
allowlist, next to the monitoring healthcheck.

Two things that follow, so nobody has to rediscover them:

- **Your `User-Agent: hadoku-task` gets through Cloudflare.** Not a given — the default
  `python-urllib` UA is blocked with a 1010 on this zone, which is why our whoami client sets its
  own. Yours was verified against the origin before this shipped.
- **No CORS headers are served on it**, per your design. Fetch server-side.

## 2. What you get: one preset, not two

You guessed §5 was "Simple Work" vs "Complex Work". It isn't — our §5 is *Two pipelines, one gate
registry*, and the two pipelines are **hadoku-task-automation** (this one) and **crimson-kitty**
(the OSS-contribution pipeline). They share a gate registry and an engine, not a board:
crimson-kitty's work arrives from the aggregator and leaves as an upstream PR, so it has no lane
vocabulary to publish and [is not moving to boards](board-contract.md).

So the array has exactly one entry today, `autoland` v1 — the eight lanes in
[schemas/autoland-v1.json](schemas/autoland-v1.json), described in [board-contract.md](board-contract.md) §3.
A second pipeline shape would be a second file in `schemas/`; it appears in the same array with no
endpoint change and nothing to coordinate.

**The file is the source of truth, not a copy of it.** `schemas/autoland-v1.json` is already the
payload we hand to `activate-automation` and already what `scripts/taskauto_smoke.py` diffs a live
board against. Serving those same bytes is the point — a hand-maintained Python copy would be the
pasted-JSON problem again, one layer down.

## 3. The contract, against your two requirements

| | |
|---|---|
| https | ✅ and there is no http URL to fall back to — the origin is reachable only through the cloudflared tunnel, which terminates TLS at Cloudflare |
| Strong `ETag` | ✅ `sha256` over the **exact bytes served**. Not an mtime — a git checkout restamps every file on deploy, so an mtime validator would make you re-download on deploys that changed nothing |
| `If-None-Match` → 304 | ✅ |
| `Cache-Control` | `public, max-age=300`, matching your TTL, so nothing in between holds a staler copy than you would |
| Auth | None. Listed in `_PUBLIC_PATHS`, rate-limited to 60/min |

Body is your preferred shape, `{ "presets": [ … ] }`.

Two deliberate deviations from "exactly what you POST to activate-automation":

- **`repo` is stripped.** It's per-board — the value in the file is the placeholder
  `WolffM/<repo>` — and a preset is a lane vocabulary, not a board. Your `toPreset` ignores it
  anyway; publishing a placeholder that reads like a real repo is just a trap for whoever reads
  the JSON next.
- **A failure is `503`, never `{"presets": []}`.** "We're broken" must not be indistinguishable
  from "we have no lane sets" — on a 503 you keep serving your last good copy, which is the
  behaviour we want.

Lane `description` keys ride along as extra keys and survive your validator verbatim. They're worth
keeping: they're the per-lane "what is this column for" text.

## 4. One thing this ask fixed on our side

The payload had **two lanes at `order: 0`** — `planning` and `plan-review`. `validateLaneSet`
doesn't check `order`, so it would have activated cleanly and the column order would have been
decided by whichever way the sort broke the tie. Renumbered 0–7, and our validator now rejects a
duplicate `order` so it can't come back.

**Any board activated from the old pasted copy is one re-activation behind.** Lane *tags* are
unchanged, so this is a re-ordering, not a migration — nothing lands in a lane that no longer
exists. Which is a small illustration of the thing you were asking for.

## 5. How it's kept honest

`backend/tests/test_automation_presets.py`, on top of the HTTP-contract tests:

- every payload in `schemas/` passes a Python port of your `validateLaneSet`, so we find out at
  test time that we broke our own contract rather than by your picker quietly dropping us;
- the served lane tags must equal the lane constants in `temporal/taskauto/selection.py` — we
  can't advertise a lane the runner never claims from.

Verified against your actual consumer, not a mock: `worker/src/routes/board-presets.ts`'s
`listPresets()` (from the `t5-shared-boards` branch) bundled and run against the deployed URL,
with `Date.now` pushed past your TTL so the revalidation path runs for real.

```
✓ source ok                                   ✓ 8 lanes
✓ one preset offered                          ✓ lane descriptions survived as extra keys
✓ schemaId / schemaVersion                    ✓ inside TTL: served from memory, no network
✓ label + description present                 ✓ past TTL: revalidated, provider answered 304
                                              ✓ 304 kept the parsed lanes
```

> **Follow-up, 2026-07-26:** activation reads the contract once, so a board goes stale the next time
> we change a lane — and only its owner can re-activate. A follow-up asks the task board to surface
> that staleness on the board read.

## 6. The contract, machine-readable

`GET https://dispatch.hadoku.me/tenhands/automation/openapi.json` — OpenAPI 3.1, public, same
strong-ETag revalidation, served byte-for-byte from
[openapi.json](openapi.json). It describes both routes, the `If-None-Match`/304 behaviour and the
`AutomationPreset` / `Lane` schemas, so a client can be generated rather than transcribed.

This is §4.5 of [board-contract.md](board-contract.md) answered in the other direction. We asked you
for a spec because our side is Python and can't import your TypeScript types; publishing an
undocumented endpoint at you would have been that request made in bad faith.

**It is hand-written, not generated** — Flask has no schema layer to generate from — so the honesty
guarantee has to come from tests instead, and `backend/tests/test_automation_openapi.py` is modelled
on your `openapi-verify.ts` for the same reason yours exists:

- every documented path must exist in the Flask URL map, and **every automation route must be
  documented** — a route added with a bare `@bp.route` fails the suite rather than silently dropping
  out of the contract;
- a live response is validated against the document's own `PresetDocument` schema, and the shipped
  `schemas/*.json` against `AutomationPreset`;
- both directions of the drift guard were confirmed to fail when the spec and the app disagree —
  a guard nobody has seen fail is decoration.

Two things the document is careful to state rather than imply: the 429 body is Flask-Limiter's
default HTML with no `Retry-After`, so branch on the status code; and the cross-field lane rules
(unique `tag`, unique `order`, no whitespace in a `tag`) live in `validate_lane_set`, because JSON
Schema can't express them.
