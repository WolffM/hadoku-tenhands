# frontend/src/api/client.ts

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: arrival + deadcode · 6 lanes applicable · anchor `89575ab62d18`

### arrival — 100% of 6 commits arrived with no reaching test

Before further changes: add one test whose static import path reaches this file.

### deadcode — 2 of 4 exported items unconsumed

| item | line | action |
|---|---|---|
| `createApiClient` | 22 | un-export — used inside this file |
| `ApiError` | 14 | un-export — used inside this file |

Items marked *un-export* are live code — only their `export` keyword is unconsumed. Remove the keyword; deleting the symbol would break this file.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "arrival:frontend/src/api/client.ts" --reason "..."
vibecheck wontfix|noise|justify "deadcode:frontend/src/api/client.ts" --reason "..."
```
