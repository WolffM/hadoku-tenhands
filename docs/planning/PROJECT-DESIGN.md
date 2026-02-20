# OSS Contribution Pipeline — Project Design Document

> This document is the source of truth for the OSS contribution pipeline.
> It is ingested by agents working on hadoku-scrape, hadoku-aggregator, and vibedispatch.
> All three repos should reference this document for contracts, decisions, and integration points.

---

## 1. What We're Building

An automated pipeline that discovers viable open-source issues, analyzes their contribution viability, assigns AI agents to work on them via forked repos, reviews agent output, and submits PRs to upstream maintainers.

**The pipeline answers one question:** "If I assign an agent to this issue right now, what is the probability the resulting PR gets merged?"

## 2. The Vibecheck Analogy

The existing vibecheck pipeline works like this:

```
vibedispatch installs .yml → GitHub Actions runs WolffM/vibecheck → creates issues
vibedispatch reads issues via gh CLI → assigns Copilot → Copilot creates PR
vibedispatch reads PRs → user reviews → user merges
```

The OSS pipeline follows the same pattern but adapted for repos we don't own:

```
hadoku-scrape fetches issue/PR/repo data → writes to Cloudflare KV
hadoku-aggregator reads KV → scores issues, builds dossiers → serves API
vibedispatch reads aggregator API → user selects issues
vibedispatch forks repo → assigns agent on fork → agent creates PR on fork
vibedispatch reviews PR → user submits PR to origin → tracks outcome
```

**Key mapping:**
| vibecheck role | OSS contrib equivalent |
|---|---|
| WolffM/vibecheck GitHub Action (heavy compute) | hadoku-scrape (data collection) + aggregator (analysis) |
| .yml workflow definition in repo | Aggregator's recon pipeline config + API endpoints |
| vibedispatch orchestrating via `gh` CLI | Same — vibedispatch orchestrating via `gh` CLI |

## 3. Key Architecture Decisions

### Decision 1: Three-repo split

**hadoku-scrape** = data collection. Makes external API calls, runs Patchright browser automation, writes raw + normalized data to Cloudflare KV. Already has OSS issues scraper with 6 platform adapters, scoring engine, and KV write. This is an extension, not greenfield.

**hadoku-aggregator** = intelligence + API. Reads scraped data from KV, runs analysis (CVS scoring, repo health, lifecycle classification, comment sentiment), compiles dossiers, and serves results via Hono API. Already has the data provider interface, KV caching, and OpenAPI endpoints.

**vibedispatch** = orchestration + UI. Reads scored data from aggregator API, displays in stage-based UI, and drives the fork→assign→review→submit workflow via `gh` CLI. Already has pipeline store, stage tabs, review queue, and batch operations.

### Decision 2: KV as the integration bus

All data flows through Cloudflare KV. The scraper writes, the aggregator reads. This is the same pattern already working for the basic issue scraper (`cached:{slug}` keys).

**Canonical slug format:** Slugs use hyphenated `{owner}-{repo}` format (e.g., `fastify-fastify`, `pytorch-pytorch`). This matches the existing scraper convention (e.g., `huggingface-transformers`) and avoids `/` in KV keys which would create ambiguous colon-separated key parsing. The `owner` and `repo` fields are stored separately in `RepoMeta` for GitHub API calls. The slug is ONLY used for KV keys, URL path segments, and watchlist entries. All three repos must use the same hyphenated format.

New KV key patterns for recon data (slug = hyphenated):

```
recon:{slug}:issues          → ExtendedIssue[]  (issues with comments, assignees, bodyPreview)
recon:{slug}:merged-prs      → PRSample[]       (10 most recent merged PRs with metadata)
recon:{slug}:rejected-prs    → PRSample[]       (8 most recent rejected PRs)
recon:{slug}:repo-meta       → RepoMeta         (stars, language, license, CONTRIBUTING.md, PR templates)
recon:{slug}:comments        → IssueComments{}  (per-issue comment threads with author roles)
```

