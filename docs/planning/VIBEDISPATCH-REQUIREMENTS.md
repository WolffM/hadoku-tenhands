# vibedispatch — OSS Contrib Requirements

> Read PROJECT-DESIGN.md first for full context, shared contracts, and milestone plan.

## Role in the Pipeline

vibedispatch is the **orchestration + UI layer**. It reads scored data from the aggregator API, displays it in a stage-based UI, and drives the fork→assign→review→submit workflow via `gh` CLI. It never runs analysis, never scrapes, never clones repos.

**Analogy:** vibedispatch does the same thing for OSS contrib as it does for vibecheck — it reads results from an external source and drives a multi-stage human workflow via `gh` CLI calls. The only difference is the stages and the fork-based topology.

## What Already Exists

- `backend/routes/pipeline_routes.py` — Stage 1-4 endpoints for vibecheck
- `backend/routes/action_routes.py` — PR/issue actions (assign Copilot, approve, merge)
- `backend/services/github_api.py` — `run_gh_command()` wrapper, `get_repo_issues()`, `get_repo_prs()`, `get_authenticated_user()`
- `backend/services/cache.py` — File-based caching with `@cached_endpoint` decorator
- `frontend/src/store/pipelineStore.ts` — Zustand store with `createStageLoader`, `registerPipelineItemProvider`, `refreshPipelineItems`
- `frontend/src/views/` — Stage-based views
- `frontend/src/components/` — ReviewQueueShell, DiffViewer, batch action hooks
- `frontend/src/api/types.ts` — PipelineItem, Issue, PullRequest types
- `frontend/src/api/endpoints.ts` — API endpoint functions

## What to Build

### 5-Stage OSS Pipeline

```
Stage 1: Target Repos     — Add/remove repos to track (reads aggregator watchlist)
Stage 2: Select Issues    — Browse scored issues, select for work (reads aggregator scored-issues)
Stage 3: Fork & Assign    — Fork repo, create context issue, assign agent (gh CLI)
Stage 4: Review on Fork   — Review agent's PR on your fork (gh CLI, reuses ReviewQueueShell)
Stage 5: Submit Upstream   — Submit PR from fork to origin repo (gh CLI)
```

Stages 1-2 depend on the aggregator API. **Stages 3-5 are pure `gh` CLI — no aggregator dependency.**

### File Structure

```
backend/
  routes/
    oss_routes.py              ← NEW: all OSS stage endpoints + actions
  services/
    oss_service.py             ← NEW: aggregator API client, fork management, agent context builder
  helpers/
    oss_helpers.py             ← NEW: scoring fallback, PR template formatting

frontend/
  src/
    api/
      endpoints.ts             ← ADD: OSS endpoint functions
      types.ts                 ← ADD: OSS types (OSSTarget, ScoredIssue, ForkPR, etc.)
    store/
      pipelineStore.ts         ← ADD: OSS stage data + loaders + item mapper
    components/
      oss/
        OSSTargetList.tsx      ← NEW: Stage 1 — target repo list
        OSSIssueList.tsx       ← NEW: Stage 2 — scored issues with filters
        OSSAssignPanel.tsx     ← NEW: Stage 3 — fork & assign controls
        OSSReviewPanel.tsx     ← NEW: Stage 4 — wraps ReviewQueueShell
        OSSSubmitPanel.tsx     ← NEW: Stage 5 — submit to origin with PR editor
        OSSDossierPanel.tsx    ← NEW: Side panel for dossier markdown
    views/
      OSSView.tsx              ← NEW: StageTabView with 5 stages
```

---

## Milestone 1: Stages 3-5 + Scaffolding

**Duration:** 3-5 days
**Dependencies:** None — Stages 3-5 are pure `gh` CLI, no aggregator needed
**Parallel with:** Scraper M1, Aggregator M1

### What to Build

#### Backend

