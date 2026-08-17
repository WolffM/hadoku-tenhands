# scripts/copilot-sessions.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 5 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 517 code lines (tier 1) · 618 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `_classify_command` | def | 153 | 231–383 |
| `analyze_workflow` | def | 135 | 384–518 |
| `extract_thinking` | def | 60 | 160–219 |
| `cmd_compare` | def | 56 | 608–663 |
| `main` | def | 49 | 705–753 |
| `cmd_batch` | def | 41 | 664–704 |

Suggested first cut: extract `_classify_command` (153 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:scripts/copilot-sessions.py" --reason "..."
```
