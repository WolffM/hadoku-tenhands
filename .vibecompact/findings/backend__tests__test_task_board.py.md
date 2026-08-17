# backend/tests/test_task_board.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 3 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 488 code lines (tier 1) · 570 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `client` | def | 39 | 84–122 |
| `test_history_and_changes_use_query_params` | def | 26 | 256–281 |
| `test_ambient_key_has_no_keyfile_fallback` | def | 22 | 455–476 |
| `Recorder` | class | 21 | 63–83 |
| `test_every_documented_code_has_a_typed_exception` | def | 17 | 490–506 |
| `test_discovery_returns_no_tasks_because_it_cannot_know_claim_state` | def | 17 | 536–552 |

Suggested first cut: extract `client` (39 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/tests/test_task_board.py" --reason "..."
```
