# backend/temporal/activities/submission.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 4 lanes applicable · anchor `c30a2d47f010`

### size — 857 code lines (tier 2) · 1114 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `replicate_fix_as_operator` | def | 319 | 183–501 |
| `submit_upstream_pr` | def | 194 | 502–695 |
| `_render_default` | def | 102 | 1024–1125 |
| `render_pr_body` | def | 81 | 102–182 |
| `_extract_section` | def | 77 | 1170–1246 |
| `_reorder_body_sections` | def | 58 | 954–1011 |

Suggested first cut: extract `replicate_fix_as_operator` (319 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/temporal/activities/submission.py" --reason "..."
```
