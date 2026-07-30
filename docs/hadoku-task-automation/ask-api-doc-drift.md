# Ask: `docs/API.md` documents a create-task body that cannot work

**From:** TenHands · **Date:** 2026-07-29 · **Read cold** — self-contained. Docs-only, ~10 lines.

Not automation-specific, but this is the established channel between the two repos.

---

## The finding

`docs/API.md` §`POST /` (create a task) documents a body that **always 400s**. It omits `id`, which
`CreateTaskInputSchema` requires:

```jsonc
// docs/API.md — the documented body
{ "title": "Task title", "tag": "work", "boardId": "main",
  "startTime": "…", "endTime": "…" }
```

```
$ curl -X POST https://hadoku.me/task/api -H 'X-User-Key: …' \
    -d '{"title":"probe","boardId":"MRZX1I6D…"}'
HTTP 400
{"success":false,"error":{"name":"ZodError","message":"[{ \"expected\": \"string\",
  \"code\": \"invalid_type\", \"path\": [\"id\"], … }]"}}
```

`worker/src/schemas.ts:161` — `id: z.string().min(1)`, no `.optional()`. The field table in the doc
lists only `title` as required and has no `id` row at all, so there is nothing to hint at it. A
client following the doc has to reverse-engineer a ULID requirement out of a ZodError.

## Your generated spec is already correct — the prose is the only wrong part

Worth saying plainly, because it narrows the fix: `GET /task/api/openapi.json` is right.

```
components.schemas.CreateTaskInput
  required: ["id", "title"]
  props:    board, boardId, createdAt, date, endTime, id, metadata,
            notes, source, sourceId, startTime, tag, title
```

So `app.doc()` at `worker/src/index.ts:296` emits the truth from the same zod schemas, and
`index.ts:13` already points at it. Only the hand-maintained field tables in `docs/API.md` drifted.

## Scope — one endpoint is broken, the rest is merely incomplete

| Endpoint | Doc vs generated spec | Severity |
|---|---|---|
| `POST /` | missing **`id` (required)**, plus `notes`, `board`, `createdAt`, `date`, `source`, `sourceId`, `metadata` | **Unusable as documented** |
| `PATCH /:id` | missing `notes`, `board`, `date`, `metadata` | Incomplete but works — nothing required is missing |

Only the create path actually fails. Flagging the `PATCH` gap so a fix covers both, not as a bug.

## Suggested fix

1. **Add the `id` row** to `POST /`'s table and its example. That is the whole bug.
   - Worth a decision, not just a doc edit: a client-supplied primary key is unusual for a create
     endpoint. If server-generated ULIDs were the intent, making `id` optional with a server-side
     default is the better fix and needs no doc change. Your call — we adapted either way.
2. **Consider not hand-maintaining write-body tables at all.** A correct generated spec plus prose
   tables of the same fields is two sources of truth, and this is the drift you'd predict. Either
   link `openapi.json` for field-level detail and keep the prose for intent, or add a drift test.
   - We do the third thing for our own hand-written spec — `backend/tests/test_automation_openapi.py`
     keeps `docs/hadoku-task-automation/openapi.json` honest — but our spec is hand-written *because*
     tenhands is Flask with no generator. You have a generator, so linking is strictly less work than
     testing a copy.

## One more small trap, while you're in there

The heading is `POST /`, but mounted (`index.ts:281`, `app.route('/task/api', createTaskRoutes())`)
the real path is `POST /task/api` — and **`POST /task/api/` with a trailing slash 404s**. Other parts
of the doc use full paths (`POST /task/api/01HQ.../complete`), so a bare `/` reads as "the base URL
with a slash", which is exactly the thing that doesn't work. Spelling the mounted path once at the
top of the Task Endpoints section would close it.

## What this cost

Two failed attempts inside an end-to-end test of the wake dispatch: one on the trailing slash, one on
the missing `id`. Both self-inflicted-looking at the time, which is why they were worth chasing to
the schema rather than worked around.
