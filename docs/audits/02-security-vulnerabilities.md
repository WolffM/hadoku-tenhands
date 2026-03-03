# Security Vulnerability Audit Report

**Audit Date:** 2026-02-26
**Repository:** vibedispatch
**Focus:** OWASP Top 10 and common web application vulnerabilities

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 2 |
| HIGH | 5 |
| MEDIUM | 6 |
| LOW | 2 |
| **TOTAL** | **15** |

---

## CRITICAL FINDINGS

### 1. Command Injection Risk in GitHub API Wrapper
**File:** `backend/services/github_api.py:25-32`
**Type:** Command Injection / Unsafe Subprocess

```python
result = subprocess.run(
    ["gh"] + args,
    capture_output=capture_output,
    text=True,
    ...
)
```

**Issue:** User input from route parameters flows into `run_gh_command(args)`. While list-based args prevent shell injection, unvalidated values (repo names, owner names) could exploit `gh` CLI argument parsing.

**Exploit Scenario:** If a route accepts `repo="--help"` or a repo name with special characters, gh CLI behavior may be unexpected.

**Fix:** Validate all inputs before passing to `run_gh_command()` — whitelist alphanumeric, hyphens, underscores, dots for repo/owner names:
```python
import re
SLUG_PATTERN = re.compile(r'^[a-zA-Z0-9._-]+$')
```

---

### 2. Path Traversal Risk in Cache Layer
**File:** `backend/services/cache.py:52-56`
**Type:** Path Traversal

```python
def _get_cache_path(cache_key: str) -> str:
    key_hash = hashlib.md5(cache_key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{key_hash}.json")
```

**Issue:** While MD5 hashing the key prevents direct path traversal, the `cache_key` comes from URL route parameters that aren't validated for format or length.

**Fix:** Validate slug format at the route level before any cache operations.

---

## HIGH FINDINGS

### 3. Missing Authentication on Debug Routes
**File:** `backend/routes/oss_debug_routes.py` (all endpoints)
**Type:** Broken Access Control

All 14 `/api/oss/debug/*` routes have NO authentication checks:
- `api_oss_debug_gh_health` — exposes rate limits and API status
- `api_oss_debug_state_dump` — exposes ALL assignments, selected issues, submitted PRs
- `api_oss_debug_fork_repo` — can TRIGGER fork operations
- `api_oss_debug_build_context` — can trigger aggregator calls
- `api_oss_debug_assign_copilot` — can assign Copilot to issues

**Fix:** Add auth decorator, disable in production, or require admin key.

---

### 4. SSRF Risk in Aggregator Calls
**File:** `backend/services/oss_service.py:70-84`
**Type:** Server-Side Request Forgery

```python
url = f"{AGGREGATOR_API_URL}{endpoint}"
resp = requests.get(url, timeout=timeout)
```

**Issue:** `AGGREGATOR_API_URL` from env is concatenated with `endpoint` without URL encoding/validation.

**Fix:**
- Validate `AGGREGATOR_API_URL` at startup (must be HTTPS, known host)
- URL-encode endpoint parameters
- Block requests to private IP ranges

---

### 5. Verbose Error Messages Leak Internal Details
**File:** `backend/routes/oss_routes_stage5.py:67-87` (and others)
**Type:** Information Disclosure

```python
return jsonify({
    "success": False,
    "error": result.get("error", "Failed to create PR"),  # Raw gh CLI error
    "owner": my_user,
})
```

**Issue:** Raw `gh` CLI error messages returned to client may contain repo details, permission info, or internal paths.

**Fix:** Map errors to generic user-facing messages; log details server-side only.

---

### 6. CORS Configuration Issues
**File:** `backend/app.py:26-37`
**Type:** CORS Misconfiguration

```python
if origin in ['http://localhost:5175', 'http://127.0.0.1:5175',
               'http://localhost:5173', 'http://localhost:5174']:
    response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Credentials'] = 'true'
```

**Issues:**
- `Access-Control-Allow-Credentials: true` with dynamic origin
- Multiple hardcoded dev ports — fragile
- No production origin handling

**Fix:** Use environment-based CORS configuration. For credential-bearing requests, use explicit allowlist.

---

### 7. No Rate Limiting on Any Endpoint
**Type:** Denial of Service

