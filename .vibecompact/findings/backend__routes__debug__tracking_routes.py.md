# backend/routes/debug/tracking_routes.py

Single-lane finding (below the corroboration gate — one signal, weigh accordingly) · firing: deadcode · 4 lanes applicable · anchor `fbc0b4f2aaa3`

### deadcode — 3 of 3 exported items unconsumed

| item | line |
|---|---|
| `unused function 'api_oss_debug_fork_pr_status'` | 22 |
| `unused function 'api_oss_debug_poll_submitted_pr'` | 56 |
| `unused function 'api_oss_debug_notification_preview'` | 142 |

### If this finding is wrong or accepted

```
vibecheck wontfix|noise|justify "deadcode:backend/routes/debug/tracking_routes.py" --reason "..."
```