1. **`oss_routes.py`** — All OSS routes

   ```python
   # Stage 1: Target management (aggregator proxy + local tracking)
   GET  /api/oss/stage1-targets        → proxy to aggregator /recon/watchlist + enrich with gh CLI
   POST /api/oss/add-target            → proxy to aggregator /recon/watchlist/add
   POST /api/oss/remove-target         → proxy to aggregator /recon/watchlist/remove
   POST /api/oss/refresh-target        → proxy to aggregator /recon/{slug}/refresh

   # Stage 2: Scored issues (aggregator proxy)
   GET  /api/oss/stage2-issues         → proxy to aggregator /recon/all-scored-issues
   GET  /api/oss/dossier/{slug}        → proxy to aggregator /recon/{slug}/dossier

   # Stage 3: Fork & assign (gh CLI — no aggregator)
   GET  /api/oss/stage3-assigned       → read from local JSON tracking
   POST /api/oss/fork-and-assign       → fork repo + create context issue + assign Copilot
   POST /api/oss/select-issue          → mark issue as selected (local JSON, dedup by origin_slug+issue_number)

   # Stage 4: Review on fork (gh CLI — no aggregator)
   GET  /api/oss/stage4-fork-prs       → gh pr list on forked repos
   POST /api/oss/fork-pr-details       → gh pr view on fork
   POST /api/oss/approve-fork-pr       → gh pr review --approve on fork
   POST /api/oss/merge-fork-pr         → gh pr merge on fork

   # Stage 5: Submit upstream (gh CLI — no aggregator)
   GET  /api/oss/stage5-submit         → read from ready-to-submit.json (populated by merge-fork-pr)
   POST /api/oss/submit-to-origin      → gh pr create -R origin
   GET  /api/oss/stage5-tracking       → poll submitted PR status from submitted-prs.json
   ```

2. **`oss_service.py`** — Core service logic

   ```python
   class OSSService:
       """Service layer for OSS contribution pipeline."""

       def __init__(self, aggregator_url: str | None = None):
           self.aggregator_url = aggregator_url or os.environ.get("AGGREGATOR_API_URL")
           self.data_dir = os.path.join(CACHE_DIR, "oss")

       # === Aggregator API client ===
       def get_watchlist(self) -> list[str]: ...
       def add_to_watchlist(self, slug: str) -> bool: ...
       def remove_from_watchlist(self, slug: str) -> bool: ...
       def get_scored_issues(self, slug: str = None) -> list[dict]: ...
       def get_dossier(self, slug: str) -> dict | None: ...
       def get_repo_health(self, slug: str) -> dict | None: ...
       def trigger_refresh(self, slug: str) -> bool: ...

       # === Local tracking (JSON files) ===
       def get_selected_issues(self) -> list[dict]: ...
       def select_issue(self, origin_slug: str, issue_number: int, ...) -> None: ...
       def get_assigned_issues(self) -> list[dict]: ...
       def save_assignment(self, ...) -> None: ...
       def get_submitted_prs(self) -> list[dict]: ...
       def save_submitted_pr(self, ...) -> None: ...

       # === Fork management (gh CLI) ===
       def fork_repo(self, origin_owner: str, repo: str) -> bool: ...
       def sync_fork(self, repo: str) -> bool: ...
       def check_fork_exists(self, repo: str) -> bool: ...
       def wait_for_fork(self, my_user: str, repo: str, timeout: int = 60, interval: int = 3) -> bool: ...

       # === Agent context ===
       def build_agent_context(self, origin_owner, repo, issue_number, issue_title, issue_url, dossier=None) -> str: ...

       # === Claim management ===
       def report_claim(self, origin_slug: str, issue_id: str, claimed_by: str, fork_issue_url: str) -> None: ...
       def report_unclaim(self, origin_slug: str, issue_id: str) -> None: ...

       # === Dedup ===
       def find_assignment(self, origin_slug: str, issue_number: int) -> dict | None: ...
       def find_selected_issue(self, origin_slug: str, issue_number: int) -> dict | None: ...

       # === Stage transitions ===
       def save_ready_to_submit(self, origin_slug: str, repo: str, branch: str, title: str, base_branch: str) -> None: ...
       def get_ready_to_submit(self) -> list[dict]: ...
   ```

