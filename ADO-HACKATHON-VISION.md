# ADO Hackathon Vision: Intelligent Work Item Triage for Azure DevOps

## Goal

Fork the vibedispatch + hadoku-aggregator pipeline and rewire it to work with Azure DevOps repos and work items instead of GitHub. Deliver a localhost proof-of-concept that scores ADO work items using the existing CVS engine and displays them in the triage dashboard.

## Scope

**In scope:** Stages 1-2 (reconnaissance + scoring + dashboard UI)
**Out of scope:** Stages 3-5 (fork/agent/review/submit — no Copilot agent equivalent on ADO)

## Architecture

```
ado-scraper (new, Python)                    ← YOU BUILD THIS
  → hits ADO REST API, writes ConsolidatedReconData to local JSON files

hadoku-aggregator (forked, TypeScript)       ← PATCH ~5 SPOTS
  → reads local JSON (instead of KV), runs CVS scoring engine as-is
  → serves scored data via Hono API on localhost

vibedispatch (forked, Python + React)        ← SWAP READ PATHS
  → calls aggregator API for scored data (no changes needed here)
  → swap gh CLI calls in Stage 1-2 routes for az devops CLI or remove them
  → dashboard UI works as-is with minor label tweaks
```

---

## Milestones

### M0: Fork and Scaffold (30 min)

- [ ] Fork vibedispatch → `vibedispatch-ado`
- [ ] Fork hadoku-aggregator → `hadoku-aggregator-ado`
- [ ] Create `ado-scraper/` directory (new project, Python)
- [ ] Pick 2-3 ADO repos with active work items as test targets
- [ ] Confirm `az devops` CLI is authenticated and working (`az boards work-item show --id <any>`)

**Test:** `az devops invoke` returns data for your target org/project.

---

### M1: ADO Scraper — Work Items + PR Metadata (3-4 hours)

Build a Python script that hits the ADO REST API and outputs a `ConsolidatedReconData` JSON file per repo, matching the shape the aggregator expects.

#### M1a: Work Item Fetcher (1.5 hours)

- [ ] Query work items via WIQL: `SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project AND [System.WorkItemType] IN ('Bug', 'Task', 'User Story') AND [System.State] <> 'Closed'`
- [ ] For each work item, fetch detail via `GET /_apis/wit/workitems/{id}?$expand=relations`
- [ ] Map to `ExtendedIssue` shape:

```
ADO Field                    → ExtendedIssue Field
─────────────────────────────────────────────────────
System.Id                    → id (as "ado-{org}-{project}-{id}")
System.Title                 → title
System.Description (HTML)    → body (strip HTML tags)
System.WorkItemType          → labels[0]
System.State                 → labels[1] (or use for lifecycle hints)
System.Tags                  → labels (split on ";")
System.CreatedDate           → createdAt
System.ChangedDate           → updatedAt
System.CreatedBy             → author
System.AssignedTo            → assignees
Microsoft.VSTS.Common.Priority → difficultySignals
System.IterationPath         → milestone
Work item URL                → url
Comment count (from API)     → commentCount
```

- [ ] Set `platform: "ado"`, `authorAssociation: "NONE"` for now (revisit in M3)
- [ ] Set `reactionGroups: []` (ADO has no emoji reactions)
- [ ] Set `linkedPrUrls` from work item relations where `rel === "ArtifactLink"` and URL contains `/pullRequest/`

**Test:** Run scraper, inspect output JSON. Every work item has an `id`, `title`, `url`, `createdAt`. File parses cleanly.

#### M1b: PR Metadata Fetcher (1 hour)

- [ ] Fetch completed PRs: `GET /{project}/_apis/git/repositories/{repo}/pullrequests?searchCriteria.status=completed&$top=100`
- [ ] Fetch abandoned PRs: same with `status=abandoned`
- [ ] Map to `PRSample` shape:

```
ADO Field                    → PRSample Field
─────────────────────────────────────────────────────
pullRequestId                → number
title                        → title
createdBy.uniqueName         → author
creationDate                 → createdAt
closedDate                   → mergedAt / closedAt
targetRefName                → baseRefName
sourceRefName                → headRefName
reviewers[].vote             → derive review engagement
```

