# VibeDispatch Retrospective v2.0

## Guiding Principles

- Human review comments are the single most important signal. Everything else is context for reading them.
- The retrospective is read-only. Action happens in the next batch, not here.
- Batches are the top-level unit of analysis.
- All fetched data persisted to file immediately. Reports read from file — no repeat API calls.
- Raw comment data always saved unfiltered. Bot filtering happens at render time.

---

## Batch Identity

### Naming convention
`{adjective}-{animal}` — e.g. `fluffy-tiger`, `crimson-kitty`

### Established batches
| Name | Period | Issues | Status |
|------|--------|--------|--------|
| `dusty-lizard` | Feb 2026 | 8 (pre-tracking) | Historical |
| `jade-hare` | Mar 13–17 2026 | 55 | Historical |
| `crimson-kitty` | Mar 24 2026+ | Active | **Current** |

Active batch configured in `backend/.cache/oss/active-batch.json`.
All batches stored in `backend/.cache/oss/batches.json`.

### Scripts
- `scripts/gen_batch_names.py` — generate ~50 name candidates for manual selection
- `scripts/backfill_batches.py` — retroactively stamps existing records with batch_id

---

## Session Artifacts (per issue)

Stored in `backend/.cache/oss/sessions/{owner}-{repo}/{issue_number}/`:

| File | When saved | Content |
|------|-----------|---------|
| `context.md` | Stage 3 | Context brief posted to fork issue |
| `session.log` | Post-Stage 4 | Copilot session thinking log |
| `fork-diff.patch` | Post-Stage 4 | Full PR diff |
| `upstream-pr-body.md` | Stage 5 submit | PR body submitted to upstream |
| `fork-pr-comments.json` | Stage 4 before merge | All fork PR comments (raw, unfiltered) |
| `upstream-pr-comments.json` | Stage 5 poll | All upstream PR comments (raw, unfiltered) |

---

## Bot Filter

`backend/helpers/bot_filter.py` — `BOT_LOGINS` set + `is_bot(login)` + `filter_human_comments(comments)`.
Add new bots to `BOT_LOGINS`. Filtering happens at render time, not at save time.

---

## Backend State Changes

### oss_state.py additions
```python
# New methods on OSSStateMixin:
get_batches() → list
get_active_batch() → str | None          # reads active-batch.json
set_active_batch(batch_id)               # writes active-batch.json, creates batch record
add_issue_to_batch(batch_id, issue_ref)  # idempotent
get_batch(batch_id) → dict | None

# Modified:
save_assignment(...)                     # stamps batch_id from get_active_batch(), calls add_issue_to_batch
save_submitted_pr(..., issue_number=None)  # adds issue_number to record
```

### pipeline_retrospective.py additions
```python
fetch_pr_comments(repo_slug, pr_number) → list[dict]
# Returns: [{author, body, created_at, comment_type: "regular"|"inline", path?, line?}]

# collect_retrospective() gains new fields:
retro["batch_id"]            = assignment.get("batch_id")
retro["context_issue_body"]  = get_session_artifact(origin_slug, issue_number, "context.md")
retro["upstream_pr_body"]    = get_session_artifact(origin_slug, issue_number, "upstream-pr-body.md")
retro["raw_comments"]        = {
    "fork_pr": json.loads(get_session_artifact(..., "fork-pr-comments.json")) or [],
    "upstream_pr": json.loads(get_session_artifact(..., "upstream-pr-comments.json")) or [],
}
```

### oss_routes_stage4.py additions
```python
def _capture_fork_pr_comments(my_user, repo, pr_number, origin_slug, svc):
    """Fetch and save fork PR comments before merge. Silent on failure."""
    # fetch_pr_comments(f"{my_user}/{repo}", pr_number)
    # save to session artifact: fork-pr-comments.json

# Hooks:
# merge-fork-pr: call _capture_fork_pr_comments before merge
# signoff Step 3: call _capture_fork_pr_comments before merge
# signoff: save_submitted_pr(..., issue_number=upstream_issue_number)
```

New endpoints:
```
GET /api/oss/retro/batches       → { batches: BatchSummary[] }
GET /api/oss/retro/batch/<name>  → { batch, issues: [{assignment, upstream_pr, retro}] }
```

### oss_routes_stage5.py additions
```python
# submit-to-origin:
save_session_artifact(origin_slug, issue_num, "upstream-pr-body.md", body)
svc.save_submitted_pr(origin_slug, pr_url, title, issue_number=issue_num)

# _poll_single_pr:
all_comments = fetch_pr_comments(f"{repo_owner}/{repo_name}", pr["pr_number"])
save_session_artifact(origin_slug, issue_num, "upstream-pr-comments.json", json.dumps(all_comments))
```

---

## Frontend Architecture

### ViewType
Add `'retro'` to the union in `uiStore.ts`.

### New API types (api/types.ts)
```typescript
interface PrComment {
  author: string; body: string; created_at: string
  comment_type: 'regular' | 'inline'; path?: string; line?: number
}
interface BatchSummary { batch_id, created_at, note, issue_count, upstream_pr_count, upstream_merged, upstream_closed, upstream_open, has_fork_pr }
interface BatchIssue { assignment, upstream_pr, retro }
interface BatchDetailResponse extends OSSBaseResponse { batch, issues: BatchIssue[], error? }
interface BatchListResponse extends OSSBaseResponse { batches: BatchSummary[] }
```

### New API endpoints (api/endpoints.ts)
```typescript
getRetroBatches() → BatchListResponse         // GET /api/oss/retro/batches
getRetroBatchDetail(batchId) → BatchDetailResponse  // GET /api/oss/retro/batch/{id}
```

### New components
```
frontend/src/views/RetroView.tsx             — top-level view, batch tabs, issue list
frontend/src/components/retro/
  IssueRetroCard.tsx                         — expandable issue card (EXISTS)
  BatchSummaryPanel.tsx                      — funnel: dispatched→fork→upstream→outcomes
  ContextPanel.tsx                           — slide-in panel for context.md / upstream PR body
  index.ts                                   — exports
```

### Wiring
- `App.tsx`: import + `case 'retro': return <RetroView />`
- `Navigation.tsx`: add `{ id: 'retro', label: 'Retrospective' }` to pipelineTabs
- `views/index.ts`: add `export * from './RetroView'`

### IssueRetroCard sections (in order)
1. Timeline (steps, timestamps, deltas)
2. **Human comments** — OPEN BY DEFAULT, bot-filtered, Fork PR + Upstream PR threads
3. Copilot workflow (reproduced/verified/self_corrected chips)
4. SA findings (file:line — message)
5. Artifacts (links to ContextPanel: context brief, upstream PR body)

Batch tabs: last 5 visible, 6th = "Older ▾" dropdown.

---

## CLI Skills (Phase 3 — not yet implemented)

`scripts/retro_report.py` — Markdown generator, two modes:

```
# Single PR
python3 scripts/retro_report.py --pr owner/repo#123
python3 scripts/retro_report.py --pr https://github.com/owner/repo/pull/456

# Batch
python3 scripts/retro_report.py --batch crimson-kitty
python3 scripts/retro_report.py --batch 2026-03-17
python3 scripts/retro_report.py --prs url1,url2

# Flags
--full     show full context body (default: truncated)
--output   write to file instead of stdout
```

Skill wrappers:
- `.claude/commands/retro-pr.md`
- `.claude/commands/retro-batch.md`