3. **Fork & Assign flow** (Stage 3 — THE critical feature)

   ```python
   @bp.route("/api/oss/fork-and-assign", methods=["POST"])
   def api_oss_fork_and_assign():
       data = request.json
       origin_owner = data["origin_owner"]
       repo = data["repo"]
       issue_number = data["issue_number"]
       issue_title = data["issue_title"]
       issue_url = data["issue_url"]
       origin_slug = f"{origin_owner}/{repo}"
       dossier_context = data.get("dossier")  # Optional: contribution rules from aggregator

       my_user = get_authenticated_user()
       svc = OSSService()

       # 0. Dedup guard — don't create duplicate context issues
       existing = svc.find_assignment(origin_slug, issue_number)
       if existing:
           return jsonify({
               "success": True,
               "fork_issue_url": existing["fork_issue_url"],
               "owner": my_user,
               "already_assigned": True,
           })

       # 1. Fork if needed
       if not svc.check_fork_exists(repo):
           svc.fork_repo(origin_owner, repo)

       # 2. Wait for fork to be ready (GitHub fork creation is async)
       if not svc.wait_for_fork(my_user, repo, timeout=60, interval=3):
           return jsonify({"success": False, "error": "Fork creation timed out", "owner": my_user})

       # 3. Sync fork
       svc.sync_fork(repo)

       # 4. Build agent context (issue body + CONTRIBUTING.md + dossier)
       context_body = svc.build_agent_context(
           origin_owner, repo, issue_number, issue_title, issue_url, dossier_context
       )

       # 5. Create context issue on fork
       create_result = run_gh_command([
           "issue", "create", "-R", f"{my_user}/{repo}",
           "--title", f"[OSS] Fix {origin_owner}/{repo}#{issue_number}: {issue_title}",
           "--body", context_body
       ])

       # 6. Assign Copilot
       fork_issue_url = create_result["output"].strip()
       fork_issue_number = fork_issue_url.split("/")[-1]
       run_gh_command([
           "issue", "edit", fork_issue_number,
           "-R", f"{my_user}/{repo}",
           "--add-assignee", "@Copilot"
       ])

       # 7. Track locally
       svc.save_assignment(origin_owner, repo, issue_number, fork_issue_number, fork_issue_url)

       # 8. Report claim to aggregator (best-effort, don't fail if aggregator is down)
       issue_id = f"github-{origin_slug.replace('/', '-')}-{issue_number}"
       svc.report_claim(origin_slug, issue_id, my_user, fork_issue_url)

       return jsonify({"success": True, "fork_issue_url": fork_issue_url, "owner": my_user})
   ```

   **`wait_for_fork` implementation** (in `oss_service.py`):

   ```python
   def wait_for_fork(self, my_user: str, repo: str, timeout: int = 60, interval: int = 3) -> bool:
       """Poll until fork exists on GitHub. Returns True if ready, False on timeout."""
       for _ in range(timeout // interval):
           check = run_gh_command(["repo", "view", f"{my_user}/{repo}", "--json", "name"])
           if check["success"]:
               return True
           time.sleep(interval)
       return False
   ```

   **`report_claim` implementation** (in `oss_service.py`):

   ```python
   def report_claim(self, origin_slug: str, issue_id: str, claimed_by: str, fork_issue_url: str) -> None:
       """Report claim to aggregator. Best-effort — don't fail if aggregator is down."""
       slug = origin_slug.replace("/", "-")
       _call_aggregator(f"/recon/{slug}/claim", method="POST", data={
           "issueId": issue_id,
           "claimedBy": claimed_by,
           "forkIssueUrl": fork_issue_url,
       })
   ```

   **`find_assignment` implementation** (in `oss_service.py`):

   ```python
   def find_assignment(self, origin_slug: str, issue_number: int) -> dict | None:
       """Check if an assignment already exists for this issue. Returns it or None."""
       assignments = self.get_assigned_issues()
       for a in assignments:
           if a["origin_slug"] == origin_slug and a["issue_number"] == issue_number:
               return a
       return None
   ```

