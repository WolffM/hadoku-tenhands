# Ask: grant board shares by display name, not raw key

**From:** TenHands · **Date:** 2026-07-24 · **Read cold** — self-contained. Small change.

---

## The ask

`POST /task/api/boards/:ref/shares` should accept a **display name**:

```jsonc
{ "name": "tenhands-service", "level": "contributor" }
```

Today `resolveGrantee` (`worker/src/routes/shares.ts`) accepts only `key` or `userId`:

```ts
async function resolveGrantee(env, input: { key?: string; userId?: string }) {
  if (input.userId) return { userId: input.userId }
  const key = input.key
  if (!key) return { error: 'Provide `key` (grantee access key) or `userId`.' }
  const raw = await env.SESSIONS_KV.get(`key:${key}`)
  ...
}
```

**So the only way to grant a share today is to paste the grantee's raw key into a request body.**

`userId` isn't a way out: `listKeyInventory` returns `keyPreview`, `name`, `tier`, `createdAt`,
`lastSeenAt` — **no `userId`** — so nothing shows an operator a `userId` to copy. The display name is
the only identifier a human actually has.

## Why

A raw key is a bearer credential. Granting access shouldn't involve handling one: it lands in shell
history, clipboards, and screenshots of the grant call, and the board owner has no legitimate need
to *possess* the grantee's credential. They only need to name them.

## Why this is now safe — and cheap

**Display names are already unique**, case-insensitively, enforced by `isNameTaken` at every write
path in edge-router:

- `POST /session/create` (`session.ts:624`) → 409
- `POST /session/name` (`session.ts:369`) → 409
- `POST /session/admin/keys` (`key-admin.ts:106`) → 409 — even an admin can't take a held name

Retired rows are excluded so a rotated key can reclaim its own name, and `excludeKey` makes
re-setting your own name a no-op. So a name already *is* a stable, unambiguous identity, and
resolving a grantee by it is a lookup change rather than a new trust decision.

The lookup is the same shape as the one `isNameTaken` already does — a `KV.list` under `key:` plus a
`get` per row. `registry.ts` already documents the scaling caveats and the fix (a `name:{lower}` →
key index) if the registry ever outgrows it; nothing here makes that more urgent.

## Suggested shape

```
POST /task/api/boards/:ref/shares
{ "name": "tenhands-service", "level": "contributor" }   // preferred
{ "userId": "…", "level": "contributor" }                 // keep
{ "key": "…",    "level": "contributor" }                 // keep for now, deprecate later
```

Errors worth distinguishing:

| Case | Suggested |
|---|---|
| no live row with that name | `404` / `NAME_NOT_FOUND` — "no registered key named X" |
| row exists but has no `userId` | `409` — never signed in; the existing message is right |

Two small extras, both optional:

- **Echo what was granted** — `{"granted": {"name": …, "tier": "service", "level": "contributor"}}` —
  so the owner can see they granted a service key and not something else.
- **Match names case-insensitively**, consistent with `isNameTaken`, so `TenHands-Service` resolves.
- **Add `userId` to `listKeyInventory`** if it's free. Not secret, and useful in the admin UI.

## Where we are

Not blocking: we can paste our key once to get the first board shared, and will if you'd rather do
this properly later than quickly now.

Our key is already registered — `name: "tenhands-service"`, `tier: "service"`, `userId` minted (we
called `POST /session/create` with the key and a name, which does both in one call). So the moment a
name branch exists, `{"name": "tenhands-service"}` should resolve.

One unrelated thing we hit, cheap to note: Python's `urllib` default User-Agent trips Cloudflare
**1010** on `hadoku.me`, while `requests` gets through. Anything scripted against these endpoints
needs an explicit UA.