The aggregator writes its analysis results to separate keys:

```
recon:{slug}:health          → RepoHealth       (aggregator-computed scores)
recon:{slug}:scored-issues   → ScoredIssue[]    (issues with CVS scores)
recon:{slug}:dossier         → Dossier          (compiled markdown)
recon:{slug}:claims          → ClaimRecord[]    (vibedispatch reports claims here via aggregator API)
recon:watchlist              → string[]          (slugs to analyze)
```

**Watchlist source of truth:** The `recon:watchlist` KV key is the single source of truth.
The scraper's `config/oss_recon.json` is used only as a bootstrap — if the KV key doesn't exist,
the scraper seeds it from config on first run. After that, all additions/removals go through the
aggregator's watchlist API. The config file is NOT re-read or unioned on subsequent runs.

```typescript
interface ClaimRecord {
  issueId: string              // ExtendedIssue.id
  claimedBy: string            // GitHub username
  claimedAt: string            // ISO 8601
  forkIssueUrl: string | null  // URL of the context issue on the fork
}
```

### Decision 3: vibedispatch stays thin

vibedispatch never runs analysis, never scrapes, never clones repos. It calls the aggregator API for scored data and uses `gh` CLI for all GitHub operations. Every action maps to `subprocess.run(["gh", ...])` — the same execution model as vibecheck.

### Decision 4: Aggregator triggers scraper

When a user adds a target repo in vibedispatch, the flow is:

```
vibedispatch → POST aggregator /recon/watchlist/add
aggregator → POST scraper /api/v1/oss-recon/scrape (fire-and-forget)
scraper → fetches data → writes to KV
aggregator → reads from KV → runs analysis → writes scored data to KV
vibedispatch → reads scored data from aggregator API
```

The scraper also runs on a cron schedule to keep data fresh.

### Decision 5: Graceful degradation

If the aggregator is unavailable, vibedispatch can fall back to basic `gh` CLI issue fetching with simple heuristic scoring (label matching, issue age, comment count). This is explicitly NOT the primary path — it's a fallback so the fork→assign→review→submit flow isn't blocked by upstream outages.

---

## 4. Shared Data Contracts

### 4.1 ExtendedIssue (scraper → KV)

Written by scraper to `recon:{slug}:issues`. Extends the existing Issue schema.

```typescript
interface ExtendedIssue {
  // === Existing fields (already scraped by ossissues scraper) ===
  id: string                     // "{platform}-{slug}-{number}"
  platform: Platform
  project: string
  title: string
  url: string
  difficulty: Difficulty
  difficultyScore?: number       // Raw score 0-100 (optional — scraper always produces, but aggregator TS type is optional)
  difficultySignals?: string[]   // Which heuristics matched (optional — defaults to [])
  labels: string[]
  createdAt: string
  updatedAt: string
  author: string

  // === New fields (recon scraper adds these) ===
  authorAssociation: string      // "OWNER" | "MEMBER" | "COLLABORATOR" | "CONTRIBUTOR" | "NONE"
  bodyPreview: string            // First 500 chars of issue body
  commentCount: number
  thumbsUpCount: number          // GitHub reactions: +1 count
  assignees: string[]            // Current assignees
  milestone: string | null
  linkedPrUrls: string[]         // PRs that reference this issue
  lastCommentAt: string | null   // Timestamp of most recent comment
  lastCommentAuthor: string | null
  lastCommentAuthorAssociation: string | null  // "OWNER" | "MEMBER" | "COLLABORATOR" | "CONTRIBUTOR" | "NONE"
}
```

**KV envelope:** The `recon:{slug}:issues` KV value is wrapped in:
```typescript
interface ReconIssueData {
  issues: ExtendedIssue[]
  scrapedAt: string              // ISO timestamp of when the scraper ran
  source: string                 // "hadoku-scraper"
  dataTypes: string[]            // Which data_types were included in this scrape
}
```
This mirrors the existing `CachedIssues` envelope pattern from the basic scraper.
The aggregator uses `scrapedAt` to determine data freshness — if > 24h old, consider stale.

