# backend/services/oss_fork.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: size · 5 lanes applicable · anchor `fbc0b4f2aaa3`

### size — 500 code lines (tier 1) · 622 raw scc lines (docstrings excluded from the tiered count)

Largest top-level symbols — the natural cut points:

| symbol | kind | lines | span |
|---|---|---|---|
| `OSSForkMixin` | class | 714 | 81–794 |
| `get_fork_lock` | def | 13 | 68–80 |

`OSSForkMixin` alone is 90% of the file — moving it to its own module would relocate the problem, not reduce it. Cut inside it instead:

| section inside `OSSForkMixin` | kind | lines | span |
|---|---|---|---|
| `_push_files_as_single_commit` | def | 147 | 507–653 |
| `_strip_pipeline_files` | def | 87 | 335–421 |
| `create_clean_branch` | def | 67 | 422–488 |
| `ensure_pipeline_files` | def | 60 | 654–713 |
| `_disable_upstream_workflows` | def | 51 | 186–236 |
| `configure_fork_settings` | def | 49 | 137–185 |
| `_build_copilot_setup_steps` | def | 47 | 748–794 |
| `approve_pending_workflow_runs` | def | 39 | 237–275 |

Suggested first cut: group these 17 inner sections by responsibility and extract one group at a time, with a test first.

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "size:backend/services/oss_fork.py" --reason "..."
```
