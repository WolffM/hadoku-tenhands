# backend/routes/taskauto_routes.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 4 lanes applicable · anchor `c30a2d47f010`

### size — 537 code lines (tier 1) · 666 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `_prs_for` | def | 91 | 104–194 |
| `taskauto_status` | def | 78 | 373–450 |
| `taskauto_task` | def | 60 | 495–554 |
| `taskauto_send_back` | def | 60 | 688–747 |
| `taskauto_pr_details` | def | 55 | 633–687 |
| `taskauto_merge` | def | 52 | 555–606 |

Suggested first cut: extract `_prs_for` (91 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/routes/taskauto_routes.py" --reason "..."
```
