# scripts/retro_report.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 5 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 492 code lines (tier 1) · 523 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `print_pr_report` | def | 217 | 188–404 |
| `print_batch_report` | def | 193 | 405–597 |
| `main` | def | 66 | 625–690 |
| `find_issue` | def | 27 | 598–624 |
| `fetch_pr_commits` | def | 21 | 73–93 |
| `_extract_rule` | def | 20 | 153–172 |

Suggested first cut: extract `print_pr_report` (217 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:scripts/retro_report.py" --reason "..."
```
