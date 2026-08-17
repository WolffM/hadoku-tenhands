# frontend/src/api/types.ts

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: arrival + size · 6 lanes applicable · anchor `fbc0b4f2aaa3`

### arrival — 100% of 26 commits arrived with no reaching test; largest single-commit arrival 10× the repo median

Before further changes: add one test whose static import path reaches this file.

### size — 585 code lines (tier 1)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `RetrospectiveEntry` | interface | 70 | 298–367 |
| `TaskAutoTaskDetail` | interface | 22 | 670–691 |
| `PullRequest` | interface | 19 | 70–88 |
| `ScoredIssue` | interface | 19 | 179–197 |
| `PipelineAssignment` | interface | 19 | 279–297 |
| `TemporalIssueSummary` | interface | 19 | 531–549 |

Suggested first cut: extract `RetrospectiveEntry` (70 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "arrival:frontend/src/api/types.ts" --reason "..."
vibecheck wontfix|noise|justify "size:frontend/src/api/types.ts" --reason "..."
```