4. **Agent context builder**

   The issue body created on the fork is what gives the agent everything it needs. This is the most important piece of text in the entire pipeline.

   ```python
   def build_agent_context(self, origin_owner, repo, issue_number, issue_title, issue_url, dossier=None):
       # Fetch original issue body
       original = run_gh_command([
           "issue", "view", str(issue_number),
           "-R", f"{origin_owner}/{repo}",
           "--json", "body,labels"
       ])
       original_data = json.loads(original["output"]) if original["success"] else {}

       # Fetch CONTRIBUTING.md (fallback if no dossier)
       contrib_text = ""
       if not dossier:
           contrib = run_gh_command([
               "api", f"/repos/{origin_owner}/{repo}/contents/CONTRIBUTING.md",
               "--jq", ".content"
           ])
           if contrib["success"]:
               contrib_text = base64.b64decode(contrib["output"].strip()).decode("utf-8")

       body = f"""## Upstream Issue
   **Repository:** [{origin_owner}/{repo}](https://github.com/{origin_owner}/{repo})
   **Issue:** [#{issue_number}: {issue_title}]({issue_url})

   ### Original Issue Description
   {original_data.get('body', '*No description provided.*')}

   ---
   ## Instructions
   Fix the issue described above. Your changes will be submitted as a PR to `{origin_owner}/{repo}`.

   **Important:**
   - Follow the upstream repo's coding style and conventions
   - Keep changes minimal and focused
   - Write clear commit messages
   - Add tests if the repo has a test suite
   """

       if dossier and dossier.get("contributionRules"):
           body += f"\n---\n## Contribution Rules\n{dossier['contributionRules']}\n"
       elif contrib_text:
           body += f"\n---\n## CONTRIBUTING.md\n<details><summary>Expand</summary>\n\n{contrib_text[:3000]}\n\n</details>\n"

       if dossier and dossier.get("successPatterns"):
           body += f"\n---\n## What Successful PRs Look Like\n{dossier['successPatterns']}\n"

       return body
   ```

5. **Submit to origin** (Stage 5)

   ```python
   @bp.route("/api/oss/submit-to-origin", methods=["POST"])
   def api_oss_submit_to_origin():
       data = request.json
       origin_slug = data["origin_slug"]   # "fastify/fastify"
       repo = data["repo"]
       branch = data["branch"]
       title = data["title"]
       body = data["body"]

       my_user = get_authenticated_user()

       result = run_gh_command([
           "pr", "create",
           "-R", origin_slug,
           "--head", f"{my_user}:{branch}",
           "--base", data.get("base_branch", "main"),
           "--title", title,
           "--body", body
       ], timeout=60)

       if result["success"]:
           pr_url = result["output"].strip()
           OSSService().save_submitted_pr(origin_slug, pr_url, title)
           return jsonify({"success": True, "pr_url": pr_url, "owner": my_user})
       return jsonify({"success": False, "error": result.get("error"), "owner": my_user})
   ```

   **Stage 4 → Stage 5 transition:** When the user merges a PR on their fork via
   `POST /api/oss/merge-fork-pr`, the merge handler captures the PR's `headRefName`
   (branch name) and adds an entry to `ready-to-submit.json`. Stage 5's
   `GET /api/oss/stage5-submit` reads from this file.

   ```python
   @bp.route("/api/oss/merge-fork-pr", methods=["POST"])
   def api_oss_merge_fork_pr():
       data = request.json
       repo = data["repo"]
       pr_number = data["pr_number"]
       origin_slug = data["origin_slug"]

       my_user = get_authenticated_user()
       svc = OSSService()

       # Capture branch name before merge
       pr_info = run_gh_command([
           "pr", "view", str(pr_number), "-R", f"{my_user}/{repo}",
           "--json", "headRefName,title,baseRefName"
       ])
       pr_data = json.loads(pr_info["output"]) if pr_info["success"] else {}

       # Merge on fork
       result = run_gh_command([
           "pr", "merge", str(pr_number), "-R", f"{my_user}/{repo}", "--squash"
       ])

       if result["success"]:
           # Move to Stage 5: ready to submit
           svc.save_ready_to_submit(
               origin_slug=origin_slug,
               repo=repo,
               branch=pr_data.get("headRefName", ""),
               title=pr_data.get("title", ""),
               base_branch=pr_data.get("baseRefName", "main"),
           )
           return jsonify({"success": True, "owner": my_user})
       return jsonify({"success": False, "error": result.get("error"), "owner": my_user})
   ```

   **Stage 4 fork PR listing** reads the set of forked repos from `assignments.json`:

   ```python
   @bp.route("/api/oss/stage4-fork-prs")
   def api_oss_stage4_fork_prs():
       my_user = get_authenticated_user()
       svc = OSSService()

       # Only check repos we've actually assigned work to
       assignments = svc.get_assigned_issues()
       forked_repos = {(a["origin_slug"], a["repo"]) for a in assignments}

       all_prs = []
       for origin_slug, repo in forked_repos:
           result = run_gh_command([
               "pr", "list", "-R", f"{my_user}/{repo}",
               "--json", "number,title,url,headRefName,additions,deletions,changedFiles,reviewDecision,isDraft,createdAt"
           ])
           if result["success"]:
               prs = json.loads(result["output"])
               for pr in prs:
                   pr["repo"] = repo
                   pr["originSlug"] = origin_slug
               all_prs.extend(prs)

       return jsonify({"success": True, "prs": all_prs, "owner": my_user})
   ```