- [ ] Fetch repo metadata: `GET /_apis/git/repositories/{repo}` → map to `RepoMeta` (name, default branch, URL)

**Test:** Output JSON has `mergedPrs` and `rejectedPrs` arrays populated. Dates parse correctly.

#### M1c: Comment Fetcher (30 min)

- [ ] For each work item: `GET /_apis/wit/workitems/{id}/comments`
- [ ] Map to `IssueComments` shape (keyed by work item ID string):

```
ADO Field                    → Comment Field
─────────────────────────────────────────────────────
comment.text (HTML)          → body (strip HTML)
comment.createdBy            → author
comment.createdDate          → createdAt
```

**Test:** `comments.threads` in output JSON is populated. At least one work item has comments.

#### M1d: Assemble and Write (30 min)

- [ ] Combine into `ConsolidatedReconData` envelope with `scrapedAt`, `platform: "ado"`, `dataTypes`, etc.
- [ ] Write to a local JSON file: `output/{org}-{project}.json`
- [ ] Add a simple CLI: `python ado_scraper.py --org myorg --project myproject`

**Test:** End-to-end run produces valid JSON. Diff against a real `recon:{slug}` dump from the GitHub pipeline to eyeball structural parity.

---

### M2: Aggregator — Local Mode + ADO Patches (2-3 hours)

#### M2a: Local File Reader (1 hour)

The aggregator reads from Cloudflare KV. For localhost, bypass KV and read from local JSON files.

- [ ] Add a `LocalKVAdapter` class that implements the same `get(key)` / `put(key, value)` / `list()` interface as `KVNamespace` but reads/writes from a local `data/` directory
- [ ] Wire it into the Hono app as an alternative to the real KV binding
- [ ] Scraper output files go into `data/recon/` directory, named to match the key pattern (`{slug}.json`, `{slug}.health.json`, etc.)

**Test:** Start the aggregator locally, call `POST /oss/api/recon/{slug}/compute`, verify it reads the scraper output and doesn't crash.

#### M2b: Platform Patches (1 hour)

- [ ] Add `'ado'` to the `Platform` type in `api/types.ts`
- [ ] Update `isMaintainer()` in `api/recon/utils.ts` — for now, return `false` for ADO (no role mapping yet). This is safe because maintainer weighting is a bonus, not a requirement
- [ ] In `issue-scorer.ts`: handle empty `reactionGroups` gracefully (reactions contribute ±15 to CVS — with no reactions, this term is just 0)
- [ ] In `dossier-compiler.ts` and `issue-brief.ts`: make GitHub URL templates conditional on `platform`
- [ ] In `comment-digest.ts`: add ADO work item URL regex alongside the GitHub one

