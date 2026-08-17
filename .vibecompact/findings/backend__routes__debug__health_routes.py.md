# backend/routes/debug/health_routes.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: deadcode · 5 lanes applicable · anchor `fbc0b4f2aaa3`

### deadcode — 3 of 3 exported items unconsumed

| item | line |
|---|---|
| `unused function 'api_oss_debug_gh_health'` | 23 |
| `unused function 'api_oss_debug_aggregator_health'` | 63 |
| `unused function 'api_oss_debug_state_dump'` | 90 |

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "deadcode:backend/routes/debug/health_routes.py" --reason "..."
```
