Operational runbook for dispatching issues to Copilot agents.

## Pre-dispatch checklist

1. **Check aggregator coverage.** `GET /recon/{slug}/dossier` — repos with dossiers get context_tier 1 (rich context). Without it, agents fall back to tier 3 (just issue body + CONTRIBUTING.md). Prefer repos with coverage.
2. **Prioritize Microsoft repos.** Easy to contribute to, user has SSO auth. Use REST API (`gh api repos/...`) not GraphQL for issue verification — GraphQL triggers SAML prompts.
3. **Verify issues via REST API.** `gh api repos/{owner}/{repo}/issues/{number} --jq '{state, title, pull_request: .pull_request}'`. If `pull_request` is non-null → it's a PR, skip. If `state` != `open` → skip.

## GitHub auth for Microsoft org

The default `gh` CLI OAuth token does NOT have SAML authorization for the Microsoft org (returns 403). Use the `MSFT_SSO` token from `.env`:

```bash
MSFT_TOKEN=$(grep "MSFT_SSO" /mnt/c/Users/Hadoku/Documents/repos/vibedispatch/.env | cut -d'=' -f2 | tr -d '\r\n')
curl -s -H "Authorization: token $MSFT_TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/microsoft/{repo}/pulls/{number}"
```

Or: `GH_TOKEN=$MSFT_TOKEN gh api repos/microsoft/{repo}/issues/{number}`

`HADOKU_SITE_TOKEN` is separate — it won't work for Microsoft org access.

## Dispatching via API

```bash
curl -s -X POST http://localhost:5024/dispatch/api/oss/fork-and-assign \
  -H 'Content-Type: application/json' \
  -d '{
    "origin_owner": "owner",
    "repo": "repo",
    "issue_number": 123,
    "issue_title": "Issue title here",
    "issue_url": "https://github.com/owner/repo/issues/123"
  }'
```

Flow: fork (if needed) → sync → configure settings → push workflows → build context → create issue → assign Copilot → track in assignments.json.

## Context tiers

| Tier | Sources | Quality |
|------|---------|---------|
| 1 | Aggregator issue-brief + dossier | Best — structured repo health, contribution rules, issue analysis |
| 2 | Aggregator dossier only (no brief) | Good — repo context but no issue-specific analysis |
| 3 | `gh issue view` + CONTRIBUTING.md | Minimal — just the raw issue body and contribution guidelines |
