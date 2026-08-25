# backend/temporal/workflows/issue_workflow.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 4 lanes applicable · anchor `89575ab62d18`

### size — 575 code lines (tier 1) · 610 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `IssueWorkflow` | class | 658 | 75–732 |

`IssueWorkflow` alone is 90% of the file — moving it to its own module would relocate the problem, not reduce it. Cut inside it instead:

| section inside `IssueWorkflow` | kind | lines | span |
|---|---|---|---|
| `run` | async def | 483 | 93–575 |
| `_transition` | async def | 72 | 606–677 |
| `_run_state_gates_or_defer` | async def | 55 | 678–732 |
| `_record_abort` | async def | 30 | 576–605 |
| `__init__` | def | 7 | 76–82 |
| `current_state` | def | 6 | 87–92 |
| `submit_human_decision` | def | 4 | 83–86 |

Suggested first cut: group these 7 inner sections by responsibility and extract one group at a time, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/temporal/workflows/issue_workflow.py" --reason "..."
```