6. **Local data tracking** (JSON files in `.cache/oss/`)

   ```
   .cache/oss/
     selected-issues.json     # Issues user selected for work
     assignments.json         # Fork issues created + agent assigned
     ready-to-submit.json     # Merged fork PRs ready to submit upstream (Stage 4→5 transition)
     submitted-prs.json       # PRs submitted to origin repos
   ```

   Same file-cache pattern as existing vibecheck caching.

#### Frontend

7. **Types** (`api/types.ts` additions)

   **IMPORTANT:** Add `'oss'` to the existing `PipelineItem.type` union:
   ```typescript
   // EXISTING — update this union:
   type: 'vibecheck' | 'investigate' | 'custom' | 'oss'
   ```

   ```typescript
   // OSS Types
   interface OSSTarget {
     slug: string
     health?: {
       maintainerHealthScore: number
       mergeAccessibilityScore: number
       availabilityScore: number       // Higher = less saturated = better (consistent with all other scores)
       overallViability: number
     }
     meta?: {
       stars: number
       language: string
       license: string
       openIssueCount: number
       hasContributing: boolean
     }
   }

   interface ScoredIssue {
     id: string
     repo: string
     number: number
     title: string
     url: string
     cvs: number
     cvsTier: 'go' | 'likely' | 'maybe' | 'risky' | 'skip'
     lifecycleStage: string
     complexity: string
     labels: string[]               // NOTE: aggregator returns string[], NOT { name: string }[]
     commentCount: number
     assignees: string[]
     claimStatus: string
     createdAt: string
     dataCompleteness: 'full' | 'partial'  // 'partial' = repo health not yet computed, show warning badge
     repoKilled: boolean           // true = repo hit a kill signal, issue is cvs:0
   }

   // Slug format: always hyphenated "{owner}-{repo}" (e.g., "fastify-fastify")
   // Store owner/repo separately in OSSAssignment for gh CLI calls

   interface OSSAssignment {
     originSlug: string
     repo: string
     issueNumber: number
     forkIssueNumber: number
     forkIssueUrl: string
     assignedAt: string
   }

   interface ForkPR {
     number: number
     title: string
     url: string
     repo: string
     originSlug: string
     headRefName: string
     additions: number
     deletions: number
     changedFiles: number
     reviewDecision: string
     isDraft: boolean
     createdAt: string
   }

   interface SubmittedPR {
     originSlug: string
     prUrl: string
     title: string
     state: string
     submittedAt: string
   }
   ```

