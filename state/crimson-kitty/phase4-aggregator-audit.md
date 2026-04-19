# Aggregator audit — Phase 4 targets

Sampled payloads from `/recon/{slug}/{endpoint}` across 4 targets (jestjs/jest,
microsoft/TypeScript, sharkdp/bat, supabase/supabase, huggingface/transformers)
plus probes on the full 20-target list. Endpoints tested:
`dossier`, `health`, `issue-brief/{id}`, `contributing`, `pr-template`.

## Working well

| Area | Finding |
|---|---|
| Envelope consistency | All endpoints return `{success, data, _meta{scraped_at, computed_at, served_at}}` — clean. |
| `dossier.sections` | Structured: `overview`, `contributionRules`, `prPatterns` — rich enough for context. |
| `health.prPatterns` | Real signal: `medianFilesChanged`, `externalContributorMergeRate`, `medianTimeToMergeDays`. |
| `pr-template.sections` | Parsed into `{heading, required, placeholder}` — renderer-friendly. |
| `issue-brief.brief` | Already embeds CRITICAL RULES for the agent ("DO NOT use GitHub MCP tools", "DO NOT add Closes/Fixes"). Excellent. |
| Scrubber vs brief | Residual `https://github.com/{slug}/issues/{n}` URL in the brief is caught by `scrub_brief`; 0 leaks in test. |

## Critical bugs — file against aggregator

### A1 — `/issue-brief/{id}` breaks on hyphenated-owner slugs

`GET /recon/oven-sh-bun/issue-brief/github-oven-sh-bun-14522` → `success: false, error: "issue not found"`
`GET /recon/oven-sh-bun/health` → `success: true` (slug parses fine on other endpoints)

The issue-ID format `github-{owner}-{repo}-{n}` becomes ambiguous when
the owner slug contains a hyphen. Parser splits naively on `-` and
mis-attributes the segments.

**Affects Phase 4 pick #9** (oven-sh/bun #14522) — eligibility would
fail immediately.

**Proposed fix (aggregator)**: change the ID separator, OR switch the
endpoint to accept `?issue_number=N` query param, OR quote the slug
(`github-{owner%2Frepo}-{n}`). Any delimiter that can't collide with
existing slug contents works.

### A2 — `ai_policy: "unknown"` on every repo

Every one of the audit samples returns `ai_policy: "unknown"` despite
the field being present in the response. The aggregator isn't scanning
CONTRIBUTING.md for AI/LLM/Copilot-disclosure clauses.

**Phase 4 risk**: we'd open PRs on repos that explicitly prohibit
AI-generated code, triggering maintainer pushback and potentially
damaging WolffM's reputation.

**Proposed fix**: regex scan of CONTRIBUTING.md + AGENTS.md + PR
template for phrases like `AI-generated`, `LLM`, `Copilot`, `ChatGPT`,
`generated code`, `disclose`. Map to one of
`{allowed, disclose_required, prohibited, unknown}`.

### A3 — `killed: false` on a wound-down repo

`microsoft/TypeScript`'s CONTRIBUTING.md literally says *"Development
in this codebase is winding down and PRs will only be merged if they
fix critical 6.0 issues"*. Aggregator returns `killed: false`,
`overallViability: 84`.

If we dispatched to TypeScript, the PR would be closed on sight.

**Proposed fix**: add kill-reason detection for phrases like
"winding down", "maintenance mode", "see {other-repo}", "archived",
"frozen for X release". Either flip `killed` or add a `detectedQuirks`
entry with `impact: blocking`.

### A4 — `AGENTS.md` not fetched

MS TypeScript's CONTRIBUTING.md contains:
```
<!-- CODING AGENTS: READ AGENTS.md BEFORE WRITING CODE -->
```

Some repos publish an AGENTS.md specifically for LLM/agent contributors.
Aggregator doesn't fetch or serve it.

**Proposed fix**: add `GET /recon/{slug}/agents-md` that returns
`{exists, raw_text, directives}` — parsed directives like "run X before
submitting", "never touch files in Y/".

## Moderate gaps

### M1 — `likelyFiles` coverage inconsistent

Across 4 probes: jest=2 files, eslint=0, TanStack/query=0, bun=errored.
Field exists in the schema but is reliably populated only for some repos.

**Impact**: we're losing a valuable scope hint we could pass to Copilot.
When empty, fall back to current behavior; when populated, feed into
the agent context.

**Proposed fix (aggregator)**: widen the heuristic (stack traces in
issue body, file paths in code blocks, file paths in comments,
maintainer-suggested files in lastComment).

### M2 — Rich signals populated but never consumed by vibedispatch

`issue-brief.issue` includes all of these, none of which the pipeline
reads:
- `likelyFiles`
- `detectedQuirks` (from repoHealth)
- `commentDigest`
- `sentimentSignals`
- `relatedIssues`
- `competitionLevel`
- `contentQualityScore`

**Impact**: aggregator is paying to compute these; we're ignoring them.

**Proposed fix (vibedispatch)**: extend `fork_and_scrub_brief` to
append a "Context hints" section after the scrubbed brief, passing
through `likelyFiles`, `detectedQuirks`, and top-2 `relatedIssues` (if
any). Keep them under "hints" so Copilot treats them as optional scope.

## Minor / cleanup

### m1 — Scrubber-prone fields

The aggregator embeds `Issue: https://github.com/{slug}/issues/{n}`
directly into the brief text. Our scrubber catches it fine, but it'd
be cleaner to have a separate `issue_url` field in the JSON and let
us compose or omit it ourselves. Scrubbing ad-hoc strings is always
more fragile than structured data.

### m2 — `repoHealth` duplicated inside `issue-brief`

The issue-brief response includes the full `repoHealth` object, but we
separately fetch `/recon/{slug}/health`. Redundant. Could drop one call
from the eligibility activity.

## Action matrix

| # | Change | Side | Priority |
|---|---|---|---|
| A1 | Fix issue-brief slug hyphen collision | aggregator | **Blocker** — pick #9 affected |
| A2 | Populate `ai_policy` via regex scan | aggregator | **Blocker** for external-upstream safety |
| A3 | Detect wound-down repos; flip `killed` or add quirk | aggregator | **Blocker** — pick #5 (TypeScript) affected |
| A4 | Serve AGENTS.md | aggregator | High — agent-specific directives |
| M1 | Improve `likelyFiles` coverage | aggregator | Medium |
| M2 | Consume `likelyFiles` + `detectedQuirks` in vibedispatch | vibedispatch | Medium |
| m1 | Move embedded issue URL out of brief text | aggregator | Low |
| m2 | Drop duplicate `/health` fetch when we already have it from brief | vibedispatch | Low |

## What this means for the Phase 4 20-target list

- **Pick #5 (microsoft/TypeScript #283)** — drop until A3 is fixed. Repo is effectively read-only.
- **Pick #9 (oven-sh/bun #14522)** — drop until A1 is fixed. Eligibility endpoint errors.
- **Remaining 18** are audit-clean — briefs populate, scrubber works, metadata is usable (even if some fields are under-populated).

**Recommendation**: cut 18 from the 20, or swap in 2 replacements from the top-30 shortlist so we hold at 20. Tickets A1/A2/A3/A4 get filed against the aggregator team in parallel.
