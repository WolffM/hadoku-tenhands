# backend/routes/debug/fork_routes.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: deadcode · 4 lanes applicable · anchor `fbc0b4f2aaa3`

### deadcode — 4 of 4 exported items unconsumed

| item | line |
|---|---|
| `unused function 'api_oss_debug_fork_exists'` | 19 |
| `unused function 'api_oss_debug_fork_repo'` | 39 |
| `unused function 'api_oss_debug_fork_ready'` | 68 |
| `unused function 'api_oss_debug_sync_fork'` | 87 |

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "deadcode:backend/routes/debug/fork_routes.py" --reason "..."
```