8. **Endpoints** (`api/endpoints.ts` additions)

   **IMPORTANT:** All OSS responses include `owner: string` to match `createStageLoader`'s
   expected response shape `{ success: boolean; owner: string; ...data }`.

   ```typescript
   interface OSSBaseResponse { success: boolean; owner: string }
   export const getOSSTargets = () => fetchAPI<OSSBaseResponse & {targets: OSSTarget[]}>('/api/oss/stage1-targets')
   export const getOSSScoredIssues = () => fetchAPI<OSSBaseResponse & {issues: ScoredIssue[]}>('/api/oss/stage2-issues')
   export const getOSSAssigned = () => fetchAPI<OSSBaseResponse & {assignments: OSSAssignment[]}>('/api/oss/stage3-assigned')
   export const getOSSForkPRs = () => fetchAPI<OSSBaseResponse & {prs: ForkPR[]}>('/api/oss/stage4-fork-prs')
   export const getOSSSubmitted = () => fetchAPI<OSSBaseResponse & {submitted: SubmittedPR[]}>('/api/oss/stage5-submit')
   // ... action endpoints — all must include owner in response
   ```

9. **Pipeline store** — Register OSS item mapper

   ```typescript
   // Add to pipelineStore.ts:
   registerPipelineItemProvider('oss', ossItemMapper)

   function ossItemMapper(state: PipelineState): PipelineItem[] {
     // Map stage 2 selected issues → pending items
     // Map stage 3 assignments → processing items
     // Map stage 4 fork PRs → waiting_for_review items
     // Map stage 5 submitted → completed/processing items
     // Same pattern as existing vibecheckItemMapper
   }
   ```

   Add OSS stage data to PipelineState:
   ```typescript
   ossStage1: StageData<OSSTarget>
   ossStage2: StageData<ScoredIssue>
   ossStage3: StageData<OSSAssignment>
   ossStage4: StageData<ForkPR>
   ossStage5: StageData<SubmittedPR>
   ```

   Add loaders using `createStageLoader` factory (same pattern as vibecheck stages).

10. **OSSView.tsx** — Main view with StageTabView

    StageTabView's `icon` field is `string` (emoji), NOT a React component.
    Use emoji strings consistent with vibecheck's existing stages.

    ```typescript
    const OSS_STAGES: StageTabConfig[] = [
      { id: 'target',  label: 'Target Repos',    icon: '🎯', component: OSSTargetList,  getCount: () => ... },
      { id: 'select',  label: 'Select Issues',   icon: '📋', component: OSSIssueList,   getCount: () => ... },
      { id: 'assign',  label: 'Fork & Assign',   icon: '🔱', component: OSSAssignPanel,  getCount: () => ... },
      { id: 'review',  label: 'Review on Fork',  icon: '👁',  component: OSSReviewPanel,  getCount: () => ... },
      { id: 'submit',  label: 'Submit Upstream',  icon: '📤', component: OSSSubmitPanel,  getCount: () => ... },
    ]
    ```

11. **Stage 3-5 components** (build in M1 since they have no aggregator dependency)
    - `OSSAssignPanel.tsx` — Shows selected issues, fork-and-assign button, batch support
    - `OSSReviewPanel.tsx` — Wraps ReviewQueueShell for fork PRs
    - `OSSSubmitPanel.tsx` — Shows approved fork PRs, submit button, PR title/body editor

### M1 Validation

