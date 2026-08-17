# backend/routes/temporal_routes.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 5 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 490 code lines (tier 1) · 665 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `temporal_inbox` | def | 70 | 342–411 |
| `temporal_signal` | def | 55 | 673–727 |
| `temporal_dispatch` | def | 53 | 426–478 |
| `_dispatch_batch` | async def | 52 | 479–530 |
| `_issue_summary` | def | 51 | 150–200 |
| `_resolve_default_branch` | def | 51 | 549–599 |

Suggested first cut: extract `temporal_inbox` (70 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/routes/temporal_routes.py" --reason "..."
```