**Test:** Run `POST /oss/api/recon/{slug}/compute` with ADO scraper data. Check:
- `GET /oss/api/recon/{slug}/scored-issues` returns scored work items with CVS values
- `GET /oss/api/recon/{slug}/health` returns repo health scores
- `GET /oss/api/recon/{slug}/dossier` returns a dossier (may be sparse, that's fine)
- No crashes, no NaN scores, no undefined fields

#### M2c: Smoke Test the Scoring (30 min)

- [ ] Compare CVS scores against gut feeling. Do high-priority bugs with recent activity score higher than stale low-priority tasks?
- [ ] Check lifecycle classification — do new work items get `fresh`, old ones get `stale`?
- [ ] Verify the `/all-scored-issues` aggregate endpoint works

**Test:** Scores are reasonable. The ranking roughly matches what a human would prioritize.

---

### M3: vibedispatch — Dashboard Shows ADO Data (2-3 hours)

#### M3a: Point at Local Aggregator (15 min)

- [ ] Update the aggregator base URL in vibedispatch config to `http://localhost:{port}/oss/api`
- [ ] Verify the Flask backend can reach the aggregator

**Test:** `GET /dispatch/api/oss/scored-issues` returns data from the local aggregator.

#### M3b: Gut Stage 1-2 of GitHub Calls (1.5 hours)

Stage 1 (Target Repos) and Stage 2 (Scored Issues) have some `gh` CLI calls as fallbacks. Disable or swap them:

- [ ] In `oss_service.py`: the primary path already calls the aggregator API — verify the fallback code paths don't fire when the aggregator is reachable
- [ ] In Stage 1 routes: remove or stub `get_repo_context()` calls that use `gh` — replace with aggregator's `/all-scored-issues/version` for repo list
- [ ] In Stage 2 routes: verify scored issues come entirely from aggregator (they should already)

**Test:** Dashboard loads. Target Repos tab shows ADO repos. Scored Issues tab shows scored work items with CVS tiers.

#### M3c: UI Label Tweaks (1 hour)

- [ ] "Issues" → "Work Items" in display labels
- [ ] "PRs" → "Pull Requests" (ADO terminology)
- [ ] "Fork & Assign" tab → hide or grey out with "Not available for ADO"
- [ ] URLs in the UI should link to ADO work item pages (they will if the scraper set `url` correctly)
- [ ] Issue ID display: `#123` still works, just links to ADO

**Test:** Visual check. Dashboard looks coherent with ADO terminology. Clicking a work item URL opens the correct ADO page.

#### M3d: Stub Out Stages 3-5 (30 min)

- [ ] Stage 3 (Fork & Assign): return a clear "not supported for ADO" message from the API
- [ ] Stage 4-5: same treatment
- [ ] UI tabs for these stages: show as disabled or with a "coming soon" banner

**Test:** Clicking disabled stages doesn't crash. No `gh` CLI errors in the console.

---

### M4: End-to-End Demo Run (1 hour)

- [ ] Run the full pipeline end-to-end:
  1. `python ado_scraper.py --org myorg --project myproject` → writes JSON
  2. Start aggregator: `pnpm dev` → reads JSON, serves API
  3. Trigger compute: `curl -X POST localhost:{port}/oss/api/recon/{slug}/compute`
  4. Start vibedispatch: `pnpm dev` + `python app.py` → dashboard loads
  5. Browse dashboard: repos visible, work items scored, dossier loads, issue brief loads
- [ ] Screenshot the demo
- [ ] Note any rough edges for the presentation

**Test:** The whole thing works without touching GitHub at all. No `gh` CLI calls, no GitHub tokens needed.

---

## Milestone Summary

| Milestone | What | Time Estimate | Dependency |
|---|---|---|---|
| M0 | Fork + scaffold | 30 min | — |
| M1 | ADO scraper | 3-4 hours | M0 |
| M2 | Aggregator local mode + patches | 2-3 hours | M0 (can start in parallel with M1) |
| M3 | vibedispatch dashboard | 2-3 hours | M1 + M2 |
| M4 | End-to-end demo | 1 hour | M3 |

**Total: ~9-11 hours of focused work.** Fits in a 2-day hackathon with room for debugging and polish.

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| ADO API rate limits or auth issues | Blocks M1 | Use PAT auth, test with small project first, cache responses |
| ADO work items have HTML bodies not markdown | Garbled scoring signals | Strip HTML in scraper (use `html2text` or regex), good enough for hackathon |
| CVS scores are nonsensical for ADO data | Demo looks broken | Manually verify with 2-3 known work items, tune weights if needed |
| Aggregator LocalKV adapter is annoying to build | Blocks M2 | Alternative: just load JSON directly in a modified `computeAndStore()`, skip the KV interface entirely |
| `gh` CLI calls leak through in vibedispatch | Crashes at runtime | Grep for `run_gh_command` in Stage 1-2 code paths, stub any that fire |

## What This Proves (Hackathon Narrative)

"We took an existing open-source contribution intelligence platform and made it work with Azure DevOps in under 2 days. The same CVS scoring engine that identifies high-value GitHub issues now triages ADO work items — same math, different data source. The pipeline architecture (scraper → aggregator → orchestrator) is platform-agnostic by design. Adding agent automation (Stages 3-5) for ADO is future work pending an ADO-compatible coding agent."
