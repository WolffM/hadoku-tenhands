# backend/tests/taskauto/test_jobs.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 3 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 508 code lines (tier 1) · 561 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `FakeLander` | class | 39 | 67–105 |
| `test_what_the_human_added_reaches_the_implementer` | def | 21 | 379–399 |
| `test_one_recognised_heading_is_enough_to_be_read_as_a_document` | def | 20 | 164–183 |
| `test_implementing_without_a_plan_routes_where_it_will_be_planned` | def | 20 | 407–426 |
| `test_re_approving_a_refused_task_rebuilds_instead_of_replanning` | def | 19 | 201–219 |
| `GitCheckouts` | class | 18 | 548–565 |

Suggested first cut: extract `FakeLander` (39 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/tests/taskauto/test_jobs.py" --reason "..."
```