### 4.2 PRSample (scraper → KV)

Written by scraper to `recon:{slug}:merged-prs` and `recon:{slug}:rejected-prs`.

```typescript
interface PRSample {
  number: number
  title: string
  url: string
  author: string
  authorAssociation: string      // "OWNER" | "MEMBER" | "COLLABORATOR" | "CONTRIBUTOR" | "NONE"
  createdAt: string
  mergedAt: string | null
  closedAt: string | null
  additions: number
  deletions: number
  changedFiles: number
  reviewCount: number
  labels: string[]
  headRefName: string            // branch name
  baseRefName: string            // target branch
  mergeCommitSha: string | null
}
```

### 4.3 RepoMeta (scraper → KV)

Written by scraper to `recon:{slug}:repo-meta`.

```typescript
interface RepoMeta {
  owner: string
  repo: string
  slug: string
  stars: number
  forks: number
  language: string | null
  license: string | null
  hasContributing: boolean
  contributingContent: string | null   // Raw CONTRIBUTING.md (truncated to 5000 chars)
  hasPrTemplate: boolean
  prTemplateContent: string | null     // Raw PR template
  hasCodeOfConduct: boolean
  hasCodeowners: boolean
  defaultBranch: string
  isArchived: boolean
  openIssueCount: number
  openPrCount: number
  lastPushedAt: string           // NOTE: GitHub's pushed_at reflects ANY branch push, including bot branches (dependabot, renovate). May appear active for repos with stale main branches. Cross-reference with merged PR dates for true activity signal.
  topics: string[]
  externalTools: string[]            // Detected in M3 via PR comment bot scanning (e.g., ["CodeRabbit", "Codecov", "changeset-bot"])
  scrapedAt: string
}
```

### 4.4 IssueComments (scraper → KV)

Written by scraper to `recon:{slug}:comments`.

```typescript
// NOTE: Keys are stringified issue numbers. Use String(issueNumber) for lookups.
// Object.keys() returns string[], so iterate with: for (const [key, thread] of Object.entries(comments))
type IssueComments = Record<string, CommentThread>

interface CommentThread {
  issueNumber: number           // Numeric issue number (matches the string key when coerced)
  comments: Comment[]
  scrapedAt: string
}

interface Comment {
  author: string
  authorAssociation: string
  body: string              // Truncated to 1000 chars
  createdAt: string
  reactions: {
    thumbsUp: number
    thumbsDown: number
    heart: number
  }
}
```

### 4.5 ScoredIssue (aggregator → KV / API)

Written by aggregator to `recon:{slug}:scored-issues`. Extends ExtendedIssue.

```typescript
interface ScoredIssue extends ExtendedIssue {
  // === Aggregator-computed fields ===
  cvs: number                   // Contribution Viability Score 0-100
  cvsTier: 'go' | 'likely' | 'maybe' | 'risky' | 'skip'
  lifecycleStage: 'fresh' | 'triaged' | 'accepted' | 'stale' | 'zombie'
  claimStatus: 'unclaimed' | 'claimed' | 'stale-claim'
  claimAuthor: string | null
  complexity: 'low' | 'medium' | 'high'
  sentimentScore: number        // -1 to 1
  contentQualityScore: number   // 0-100
  competitionLevel: 'none' | 'low' | 'medium' | 'high'
  repoSlug: string              // Reference to repo for dossier lookup
  dataCompleteness: 'full' | 'partial'  // 'partial' if repo health not yet computed
  repoKilled: boolean           // true if repo hit a kill signal (archived, no merges in 90d)
}
```

