# scripts/render_actionability_html.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 4 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 551 code lines (tier 1) · 565 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `render_issue_html` | def | 177 | 273–449 |
| `render_full_page` | def | 111 | 450–560 |
| `_operator_context` | def | 51 | 218–268 |
| `main` | def | 22 | 581–602 |
| `_collect_targets` | def | 20 | 561–580 |

Suggested first cut: extract `render_issue_html` (177 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:scripts/render_actionability_html.py" --reason "..."
```
