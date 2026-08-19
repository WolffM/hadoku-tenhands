# backend/tests/temporal/test_gates.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 2 lanes applicable · anchor `c30a2d47f010`

### size — 747 code lines (tier 1) · 807 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `TestPipelineNamespacing` | class | 142 | 721–862 |
| `TestUniformGateDecisionTelemetry` | class | 99 | 863–961 |
| `test_submission_judge_payload_strips_notes_md` | def | 32 | 689–720 |
| `test_environment_works_fails_on_noop_install` | def | 23 | 177–199 |
| `test_repro_evidence_present_passes_with_bold_labels` | def | 23 | 257–279 |
| `test_verified_pass_with_verify_notes_md` | def | 17 | 407–423 |

Suggested first cut: extract `TestPipelineNamespacing` (142 lines) into its own module, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/tests/temporal/test_gates.py" --reason "..."
```
