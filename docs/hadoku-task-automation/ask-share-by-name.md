# Ask: grant board shares by display name, not raw key

**From:** TenHands · **Date:** 2026-07-24 · **Read cold** — self-contained.
**Size:** small change, but it has one security prerequisite that is *not* small (§3).

---

## 1. The ask

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
That's the thing we'd like to stop doing.

`userId` isn't an escape hatch either: `listKeyInventory` (edge-router `src/registry.ts`) returns
`keyPreview`, `name`, `tier`, `createdAt`, `lastSeenAt` — **no `userId`** — so there is no surface
that shows an operator a `userId` to copy. Name is the only identifier a human actually has.

## 2. Why it matters

A raw key is a bearer credential. Granting access shouldn't require handling one:

- it ends up in shell history, clipboards, and screenshots of the grant call;
- it's the one identifier that must never be logged, so every call site handling it needs care;
- the board owner granting access has no legitimate need to *possess* the grantee's credential —
  they only need to name them.

Everything needed already exists on your side: the registry row has both `name` and `userId`, and
`resolveGrantee` already reads that row. This is a lookup change, not a new concept.

## 3. The prerequisite — display names are not currently safe to authorise against

**This is the part worth reading twice.** Making `name` a grant target turns a cosmetic field into
an authorisation identifier, and today nothing stops two keys sharing a name.

- `sanitizeName` (edge-router `src/registry.ts`) only trims and truncates. **No uniqueness check.**
- `resolveNextName` only stops a `wp-*`-prefixed name being overwritten by a non-prefixed one. It
  does not stop a *different key* claiming a name already in use.
- `POST /session/create` lets **any valid key — admin, service, or friend — set its own name**, with
  no admin involvement. We used that ourselves an hour ago to register as `tenhands-service`.

So as things stand, a friend-tier key holder could name their key `tenhands-service`, and a board
owner granting that name could hand `contributor` to the wrong key. That's a privilege escalation
created by the feature, not one that exists today.

The general rule it violates: **an identifier used for authorisation must not be settable by the
party seeking authorisation.** (We hit the same class of bug in our own pipeline this week — a gate
was reading its authorisation out of a field the agent could rewrite. Same shape, same fix:
constrain the source.)

### What would make it safe

Any one of these is sufficient; the first is our preference:

1. **Enforce name uniqueness in the registry**, first-come-wins. `upsertKeyRecord` /
   `adminSetKeyRecord` reject a name already bound to a different key. Names then become real
   identities and the lookup is unambiguous. Needs a reverse index (`name:{name}` → key) since KV
   has no secondary index — cheap, and it also makes the lookup O(1).
2. **Resolve by name but fail closed on ambiguity.** If more than one registry row carries the name,
   return an error listing the candidates by `keyPreview` + `tier`, and make the caller disambiguate.
   Never pick one. Cheaper than (1), but leaves a confusing failure mode in place.
3. **Restrict self-naming.** Only an admin may set a name (`POST /session/admin/keys`), and
   `/session/create` stops accepting one. Safest, but it means a machine key can't self-register
   its own name — which is the thing that made *our* setup pleasant, so we'd rather not.

Whichever you pick, **surface `tier` and `keyPreview` in the grant response** so the owner can see
what they just granted:

```jsonc
{ "granted": { "name": "tenhands-service", "tier": "service", "keyPreview": "0470…", "level": "contributor" } }
```

## 4. Suggested shape

```
POST /task/api/boards/:ref/shares
{ "name": "tenhands-service", "level": "contributor" }   // preferred
{ "userId": "…", "level": "contributor" }                 // keep
{ "key": "…",    "level": "contributor" }                 // keep for now, deprecate later
```

`resolveGrantee` gains a `name` branch. Errors we'd want to handle distinctly:

| Case | Suggested |
|---|---|
| no row with that name | `404` / `NAME_NOT_FOUND` — "no registered key named X" |
| several rows with that name | `409` / `NAME_AMBIGUOUS`, listing `keyPreview` + `tier` |
| row exists but has no `userId` | `409` — never signed in; the existing message is fine |

We'd also take `userId` being added to `listKeyInventory` regardless — it's not secret, and it makes
option (2) workable from the admin UI.

## 5. Where we are

Not blocking us: we can paste our key once to get the first board shared, and we will if you'd
rather do this properly later than quickly now.

For reference, our key is already registered — `name: "tenhands-service"`, `tier: "service"`, with a
`userId` minted (we called `POST /session/create` with the key and a name, which does both in one
call). So the moment a name branch exists, `{"name": "tenhands-service"}` should resolve.

One small thing we hit on the way, unrelated but cheap to note: Python's `urllib` default User-Agent
trips Cloudflare **1010** on `hadoku.me`, while `requests` gets through. Anything scripted against
these endpoints needs an explicit UA.
