# backend/tests/temporal/test_workflows.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 3 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 778 code lines (tier 1) · 858 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `test_post_submission_blocking_review_runs_remediation_then_re_signoff` | async def | 108 | 780–887 |
| `test_copilot_activities_route_to_configured_queue` | async def | 65 | 622–686 |
| `test_submit_to_upstream_false_blocks_submission` | async def | 55 | 423–477 |
| `test_local_remediation_aborts_at_iteration_cap` | async def | 49 | 970–1018 |
| `test_local_remediation_fires_when_review_finds_blockers` | async def | 44 | 926–969 |
| `test_batch_workflow_fans_out_to_children` | async def | 43 | 579–621 |

Suggested first cut: extract `test_post_submission_blocking_review_runs_remediation_then_re_signoff` (108 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/tests/temporal/test_workflows.py" --reason "..."
```