- [ ] `POST /api/oss/fork-and-assign` successfully forks a test repo and creates a context issue
- [ ] Fork creation uses polling (not `time.sleep`) — works for repos that take > 3s to fork
- [ ] Calling `fork-and-assign` twice for the same issue returns `already_assigned: true` (dedup)
- [ ] Claim is reported to aggregator via `POST /recon/{slug}/claim` (best-effort)
- [ ] Copilot gets assigned to the fork issue
- [ ] `GET /api/oss/stage4-fork-prs` shows the agent's PR on the fork (reads from assignments.json)
- [ ] PR review on fork works (approve, merge) via existing review infrastructure
- [ ] Merging a fork PR moves the item to `ready-to-submit.json` with branch name captured
- [ ] `POST /api/oss/submit-to-origin` creates a PR from fork to origin
- [ ] **All** OSS API responses include `owner` field (compatible with `createStageLoader`)
- [ ] `PipelineItem.type` union includes `'oss'`
- [ ] OSS items appear in the pipeline list alongside vibecheck items
- [ ] OSSView renders with 5 stage tabs using emoji icons
- [ ] Stage 3-5 UI components render and are functional

---

## Milestone 2: Stages 1-2 (Aggregator Integration)

**Duration:** 3-4 days
**Dependencies:** Aggregator M2 API endpoints (can mock initially)
**Parallel with:** Aggregator M2 (scoring engine)

### What to Build