**Partial data handling:** If `RepoHealth` is null (M1→M2 transition, scraper hasn't run yet),
the CVS scorer uses `repo_score = 50` (neutral) instead of 0, and sets `dataCompleteness: 'partial'`.
The UI should display a warning badge for partial-data issues.

**Kill signal propagation:** If a repo hits a kill signal (archived, no merged PR in 90 days,
no external contributor PR in 90 days), ALL its issues get `cvs: 0, cvsTier: 'skip', repoKilled: true`.
The `GET /recon/all-scored-issues` endpoint EXCLUDES killed repos by default. Use
`?includeKilled=true` to see them.

### 4.6 RepoHealth (aggregator → KV / API)

Written by aggregator to `recon:{slug}:health`.

```typescript
interface RepoHealth {
  slug: string
  maintainerHealthScore: number       // 0-100
  mergeAccessibilityScore: number     // 0-100
  availabilityScore: number           // 0-100 (higher = more open for new contributors)
  overallViability: number            // 0-100 composite (0 if killed)
  killed: boolean                     // true if repo hit a kill signal (archived, no merges in 90d)
  killReason: string | null           // e.g., "archived", "no_merges_90d", "no_external_merges_90d"
  detectedQuirks: RepoQuirk[]
  prPatterns: PRPatterns
  analyzedAt: string
}

interface RepoQuirk {
  type: string       // 'changeset' | 'conventional-commits' | 'cla' | etc.
  description: string
  impact: 'blocker' | 'important' | 'minor'
  evidence: string   // What we detected (e.g., "Bot comment: 'missing changeset'")
}

interface PRPatterns {
  medianFilesChanged: number
  medianAdditions: number
  medianTimeToMergeDays: number
  mergeStyle: 'squash' | 'merge' | 'rebase' | 'mixed'
  commitConvention: string | null
  externalContributorMergeRate: number   // 0-1
  topRejectionReasons: string[]
}
```

### 4.7 Dossier (aggregator → KV / API)

Written by aggregator to `recon:{slug}:dossier`.

```typescript
interface Dossier {
  slug: string
  generatedAt: string
  sections: {
    overview: string           // Tab label: "Overview" — Repo description, health summary, viability verdict
    contributionRules: string  // Tab label: "Rules" — Parsed CONTRIBUTING.md + detected quirks
    successPatterns: string    // Tab label: "Success" — What merged PRs look like (size, style, review patterns)
    antiPatterns: string       // Tab label: "Anti-Patterns" — What rejected PRs look like + common mistakes
    issueBoard: string         // Tab label: "Issues" — Top 10 scored issues with CVS tiers
    environmentSetup: string   // Tab label: "Setup" — Language, CI tools, test framework, build system
  }
}

// Display label mapping for frontend tab rendering:
// Key: section field name → Value: tab label
const DOSSIER_TAB_LABELS: Record<keyof Dossier['sections'], string> = {
  overview: 'Overview',
  contributionRules: 'Rules',
  successPatterns: 'Success',
  antiPatterns: 'Anti-Patterns',
  issueBoard: 'Issues',
  environmentSetup: 'Setup',
}
```

### 4.8 Aggregator API Endpoints

These are what vibedispatch calls. All paths are relative to the aggregator base URL
(e.g., `https://hadoku.me/oss/api`). vibedispatch config stores the base URL and
appends these paths — do NOT duplicate the `/oss/api` prefix.

```
GET  /recon/watchlist                → { slugs: string[] }
POST /recon/watchlist/add            → { slug: string }
POST /recon/watchlist/remove         → { slug: string }
GET  /recon/{slug}/health            → RepoHealth
GET  /recon/{slug}/issues            → ExtendedIssue[]  (raw unscored — for debugging / fallback display)
GET  /recon/{slug}/scored-issues     → ScoredIssue[]
GET  /recon/{slug}/dossier           → Dossier
GET  /recon/all-scored-issues        → ScoredIssue[]  (across all watchlist repos, sorted by CVS, excludes killed repos)
GET  /recon/all-scored-issues?includeKilled=true  → ScoredIssue[]  (includes killed repos)
POST /recon/{slug}/refresh           → { status: "triggered" }  (tells scraper to re-scrape)
POST /recon/{slug}/claim             → { issueId: string, claimedBy: string }  (vibedispatch reports a claim)
POST /recon/{slug}/unclaim           → { issueId: string }
```

**Claim endpoint contract:** When vibedispatch forks a repo and assigns an agent (Stage 3),
it calls `POST /recon/{slug}/claim` to report the claim back to the aggregator. The aggregator
writes claim data to `recon:{slug}:claims` KV key. Future scoring reads this to set `claimStatus`
and `claimAuthor` on ScoredIssue, preventing other users from competing on the same issue.
If a submitted PR is closed/rejected, vibedispatch calls `POST /recon/{slug}/unclaim`.

**Claim concurrency note:** Cloudflare KV has no atomic read-modify-write. The current
implementation uses last-write-wins on the claims array. This is acceptable for single-user
deployment (one vibedispatch instance). If multi-user support is needed later, migrate
claims to Durable Objects or add CAS (compare-and-swap) via KV metadata.

### 4.9 Scraper API Endpoints (called by aggregator)

```
POST /api/v1/oss-recon/scrape               → { slug, data_types?: ["issues", "prs", "meta", "comments"] }
                                                (data_types is optional, defaults to ["issues"])
POST /api/v1/oss-recon/scrape-all           → { slugs: string[] }  (batch scrape, 202 Accepted)
GET  /api/v1/oss-recon/status                → { last_run, status }
GET  /api/v1/oss-recon/status/{slug}         → { slug, last_run, status, data_types_completed }
```

---

## 5. Milestone Plan

### Milestone 0: Contracts (this document)

**Duration:** 0 days (this document IS the milestone)
**Deliverable:** This document + per-repo requirements
**Validates:** All three agents agree on KV schemas, API endpoints, and data flow

---

### Milestone 1: Foundation (parallel across all three repos)

**Duration:** 3-5 days
**All three agents can work simultaneously. No cross-repo dependencies.**

| Agent | Repo | Work | Validates |
|---|---|---|---|
| A | hadoku-scrape | Extend `GitHubFetcher` to return ExtendedIssue fields (commentCount, assignees, bodyPreview, thumbsUpCount, linkedPrUrls, lastCommentAt). Write to `recon:{slug}:issues` KV key. | `POST /api/v1/oss-recon/scrape` with `data_types: ["issues"]` returns extended data. Manual KV inspection shows new fields. |
| B | hadoku-aggregator | Create `recon/` module with KV reader. Build `/oss/api/recon/watchlist` CRUD endpoints and `/oss/api/recon/{slug}/health` stub (returns raw repo metadata, no scoring yet). Read from `recon:*` KV keys. | `GET /oss/api/recon/watchlist` returns slug list. `GET /oss/api/recon/{slug}/health` returns data (even if scoring is just pass-through of scraper data). |
| C | vibedispatch | Build OSS target management: `oss_routes.py` (CRUD for targets), `pipelineStore.ts` extension (ossStage1-5 data), OSS types in `types.ts`, `OSSView.tsx` with StageTabView shell. Build Stage 3-5 flow: fork-and-assign, review-on-fork, submit-to-origin. These are pure `gh` CLI — no aggregator dependency. | User can add a target repo. Fork & assign flow works end-to-end manually (hardcoded issue). PR review on fork works. Submit to origin works. |

**M1 Validation gate:** Each repo's work can be tested independently. No cross-repo integration needed yet.

---

### Milestone 2: Data Pipeline (scraper leads, aggregator follows)

**Duration:** 4-6 days
**Scraper agent works first (2-3 days), then aggregator agent consumes the data.**

| Agent | Repo | Work | Depends On | Validates |
|---|---|---|---|---|
| A | hadoku-scrape | Add PR scraping (merged + rejected samples via GitHub API). Add repo metadata scraping (CONTRIBUTING.md, PR templates, CODEOWNERS, default branch). Add comment thread scraping (top 20 issues). Write to `recon:{slug}:merged-prs`, `recon:{slug}:rejected-prs`, `recon:{slug}:repo-meta`, `recon:{slug}:comments`. | Nothing — can start immediately | KV keys populated for a test repo. PR samples have correct fields. CONTRIBUTING.md content retrieved. Comment threads have author associations. |
| B | hadoku-aggregator | Build analysis engine: repo health scorer (reads `repo-meta` + `merged-prs` + `rejected-prs`), issue lifecycle classifier (reads `issues` + `comments`), CVS scorer (composite of all signals). Write results to `recon:{slug}:health` and `recon:{slug}:scored-issues`. Expose via API. | Scraper has written `recon:*` data to KV | `GET /recon/{slug}/health` returns computed scores. `GET /recon/{slug}/scored-issues` returns CVS-scored issues sorted by viability. |
| C | vibedispatch | Build Stage 1 (Target Repos) UI that reads from aggregator API. Build Stage 2 (Select Issues) UI that displays scored issues. Wire target add/remove to aggregator watchlist endpoints. Add fallback scoring via `gh` CLI for when aggregator is down. | Aggregator M2 API endpoints available (can use mock data initially) | User adds target → sees health scores. User browses scored issues → can select for work. Selected issue flows into Stage 3 fork-and-assign. |

**M2 Validation gate:** End-to-end flow works: add target → see scored issues → select → fork → assign → review → submit. Aggregator provides real scores from scraper data.

**Parallelism note:** Agent C can build Stage 1-2 UI with mock data while waiting for Agent B. Agent B can build analysis engine with test fixtures while waiting for Agent A's KV data. The bottleneck is only at integration testing.

---

### Milestone 3: Intelligence (aggregator + scraper enhancements)

**Duration:** 5-7 days
**Aggregator and scraper agents work in parallel. vibedispatch agent polishes.**

| Agent | Repo | Work | Depends On | Validates |
|---|---|---|---|---|
| A | hadoku-scrape | Add Patchright-based scraping for data not available via API (external tool detection in PR comments, vibe-coder pattern detection). Add comment sentiment keyword extraction. Add cron schedule for periodic re-scraping. | M2 complete | Scraper detects CodeRabbit, Codecov, changeset bots in PR comments. Cron runs every 6 hours. |
| B | hadoku-aggregator | Build dossier compiler (6-section markdown generation). Add comment sentiment analysis (pattern matching). Add quirk detection (changesets, CLA, conventional commits). Enhance CVS scoring with all M3 signals. | M2 complete | `GET /recon/{slug}/dossier` returns complete markdown dossier. Quirks appear in health endpoint. CVS scores meaningfully differentiate issues. |
| C | vibedispatch | Add dossier viewer panel in Stage 2 + 3. Add outcome tracking (poll submitted PRs for merge/reject status). Add notifications (Discord webhook on GO-tier issue found, PR merged). Polish batch operations. | M3 aggregator dossier endpoint | User can view dossier before selecting issues. Submitted PRs show live status. Discord notification fires on merge. |

**M3 Validation gate:** Full intelligence pipeline works. Dossiers are useful. CVS scoring differentiates viable from non-viable issues. Agent context includes contribution rules. Outcome tracking closes the loop.

---

### Milestone 4: Discovery (stretch goal)

**Duration:** 3-5 days
**Scraper adds automated repo discovery. Aggregator evaluates. vibedispatch displays.**

| Agent | Repo | Work |
|---|---|---|
| A | hadoku-scrape | GitHub trending scraper (Patchright). GitHub search API scraper (parameterized queries). Awesome list parser. |
| B | hadoku-aggregator | Auto-evaluate discovered repos against health criteria. Auto-add to watchlist if viability > threshold. |
| C | vibedispatch | Discovery feed in Stage 1 showing auto-discovered repos with accept/reject buttons. |

---

## 6. Parallel Work Strategy

```
Week 1:
  Agent A (scraper):    [M1: extend issue fields] ──────────────▶ [M2: PR + meta + comments]
  Agent B (aggregator): [M1: KV reader + API stubs] ────────────▶ [M2: analysis engine (can use fixtures)]
  Agent C (vibedispatch):[M1: target CRUD + fork/assign/review/submit flow] ──────────────────────────▶

Week 2:
  Agent A (scraper):    [M2: continued] ────▶ [M3: Patchright + cron]
  Agent B (aggregator): [M2: scoring, needs KV data] ──▶ [M3: dossiers + quirks]
  Agent C (vibedispatch):[M2: Stage 1-2 UI, can mock aggregator] ──▶ [M3: dossier viewer + tracking]

Week 3:
  All agents:           [Integration testing] ──▶ [M3 polish] ──▶ [M4 if time]
```

**Blocking dependencies (agents must wait):**

| Blocker | Who waits | What for |
|---|---|---|
| `recon:{slug}:issues` in KV | Aggregator M2 analysis | Scraper M1 must write extended issues to KV |
| `recon:{slug}:merged-prs` + `rejected-prs` + `repo-meta` in KV | Aggregator M2 health scoring | Scraper M2 must write PR + meta data to KV |
| Aggregator M2 API endpoints | vibedispatch M2 Stage 1-2 UI | Aggregator must serve `/recon/watchlist` and `/recon/{slug}/scored-issues` |

**Non-blocking (agents can proceed independently):**

- vibedispatch Stages 3-5 (fork, review, submit) → pure `gh` CLI, zero aggregator dependency
- Aggregator M1 API stubs → can return mock data
- Scraper M1 extended issues → works against existing config, no new infra
- vibedispatch M2 UI → can mock aggregator responses

---

## 7. Testing Strategy

### Per-Repo Unit Tests

Each repo tests its own logic in isolation:

- **Scraper:** Mock httpx responses, verify normalization to ExtendedIssue schema, verify KV write payloads
- **Aggregator:** Mock KV reads, verify scoring math, verify dossier template output
- **vibedispatch:** Mock aggregator API responses, verify pipeline item mapping, verify `gh` CLI command construction

### Integration Tests (per milestone)

| Test | What it validates | How to run |
|---|---|---|
| Scraper → KV | Extended data lands in KV with correct schemas | Scraper dry-run + KV inspection |
| KV → Aggregator | Aggregator reads and scores correctly | Seed KV with test data, call aggregator API |
| Aggregator → vibedispatch | vibedispatch displays scored data | Call aggregator API from vibedispatch backend |
| vibedispatch → GitHub | Fork/assign/review/submit flow works | Manual E2E against a test repo |

### E2E Validation (M2+ gate)

```bash
# 1. Trigger scraper for a test repo (slug is hyphenated; data_types defaults to ["issues"])
curl -X POST scraper/api/v1/oss-recon/scrape -d '{"slug": "fastify-fastify"}'
# Full scrape (all data types):
# curl -X POST ... -d '{"slug": "fastify-fastify", "data_types": ["issues", "prs", "meta", "comments"]}'

# 2. Poll per-slug status until complete
curl scraper/api/v1/oss-recon/status/fastify-fastify | jq '.status'

# 3. Check aggregator (base URL + relative path)
curl https://hadoku.me/oss/api/recon/fastify-fastify/scored-issues | jq '.[0].cvs'

# 4. Verify vibedispatch can read it
curl vibedispatch/api/oss/stage2-issues | jq '.issues[0].cvs'

# 5. Test fork-and-assign manually
curl -X POST vibedispatch/api/oss/fork-and-assign \
  -d '{"origin_owner":"fastify","repo":"fastify","issue_number":5432}'
```
