# Performance Audit Report

**Audit Date:** 2026-02-26
**Repository:** vibedispatch
**Focus:** N+1 patterns, blocking I/O, caching gaps, frontend optimizations

---

## Summary

| Impact | Count |
|--------|-------|
| HIGH | 1 |
| MEDIUM | 6 |
| LOW | 7 |
| **TOTAL** | **14** |

---

## HIGH Impact

### 1. Sequential Language Detection Makes Up to 9 API Calls
**File:** `backend/services/oss_fork.py:345-351`

```python
markers = [("go.mod", "go"), ("Cargo.toml", "rust"), ("package.json", "node"), ...]
for filename, lang in markers:
    result = run_gh_command([
        "api", f"repos/{my_user}/{repo}/contents/{filename}",
        "--jq", ".name"
    ])
    if result["success"] and result["output"].strip():
        return lang
```

**Issue:** Iterates through 9 marker files with a separate HTTP call each. Forking 10 repos = up to 90 sequential API calls.

**Fix:**
- Use a single `gh api /repos/{owner}/{repo}` call to fetch repo metadata (includes `language` field)
- Or use `gh api /repos/{owner}/{repo}/git/trees/HEAD` to list root files in one call
- Cache language detection results per repo

---

## MEDIUM Impact

### 2. Redundant File Reads for Assignment State
**File:** `backend/routes/oss_routes_stage3.py:24, 45, 107, 168`
**File:** `backend/routes/oss_routes_stage4.py:65, 107, 121, 274`

Multiple calls to `svc.get_assigned_issues()` within the same request handler each read the entire `assignments.json` file from disk.

**Fix:** Cache the assignments list within the request lifecycle. One read per request, not multiple.

---

### 3. Full JSON File Read/Write on Every State Mutation
**File:** `backend/services/oss_state.py` (throughout)

Every mutation follows: read full file -> modify in memory -> write full file.

```python
def add_to_local_watchlist(self, owner, repo):
    items = self.get_local_watchlist()  # Full file read
    items.append({...})
    _save_json("watchlist.json", items)  # Full file write
```

**Impact:** Scales poorly. 10 sequential assignments = 10 full reads + 10 full writes.

**Fix:** Implement in-memory caching with periodic flush, or consider SQLite for structured state.

---

### 4. Blocking `time.sleep(2)` in Fork Setup
**File:** `backend/routes/oss_routes_stage3.py:100`

```python
svc.trigger_compute(hyphenated_slug)
time.sleep(2)  # Blocks Flask worker thread
```

**Issue:** Ties up a Flask worker for 2 seconds waiting for aggregator compute. With 4 workers, a few concurrent requests can exhaust the pool.

**Fix:** Return immediately and let frontend poll for readiness, or use async task queue.

---

### 5. Subprocess Timeout Accumulation
**File:** `backend/services/github_api.py:25-32`

Default 30s timeout per `gh` CLI call. Multiple sequential calls in a single request can accumulate to minutes of blocking.

**Fix:** Add request-level timeout wrapper. Reduce default to 10s for read-only queries.

---

### 6. Inline Arrow Functions in React Table Rows
**File:** `frontend/src/components/oss/OSSReviewPanel.tsx:171-186`

```typescript
{readyPRs.map((pr, index) => (
  <ForkPRRow
    onView={() => { void openPRModal(pr, index) }}
    onApprove={() => { void handleApprove(pr.repo, pr.number) }}
  />
))}
```

**Issue:** New function closures created per render, breaking React.memo optimization.

**Fix:** Use `useCallback()` hooks or move handler logic into the row component.

---

### 7. Double-Fetch on Aggregator Compute Pending
**File:** `backend/routes/oss_routes_stage3.py:91-104`

```python
dossier_data = svc.get_dossier(slug)           # 1st fetch
issue_brief = svc.get_issue_brief(slug, id)    # 2nd fetch
if not dossier_context and not issue_brief:
    svc.trigger_compute(slug)
    time.sleep(2)
    dossier_data = svc.get_dossier(slug)       # 3rd fetch (retry)
    issue_brief = svc.get_issue_brief(slug, id) # 4th fetch (retry)
```

**Fix:** Cache aggregator responses with TTL to avoid duplicate external calls.

---

## LOW Impact

### 8. Multiple Filter Passes in OSSIssueList
**File:** `frontend/src/components/oss/OSSIssueList.tsx:40-47`

Three separate `.filter()` calls + `.sort()` on every filter change. Could be combined into a single pass.

### 9. Table Row Re-renders on Selection State Change
**File:** `frontend/src/components/oss/OSSIssueList.tsx:195-256`

Table rows not memoized — all re-render when `selectedCount` changes from checkbox toggles.

**Fix:** Wrap row component in `React.memo()`.

### 10. Regex Patterns Compiled at Module Load
**File:** `backend/services/oss_service.py:38-48`

Three regex patterns compiled on import. Negligible overhead but could be lazy-loaded.

### 11. Linear Label Search in Fallback Scorer
**File:** `backend/helpers/oss_helpers.py:89-99`

Uses list with `in` check instead of set for label lookup. Fine for small lists.

### 12. Extra API Call for File Existence Check
**File:** `backend/services/oss_fork.py:229-246`

Always checks if file exists before PUT, even for new files. One extra API call per workflow file setup.

### 13. Legacy Vibecheck Cache in Module Globals
**File:** `backend/services/cache.py:41-43`

```python
_vibecheck_cache: dict[str, bool] = {}
```

Unbounded dict — never expires. Still in active use but could grow indefinitely.

### 14. Store Selector Object Identity
**File:** `frontend/src/store/pipelineStore.ts`

Check that Zustand selectors aren't creating new object references on every call. Use `useShallow()` if needed.

---

## Top 3 Priority Fixes

| Priority | Issue | Impact | Effort |
|----------|-------|--------|--------|
| 1 | Language detection (9 sequential API calls) | HIGH | MEDIUM |
| 2 | Redundant file reads per request | MEDIUM | LOW |
| 3 | Blocking sleep in fork setup | MEDIUM | MEDIUM |

Fixing #1 alone could save 8+ seconds per fork operation.
