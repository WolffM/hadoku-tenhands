# backend/tests/temporal/test_activities.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 3 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 2217 code lines (tier 3) · 2457 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `test_replicate_fix_as_operator_squashes_and_opens_preview` | def | 166 | 1697–1862 |
| `test_replicate_strips_notes_md_from_squashed_tree` | def | 93 | 2007–2099 |
| `test_replicate_appends_signoff_when_dco_required` | def | 73 | 2171–2243 |
| `test_replicate_closes_stale_branch_prs_before_opening_new` | def | 72 | 1863–1934 |
| `test_replicate_no_strip_when_notes_md_absent` | def | 71 | 2100–2170 |
| `test_render_pr_body_template_path_uses_rich_default_content` | def | 68 | 1629–1696 |

Suggested first cut: extract `test_replicate_fix_as_operator_squashes_and_opens_preview` (166 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/tests/temporal/test_activities.py" --reason "..."
```
