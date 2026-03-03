# Dead Code Analysis Report

**Audit Date:** 2026-02-26
**Repository:** vibedispatch
**Focus:** Unused imports, functions, variables, orphaned files, stale code

---

## Summary

**Overall Code Health: EXCELLENT**

The codebase is remarkably clean. No significant dead code was found. All imports, functions, and dependencies are in active use.

---

## Findings

### 1. Debug Endpoints Not Called from Frontend
**Confidence:** CERTAIN (by design)
**Action:** KEEP (development utilities)

All 14 `/api/oss/debug/*` routes in `backend/routes/oss_debug_routes.py` are defined but never called from the frontend UI:

| Endpoint | Purpose |
|----------|---------|
| `/api/oss/debug/gh-health` | Check gh CLI authentication |
| `/api/oss/debug/aggregator-health` | Check aggregator connectivity |
| `/api/oss/debug/state-dump` | Dump all state files |
| `/api/oss/debug/fork-exists` | Check if fork exists |
| `/api/oss/debug/fork-repo` | Trigger fork operation |
| `/api/oss/debug/fork-ready` | Check fork readiness |
| `/api/oss/debug/sync-fork` | Sync fork with upstream |
| `/api/oss/debug/build-context` | Build agent context |
| `/api/oss/debug/create-context-issue` | Create context issue on fork |
| `/api/oss/debug/assign-copilot` | Assign Copilot to issue |
| `/api/oss/debug/score-issue` | Test issue scoring |
| `/api/oss/debug/fork-pr-status` | Check fork PR status |
| `/api/oss/debug/poll-submitted-pr` | Poll single submitted PR |
| `/api/oss/debug/notification-preview` | Preview notification format |

**Recommendation:** These are intentionally designed as development/troubleshooting tools. Consider:
- Gating behind `FLASK_DEBUG` flag in production
- Adding auth check (see security audit)
- Documenting them as internal APIs

---

### 2. Internal Pipeline Routes Not Called from Frontend
**Confidence:** LIKELY (used by orchestrator internally)
**Action:** KEEP

| Route | File | Notes |
|-------|------|-------|
| `/api/cache-stats` | `pipeline_routes.py:146` | Diagnostic endpoint |
| `/api/oss/advance-pipeline` | `oss_routes_stage4.py:24` | Internal pipeline advancement |
| `/api/oss/pipeline-status` | `oss_routes_stage4.py:57` | Used by orchestrator |
| `/api/oss/stage5-tracking` | `oss_routes_stage5.py:91` | Detailed tracking |
| `/api/repos-with-vibecheck` | `workflow_routes.py:126` | May overlap with other endpoints |
| `/api/vibecheck-template` | `workflow_routes.py:54` | Template retrieval |

---

### 3. Legacy Vibecheck Cache Functions
**Confidence:** CERTAIN — Still actively used
**Action:** KEEP

`backend/services/cache.py` lines 217-237 contain legacy cache functions:
- `get_cached_vibecheck_status()`
- `set_cached_vibecheck_status()`
- `clear_vibecheck_cache()`

These are marked as "legacy" but are still actively used by `github_api.py` and `pipeline_routes.py`.

---

## Verified NOT Dead

The audit confirmed the following are all actively used:

| Category | Status |
|----------|--------|
| Python imports | All used |
| Backend functions/methods | All called |
| Frontend components | All rendered |
| Test fixtures | All referenced |
| Config keys | All read |
| Dependencies (requirements.txt) | All imported |
| Frontend dependencies (package.json) | All imported |
| Script files | All functional utilities |

---

## No Issues Found In

- Unused imports
- Unused variables
- Unreachable code (no code after return/raise)
- Commented-out code blocks
- Orphaned files
- Stale TODO/FIXME/HACK comments
- Unused dependencies
- Unused test fixtures

---

## Recommendations

1. **Optional:** Guard debug endpoints behind `FLASK_DEBUG` environment variable
2. **Optional:** Add inline documentation for internal-only routes explaining their purpose
3. **No code removal needed** — the codebase is clean