1. **Aggregator API proxy routes** in `oss_routes.py`
   - `GET /api/oss/stage1-targets` → calls aggregator `/recon/watchlist`, enriches with health data
   - `GET /api/oss/stage2-issues` → calls aggregator `/recon/all-scored-issues`
   - `POST /api/oss/add-target` → calls aggregator `/recon/watchlist/add`
   - Uses `requests.get()` (or `httpx`) to call aggregator API
   - `@cached_endpoint` for caching aggregator responses locally (5 min TTL)
   - **All proxy responses must include `owner: get_authenticated_user()`**

   Note: `AGGREGATOR_API_URL` stores the base URL (e.g., `https://hadoku.me/oss/api`).
   Append `/recon/...` paths — do NOT include `/oss/api` in the path (it's already in the base URL).

2. **Fallback scoring** in `oss_helpers.py`
   - If aggregator is down, fall back to basic `gh` CLI scoring
   - `gh issue list -R {owner}/{repo} --label "good first issue" --json number,title,labels,createdAt,comments,assignees`
   - Score with label/age/comment heuristics
   - **Minimum filters to prevent false positives:**
     - Skip issues with `len(assignees) > 0` (already claimed)
     - Penalize `updatedAt` > 90 days ago by -30 points (stale)
     - Penalize `comments == 0` for issues > 14 days old by -10 (no maintainer triage)
   - This ensures Stages 1-2 work even without the aggregator, with results that are
     directionally consistent with the full aggregator scoring

3. **Stage 1 UI: `OSSTargetList.tsx`**
   - Table showing target repos with health scores, star count, viable issue count
   - Add repo input (text field → validates via `gh api /repos/{owner}/{repo}`)
   - Remove button, refresh button
   - Health score badge (green/yellow/red based on overall viability)

4. **Stage 2 UI: `OSSIssueList.tsx`**
   - Sortable table of scored issues across all target repos
   - CVS score badge with tier coloring
   - Filters: cvsTier (go/likely/maybe), complexity (low/medium/high), lifecycle (accepted/triaged/fresh)
   - Group by repo option
   - "Select for Work" button → moves issue to Stage 3
   - "View Dossier" button → opens side panel with dossier markdown

5. **`OSSDossierPanel.tsx`** — Side panel dossier viewer
   - Renders markdown dossier from aggregator API
   - Tabbed by section using the `DOSSIER_TAB_LABELS` mapping from PROJECT-DESIGN.md:
     `overview` → "Overview", `contributionRules` → "Rules", `successPatterns` → "Success",
     `antiPatterns` → "Anti-Patterns", `issueBoard` → "Issues", `environmentSetup` → "Setup"
   - Iterate over `Object.entries(dossier.sections)` and use the mapping for tab labels
   - Shown from Stage 2 and Stage 3

### M2 Validation

- [ ] `GET /api/oss/stage1-targets` returns repos with health scores from aggregator
- [ ] Adding a target triggers aggregator watchlist add + scraper refresh
- [ ] `GET /api/oss/stage2-issues` returns CVS-scored issues sorted by viability
- [ ] Stage 2 filters work (by tier, complexity, lifecycle)
- [ ] Selecting an issue moves it to Stage 3 and flows through fork→assign→review→submit
- [ ] Selecting the same issue twice is idempotent (dedup guard in `select_issue()`)
- [ ] Dossier panel renders markdown correctly with correct tab labels matching section keys
- [ ] Fallback scoring works when aggregator is unreachable
- [ ] **Full E2E:** Add target → browse issues → select → fork → assign → review → submit → track

---

## Milestone 3: Polish + Tracking

**Duration:** 2-3 days
**Dependencies:** M2 complete
**Parallel with:** Aggregator M3 (dossiers), Scraper M3 (cron)

### What to Build

1. **Outcome tracking** — Poll submitted PRs for status changes
   - Background timer that checks `gh pr view -R {origin_slug} {pr_url} --json state,reviewDecision`
   - Update `submitted-prs.json` with current state
   - Surface in Stage 5 UI with status badges (open, merged, closed, changes_requested)

2. **Notifications** — Discord webhook on key events
   - New GO-tier issue discovered (CVS > 85)
   - Agent completed PR on fork (ready for review)
   - Submitted PR merged upstream
   - Submitted PR received review feedback

3. **Batch operations**
   - Batch fork-and-assign (select multiple issues → fork & assign all)
   - Batch submit (approve multiple fork PRs → submit all to origin)
   - Uses existing `useBatchAction` hook

4. **Agent context enrichment**
   - When aggregator dossier is available, include contribution rules + success patterns in agent context
   - When quirks are detected, add explicit warnings (e.g., "This repo requires changesets — run `npx changeset` before committing")

### M3 Validation

- [ ] Submitted PR status updates in real-time (or on page refresh)
- [ ] Discord notification fires on PR merge
- [ ] Batch fork-and-assign works for 3+ issues simultaneously
- [ ] Agent context includes dossier contribution rules when available
- [ ] Agent context warns about detected quirks

---

## Implementation Notes

### Aggregator URL Configuration

```python
# backend/config.py
# Base URL includes /oss/api prefix. Endpoints append /recon/... paths.
# Example: AGGREGATOR_API_URL + "/recon/watchlist" → "https://hadoku.me/oss/api/recon/watchlist"
# Do NOT include /oss/api in the endpoint paths passed to _call_aggregator().
AGGREGATOR_API_URL = os.environ.get("AGGREGATOR_API_URL", "https://hadoku.me/oss/api")
```

### Local Data Storage

```python
# Same file-cache pattern as existing vibecheck
OSS_DATA_DIR = os.path.join(CACHE_DIR, "oss")

def _load_json(filename):
    path = os.path.join(OSS_DATA_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return []

def _save_json(filename, data):
    os.makedirs(OSS_DATA_DIR, exist_ok=True)
    path = os.path.join(OSS_DATA_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
```

### Error Handling for Aggregator Calls

```python
def _call_aggregator(endpoint, method="GET", data=None, timeout=10):
    """Call aggregator API with graceful failure."""
    if not AGGREGATOR_API_URL:
        return None
    try:
        url = f"{AGGREGATOR_API_URL}{endpoint}"
        if method == "GET":
            resp = requests.get(url, timeout=timeout)
        else:
            resp = requests.post(url, json=data, timeout=timeout)
        if resp.ok:
            return resp.json()
        return None
    except Exception:
        return None  # Graceful degradation
```

### Reuse Existing Patterns

- **Routes:** Same decorator/jsonify pattern as `pipeline_routes.py` and `action_routes.py`
- **Services:** Same `run_gh_command()` wrapper in `github_api.py`
- **Cache:** Same `@cached_endpoint` decorator from `cache.py`
- **Parallel:** Same `ThreadPoolExecutor(max_workers=10)` for fetching fork PRs across repos
- **Store:** Same `createStageLoader` factory and `registerPipelineItemProvider` pattern
- **UI:** Same StageTabView, ReviewQueueShell, batch action hooks
