# backend/services/dispatchers.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 4 lanes applicable · anchor `89575ab62d18`

### size — 480 code lines (tier 1) · 599 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `CopilotSWEDispatcher` | class | 252 | 72–323 |
| `CopilotRemediationDispatcher` | class | 171 | 572–742 |
| `GitHubActionsDispatcher` | class | 143 | 324–466 |
| `CopilotReviewDispatcher` | class | 105 | 467–571 |
| `StageDispatcher` | class | 48 | 24–71 |
| `create_default_registry` | def | 11 | 743–753 |

Suggested first cut: extract `CopilotSWEDispatcher` (252 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/services/dispatchers.py" --reason "..."
```
