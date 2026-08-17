# backend/helpers/report_generator.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 5 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 550 code lines (tier 1) · 583 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `cluster_runs` | def | 41 | 476–516 |
| `build_report_data` | def | 30 | 576–605 |
| `generate_issue_report_html` | def | 24 | 616–639 |
| `build_health_data` | def | 23 | 535–557 |
| `load_health_from_cache` | def | 18 | 517–534 |
| `derive_slugs` | def | 18 | 558–575 |

Suggested first cut: extract `cluster_runs` (41 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/helpers/report_generator.py" --reason "..."
```