~30 API endpoints with zero rate limiting. Expensive operations like:
- `/api/oss/fork-and-assign` (forks repos, creates issues)
- `/api/oss/poll-submitted-prs` (spawns ThreadPoolExecutor)
- `/api/oss/debug/state-dump` (reads all state files)

**Fix:** Add Flask-Limiter:
```python
limiter = Limiter(app, key_func=get_remote_address)

@limiter.limit("5/minute")
@bp.route("/api/oss/fork-and-assign", methods=["POST"])
```

---

## MEDIUM FINDINGS

### 8. XSS Risk in DiffViewer
**File:** `frontend/src/components/review/DiffViewer.tsx:38`
**Type:** Cross-Site Scripting

```typescript
<div dangerouslySetInnerHTML={{ __html: sanitizedHtml }} />
```

Uses DOMPurify which is good, but relies on `renderDiffToHtml()` escaping plus DOMPurify sanitization. If either fails, XSS is possible.

**Fix:** Keep DOMPurify updated. Add Content-Security-Policy headers. Consider React-native rendering instead.

---

### 9. Race Conditions in File State Operations
**File:** `backend/services/oss_state.py:98-114`
**Type:** TOCTOU Race Condition

```python
def update_assignment(self, repo, fork_issue_number, updates):
    items = self.get_assigned_issues()  # Read
    for item in items:
        if item["repo"] == repo ...:
            item.update(updates)
            _save_json("assignments.json", items)  # Write
```

Two concurrent requests could read stale data and overwrite each other's changes.

**Fix:** Implement file locking or atomic writes with temp files.

---

### 10. Unvalidated URL Extraction from gh CLI Output
**File:** `backend/routes/oss_routes_stage3.py:200-202`
**Type:** Unvalidated Data

```python
fork_issue_url = create_result["output"].strip()
fork_issue_number = fork_issue_url.split("/")[-1]
```

**Fix:** Validate URL matches expected pattern: `https://github.com/{owner}/{repo}/issues/\d+`

---

### 11. Missing Input Validation on Slugs
**File:** `backend/routes/oss_routes_stage1.py:95-106`
**Type:** Input Validation

```python
slug = data.get("slug", "").strip()
if "/" not in slug:
    return jsonify(...)
parts = slug.split("/", 1)
```

Only checks for `/` presence — no character validation.

**Fix:**
```python
SLUG_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+/[a-zA-Z0-9._-]+$')
if not SLUG_PATTERN.match(slug):
    return error("Invalid slug format")
```

---

### 12. Logging May Contain Sensitive Data
**File:** `backend/services/cache.py:92, 95, 122`
**Type:** Information Disclosure via Logs

```python
print(f"[CACHE] HIT: {cache_key} (TTL: {effective_ttl}s)")
```

Cache keys may contain repo names or user info. Uses `print()` without filtering.

**Fix:** Use Python `logging` module with configurable levels. Filter sensitive data.

---

### 13. Insecure Subprocess Timeout
**File:** `backend/services/github_api.py:16`
**Type:** DoS / Resource Exhaustion

Default timeout of 30s per subprocess call. Multiple sequential calls can tie up workers.

**Fix:** Reduce default to 10s for read-only operations. Set ceiling on total request time.

---

## LOW FINDINGS

### 14. Outdated Dependencies
**File:** `backend/requirements.txt`

- Flask 3.0.0 (check for security patches)
- python-dotenv 1.0.0 (current is 1.1.x)

**Fix:** Run `pip-audit` to check for known CVEs.

---

### 15. Hardcoded Debug Paths
**File:** `backend/services/pipeline_orchestrator.py:439-442`

```python
script = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "copilot-sessions.py")
```

**Fix:** Use `os.path.abspath()` and validate path exists.

---

## Priority Fix Order

1. **Input validation** — Add slug/repo format validation to all route handlers
2. **Auth on debug routes** — Gate behind admin key or disable in production
3. **Rate limiting** — Add Flask-Limiter to expensive endpoints
4. **Error sanitization** — Map internal errors to user-facing messages
5. **CORS config** — Use environment-based configuration
6. **File locking** — Add atomic operations for state files
7. **Dependencies** — Audit and update
