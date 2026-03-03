# Duplicate Code Analysis Report

**Audit Date:** 2026-02-26
**Repository:** vibedispatch
**Focus:** Copy-paste violations, repeated patterns, redundant utilities

---

## Summary

Found **12 categories** of code duplication. Estimated **200+ lines** of duplicate code that could be consolidated.

| Severity | Count |
|----------|-------|
| MEDIUM | 7 |
| LOW | 5 |

---

## MEDIUM Severity

### 1. Required Fields Validation (13+ occurrences)
**Files:** All route files (`oss_routes_stage*.py`, `action_routes.py`, `oss_debug_routes.py`)

**Repeated Pattern:**
```python
if not all([origin_owner, repo, issue_number]):
    return jsonify({"success": False, "error": "Missing required fields"})
```

**Recommended Consolidation:**
```python
# backend/helpers/request_helpers.py
def validate_required_fields(data, *field_names):
    values = {f: data.get(f) for f in field_names}
    missing = [f for f, v in values.items() if not v]
    if missing:
        return None, jsonify({"success": False, "error": f"Missing: {', '.join(missing)}"})
    return values, None
```

---

### 2. Repo Name Normalization (4 occurrences)
**File:** `backend/routes/oss_routes_stage4.py:39, 145, 184, 240`

**Repeated Pattern:**
```python
if "/" in str(repo):
    repo = repo.split("/")[-1]
```

**Recommended Consolidation:**
```python
def normalize_repo_name(repo):
    return repo.split("/")[-1] if "/" in str(repo) else repo
```

---

### 3. Slug Format Conversion (7+ occurrences)
**Files:** `oss_service.py`, `oss_routes_stage1.py`, `oss_routes_stage3.py`

**Repeated Pattern:**
```python
slug = origin_slug.replace("/", "-")
# or
hyphenated_slug = f"{origin_owner}-{repo}"
```

**Recommended Consolidation:**
```python
def to_aggregator_slug(slash_slug):
    """Convert owner/repo to owner-repo for aggregator API."""
    return slash_slug.replace("/", "-")
```

---

### 4. JSON Parsing from gh CLI Output (6+ occurrences)
**Files:** Multiple routes and services

**Repeated Pattern:**
```python
result = run_gh_command([...])
if result["success"]:
    try:
        data = json.loads(result["output"])
    except (json.JSONDecodeError, KeyError):
        data = {}
```

**Recommended Consolidation:**
```python
def parse_gh_json(result, default=None):
    if not result.get("success"):
        return default or {}
    try:
        return json.loads(result["output"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return default or {}
```

---

### 5. Aggregator Response Unwrapping (5 occurrences)
**File:** `backend/services/oss_service.py` (get_watchlist, get_scored_issues, get_dossier, get_issue_brief)

Each method re-implements envelope unwrapping:
```python
result = _call_aggregator(endpoint)
if not result or not isinstance(result, dict):
    return None
data = result.get("data") or result
```

**Recommended Consolidation:**
```python
def _unwrap_response(result, key=None, default=None):
    if not result or not isinstance(result, dict):
        return default
    data = result.get("data") or result
    if isinstance(data, dict) and data.get("status") == "pending":
        return default
    return data.get(key, default) if key else data
```

---

### 6. GitHub API Command Construction (8+ occurrences)
**Files:** `oss_fork.py`, `oss_context.py`, route files

Same `run_gh_command(["api", f"repos/{user}/{repo}/...", "--jq", "..."])` pattern repeated with different endpoints.

**Recommended Consolidation:** Create typed wrapper functions:
```python
def gh_api_get(path, jq=None, timeout=30):
    args = ["api", path]
    if jq:
        args.extend(["--jq", jq])
    return run_gh_command(args, timeout=timeout)
```

---

### 7. Assignment State Lookup (2 methods with same pattern)
**File:** `backend/services/oss_state.py:90-96, 191-196`

Two methods doing the same linear search with different predicates:
```python
# find_assignment_by_fork_issue
for item in items:
    if item["repo"] == repo and item["fork_issue_number"] == int(fork_issue_number):
        return item

# find_assignment
for item in items:
    if item["origin_slug"] == origin_slug and item["issue_number"] == issue_number:
        return item
```

**Recommended Consolidation:**
```python
def _find_in_list(items, **filters):
    for item in items:
        if all(item.get(k) == v for k, v in filters.items()):
            return item
    return None
```

---

## LOW Severity

### 8. `my_user` + `svc` Initialization (34 occurrences)
**Files:** All route handlers

```python
my_user = get_authenticated_user()
svc = OSSService()
```

Appears at the top of every endpoint. Could use a decorator or Flask `g` context.

---

### 9. ThreadPoolExecutor Pattern (5 occurrences)
**Files:** `oss_routes_stage1.py`, `oss_routes_stage2.py`, `oss_routes_stage4.py`, `oss_routes_stage5.py`, `pipeline_routes.py`

Same try/except pattern around `ThreadPoolExecutor` with varying `max_workers`.

**Recommended Consolidation:**
```python
def parallel_map(func, items, max_workers=5):
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for future in as_completed([executor.submit(func, i) for i in items]):
            try:
                result = future.result()
                results.extend(result if isinstance(result, list) else [result])
            except Exception:
                pass
    return results
```

---

### 10. Hardcoded gh JSON Field Lists (4+ occurrences)
**Files:** Route files, `github_api.py`

```python
"--json", "number,title,url,headRefName,additions,deletions,changedFiles,..."
```

Same field strings repeated across files.

**Recommended:** Define as module-level constants:
```python
GH_PR_FIELDS = "number,title,url,headRefName,additions,deletions,changedFiles,reviewDecision,isDraft,createdAt,mergeable"
```

---

### 11. Sanitization Applied Piecemeal (7 calls)
**File:** `backend/services/oss_context.py`

`_sanitize_upstream_refs()` called 7 times on individual strings that are later concatenated.

**Recommended:** Build the full body first, then sanitize once at the end.

---

### 12. Success/Error Response Envelope (50+ occurrences)
**Files:** All route handlers

```python
return jsonify({"success": True, "message": "...", "owner": my_user})
return jsonify({"success": False, "error": "...", "owner": my_user})
```

**Recommended Consolidation:**
```python
def success(data=None, **kwargs):
    return jsonify({"success": True, **kwargs, **(data or {})})

def error(msg, **kwargs):
    return jsonify({"success": False, "error": msg, **kwargs})
```

---

## Consolidation Priority

### Quick Wins (HIGH impact, LOW effort)
1. **Findings 1, 3, 12** — Validation, slug conversion, response helpers (~60 lines saved)
2. **Finding 4** — JSON parsing helper (eliminates 6 try-except blocks)

### Moderate Effort
3. **Finding 5** — Aggregator unwrapping (DRY up API handling)
4. **Finding 6** — gh API wrappers (reduce command construction)
5. **Finding 7** — Generic list finder

### Nice-to-Have
6. **Findings 2, 9, 10, 11** — Smaller patterns, minor improvements

---

## Suggested New Helper Files

| File | Contents |
|------|----------|
| `backend/helpers/request_helpers.py` | `validate_required_fields()`, `success()`, `error()` |
| `backend/helpers/slug_helpers.py` | `to_aggregator_slug()`, `normalize_repo_name()` |
| `backend/helpers/gh_helpers.py` | `parse_gh_json()`, `gh_api_get()`, field constants |

These would consolidate ~200 lines of duplicated code while improving consistency and maintainability.
