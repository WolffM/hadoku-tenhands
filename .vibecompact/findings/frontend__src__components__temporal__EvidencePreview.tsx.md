# frontend/src/components/temporal/EvidencePreview.tsx

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: arrival + deadcode · 6 lanes applicable · anchor `fbc0b4f2aaa3`

### arrival — 100% of 3 commits arrived with no reaching test

Before further changes: add one test whose static import path reaches this file.

### deadcode — 1 of 2 exported items unconsumed

| item | line | action |
|---|---|---|
| `EvidenceValue` | 22 | un-export — used inside this file |

Items marked *un-export* are live code — only their `export` keyword is unconsumed. Remove the keyword; deleting the symbol would break this file.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "arrival:frontend/src/components/temporal/EvidencePreview.tsx" --reason "..."
vibecheck wontfix|noise|justify "deadcode:frontend/src/components/temporal/EvidencePreview.tsx" --reason "..."
```
