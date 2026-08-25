# backend/helpers/report_generator.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 4 lanes applicable · anchor `89575ab62d18`

### size — 558 code lines (tier 1) · 591 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `cluster_runs` | def | 41 | 484–524 |
| `build_report_data` | def | 30 | 584–613 |
| `generate_issue_report_html` | def | 24 | 624–647 |
| `build_health_data` | def | 23 | 543–565 |
| `load_health_from_cache` | def | 18 | 525–542 |
| `derive_slugs` | def | 18 | 566–583 |

Suggested first cut: extract `cluster_runs` (41 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/helpers/report_generator.py" --reason "..."
```
