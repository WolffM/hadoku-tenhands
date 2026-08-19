# backend/tests/temporal/test_temporal_routes.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 2 lanes applicable · anchor `c30a2d47f010`

### size — 558 code lines (tier 1) · 600 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `test_inbox_enriches_operator_signoff_with_preview_pr_and_body` | def | 38 | 281–318 |
| `test_dispatch_calls_temporal_client` | def | 38 | 459–496 |
| `test_inbox_resolve_all_clears_every_deferred_entry` | def | 33 | 401–433 |
| `test_signal_legacy_payload_without_reason_code_still_works` | def | 33 | 565–597 |
| `_seed_issue` | def | 32 | 53–84 |
| `test_signal_persists_structured_override` | def | 29 | 598–626 |

Suggested first cut: extract `test_inbox_enriches_operator_signoff_with_preview_pr_and_body` (38 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/tests/temporal/test_temporal_routes.py" --reason "..."
```
