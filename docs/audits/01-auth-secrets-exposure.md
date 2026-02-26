# Auth & Secrets Exposure Audit Report

**Audit Date:** 2026-02-26
**Repository:** vibedispatch (PUBLIC)
**Focus:** Exposed authentication structures, secrets, and production infrastructure references

---

## CRITICAL FINDINGS

### 1. .env File Contains Production Secrets
**File:** `.env` (locally, NOT committed — `.gitignore` protects it)
**Severity:** CRITICAL (if ever committed)

The `.env` file contains real production credentials:
- `HADOKU_SITE_TOKEN` — GitHub Personal Access Token (ghp_...)
- `ADMIN_KEY` — Admin API key (UUID format)
- `DISCORD_WEBHOOK_URL` — Full Discord webhook URL
- `AGGREGATOR_API_URL` — Production aggregator URL

**Risk:** If `.env` is ever accidentally committed (e.g., `.gitignore` bypassed), all production secrets are exposed.

**Recommended Action:**
- Create a `.env.example` with placeholder values for documentation
- Consider adding a pre-commit hook that blocks `.env` file commits
- Regularly audit git history: `git log --all --full-history -- .env`
- Implement GitHub secret scanning alerts

---

### 2. Hardcoded Infrastructure References in Committed Code
**Severity:** HIGH

#### Production URLs in Documentation
| File | Content | Risk |
|------|---------|------|
| `CLAUDE.md` | Full aggregator API URL (`hadoku.me/oss/api`) | Reveals production domain |
| `CLAUDE.md` | Cloudflare worker name (`oss-issues-api`) | Reveals infra naming |
| `docs/planning/PROJECT-DESIGN.md` | Architecture diagrams with service names | Full system map |
| `docs/planning/VIBEDISPATCH-REQUIREMENTS.md` | API URL patterns | Endpoint enumeration |

#### Hardcoded Repository References
| File | Reference | Context |
|------|-----------|---------|
| `.github/workflows/deploy.yml` | `repos/WolffM/hadoku_site/dispatches` | Deploy target |
| `.github/workflows/publish.yml` | `repos/WolffM/hadoku_site/dispatches` | Publish target |
| `backend/routes/workflow_routes.py` | `repos/WolffM/vibecheck` | Vibecheck repo |
| `CLAUDE.md` | `WolffM/hadoku-watchparty` | Example references |
| `README.md` | `WolffM/vibedispatch.git` | Clone URL |

**Recommended Action:**
- Replace hardcoded repo references with environment variables where functional
- Move sensitive architecture docs (`CLAUDE.md` internal sections, planning docs) to a private location or redact infrastructure-specific details
- Use generic examples in documentation instead of real repo names

---

### 3. Auth Header Structure Exposed in Code
**Severity:** HIGH

| File | Line | Exposure |
|------|------|----------|
| `backend/app.py` | ~35 | CORS config reveals `X-User-Key` header name |
| `frontend/src/api/client.ts` | ~35 | Auth header construction visible |
| `frontend/src/api/client.ts` | ~97 | SessionStorage key `dispatch_key` exposed |
| `.github/workflows/deploy.yml` | ~46 | Bearer token pattern for deployment |

**Risk:** Attackers know the exact auth header name and session storage mechanism.

**Recommended Action:**
- Consider using standard `Authorization: Bearer` header instead of custom `X-User-Key`
- Implement httpOnly cookies for session management instead of sessionStorage
- Add CSRF token protection for state-changing endpoints

---

### 4. Complete API Endpoint Structure in Public Docs
**Severity:** MEDIUM

**File:** `CLAUDE.md:51-63`

All aggregator API endpoints are documented:
```
GET  /recon/watchlist
GET  /recon/{slug}/health
GET  /recon/{slug}/scored-issues
GET  /recon/all-scored-issues
GET  /recon/{slug}/dossier
GET  /recon/{slug}/issue-brief/{id}
POST /recon/{slug}/refresh
POST /recon/{slug}/claim
POST /recon/{slug}/unclaim
POST /recon/watchlist/add
POST /recon/watchlist/remove
```

**Risk:** Full API surface enumeration for attackers.

**Recommended Action:**
- Move API documentation to private docs or OpenAPI spec not checked into public repo

---

### 5. CI/CD Workflow Secret References
**Severity:** LOW

Workflows properly use GitHub Secrets (`secrets.HADOKU_SITE_TOKEN`, `secrets.GITHUB_TOKEN`), but the workflow files reveal:
- Which secrets are required
- How they're used (bearer tokens, dispatch triggers)
- Which external repositories they interact with

**Status:** Acceptable — this is standard GitHub Actions practice.

---

## Infrastructure Disclosure Summary

| Item | Disclosed In | Severity |
|------|-------------|----------|
| Production domain (`hadoku.me`) | CLAUDE.md, docs, .env | MEDIUM |
| GitHub username (`WolffM`) | Multiple files | LOW (public) |
| Related repos (hadoku-scrape, hadoku-aggregator, etc.) | CLAUDE.md, workflows | MEDIUM |
| Cloudflare worker name (`oss-issues-api`) | CLAUDE.md memory | MEDIUM |
| Full API endpoint map | CLAUDE.md | MEDIUM |
| Auth header name (`X-User-Key`) | app.py, client.ts | HIGH |
| Technology stack (Flask, React, PM2, Cloudflare) | Various | LOW |

---

## Priority Actions

1. **Immediate:** Add pre-commit hook to block `.env` commits
2. **This week:** Create `.env.example` with placeholder values
3. **This week:** Audit git history for any previously committed secrets
4. **This week:** Redact infrastructure-specific details from `CLAUDE.md` and planning docs, or move them to private docs
5. **This month:** Replace hardcoded repo references with config variables where possible
6. **This month:** Consider switching to standard auth headers
