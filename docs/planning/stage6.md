# Stage 6 — Upstream PR Monitoring & Retrospective

## Goals (from spec)

After upstream PR submission, Stage 6 handles three recurring situations:

1. **Build failure** — CI fails on the upstream PR → dispatch a new agent to the fork with the build failure as context → validate the fix → port to the upstream PR (new squashed commit from WolffM, not Copilot).

2. **External SA / automated code review** (CodeRabbit, etc.) → dispatch a remediation agent against the fork → validate → port to upstream PR. If a finding is not actionable, auto-respond to the comment explaining why.

3. **Human engagement** → DO NOT auto-respond. Trigger a Discord notification with the comment, the PR context, and a suggested response for the user to review and send manually.

**Critical invariant:** All commits to the upstream PR must come from WolffM, not Copilot. All work is done on the fork, then squashed to the upstream branch under WolffM's identity.

---

## Root Cause: The Telemetry Gap

The pipeline currently saves zero artifacts about what was sent to Copilot or why it failed. Every failed PR is a black box. We have:
- `pipeline-events.jsonl` — step timing events (stage 3 only)
- `retrospective-logs.json` — aggregate stats (PR line count, SA conclusion, review inline count)

We are missing:
- The actual dossier + instructions markdown sent to Copilot (built but never saved)
- The full Copilot session log (what files it read, edited, tested)
- The fork PR diff before squashing (what Copilot actually changed)
- The upstream PR body submitted to the maintainer
- Upstream PR events after submission (comments, CI, review decisions)

### Part A — Full Pipeline Telemetry

**Session directory per issue:** `backend/.cache/oss/sessions/{owner}-{repo}/{issue_number}/`

| File | Captured At | Method |
|---|---|---|
| `context.md` | Stage 3, after `build_agent_context` | Write `context_body` to file |
| `session.log` | Stage 4 retrospective | `copilot-sessions.py summary -R WolffM/{repo} --pr {fork_pr}` |
| `fork-diff.patch` | Stage 4 retrospective | `gh pr diff {fork_pr} -R WolffM/{repo}` |
| `upstream-pr-body.md` | Stage 5 / signoff | Save body string before `gh pr create` |
| `upstream-events.json` | Stage 6 polling | Per-poll snapshot of comments + CI + reviews |

Add paths to `retrospective-logs.json` entries so the report view can link to each artifact.

---

### Part B — Stage 6 Polling Loop

**Cadence:** Every 15 minutes, after active stage 4 assignments are processed.

**Per-PR data structure:**

```json
{
  "pr_number": 123,
  "state": "open|closed|merged",
  "health": "healthy|needs_attention|actionable|rejected|stale|empty",
  "last_human_comment_at": "...",
  "comments": [
    {
      "id": 456,
      "author": "username",
      "is_bot": false,
      "body_excerpt": "first 300 chars...",
      "created_at": "...",
      "signals": ["needs_tests", "wrong_approach"]
    }
  ],
  "ci": {
    "conclusion": "failure|success|pending",
    "failing_checks": ["lint"],
    "passing_checks": ["build", "test"]
  },
  "review_decision": "CHANGES_REQUESTED|APPROVED|REVIEW_REQUIRED|null",
  "signals": ["empty_pr", "wip_title", "ai_detected", "fix_doesnt_work", "needs_description"]
}
```

**Signal detection:**

| Signal | Logic |
|---|---|
| `empty_pr` | Additions + deletions < 5, OR human comment contains "empty"/"no changes" |
| `wip_title` | Title contains `[WIP]` |
| `ai_detected` | Human comment contains "AI"/"copilot"/"generated"/"llm" (case-insensitive) |
| `fix_doesnt_work` | Human comment contains "still reproduces"/"doesn't work"/"not fixed"/"still fails" |
| `wrong_approach` | Human comment contains "wrong approach"/"different way"/"shouldn't" |
| `needs_tests` | Human comment contains "test"/"spec"/"coverage" |
| `needs_description` | Human comment contains "description"/"screenshot"/"changeset" |
| `ci_failing` | CI conclusion "failure", at least one non-lint check failing |
| `changes_requested` | review_decision == "CHANGES_REQUESTED" |

**Health scoring:**

| Health | Criteria |
|---|---|
| `rejected` | Closed with `ai_detected` or `fix_doesnt_work` signal |
| `empty` | `empty_pr` signal, still open |
| `actionable` | `ci_failing` or `changes_requested` or `fix_doesnt_work` — something concrete to act on |
| `needs_attention` | New human comment since last check |
| `stale` | Open, no activity in >72h |
| `healthy` | Open, CI passing/pending, no red signals |

**Discord notifications (replaces all existing hooks):**

| Event | What's sent |
|---|---|
| Human comment | PR link, repo, author, full comment, Claude-suggested response |
| CI failure | PR link, failing check names, run link |
| PR closed by maintainer | PR link, last human comment (rejection reason) |
| PR merged | PR link |
| `ai_detected` | Urgent flag, offending comment, suggested response |

**Automated actions (no approval needed):**

| Trigger | Action |
|---|---|
| External SA bot comment (CodeRabbit/Greptile) | Dispatch remediation agent to fork → validate → port |
| CI failure (build/test, not lint only) | Dispatch fix agent to fork → validate → port |
| `empty_pr` signal | Auto-close with polite explanation |

**Requires user action (Discord notification, user responds manually):**
- Human comments (any sentiment)
- `ai_detected`
- `fix_doesnt_work`
- `changes_requested`

---

### Part C — Retrospective View (Frontend)

**Stage 6 tab in OSS view:**

1. **Health summary bar** — count badges: healthy / needs_attention / actionable / rejected / stale / empty

2. **PR table** (filterable, sortable by last human comment date):
   - Repo, Title, Health badge, CI status, Human comment count + excerpt, Age

3. **PR detail drawer** (click row):
   - PR metadata + upstream link
   - **Instructions sent** — `context.md` rendered as markdown
   - **Copilot session summary** — `session.log` content
   - **Fork diff** — syntax-highlighted patch
   - **Upstream PR body** — what was submitted
   - **Comment timeline** — bots greyed, humans bold with signal badges
   - **CI per-check breakdown**
   - **Action buttons**: Close PR | Post comment (opens editor) | View on GitHub

---

### New Backend Endpoints

```
GET  /api/oss/stage6-status                   → all submitted PRs with health + signals
GET  /api/oss/stage6-pr/{slug}/{issue_number} → one PR detail + all artifacts
POST /api/oss/stage6-poll                     → trigger immediate re-poll
POST /api/oss/stage6-close                    → close upstream PR with optional comment
POST /api/oss/stage6-respond                  → post WolffM comment on upstream PR
```

---

## Implementation Order

### Phase 1 — Telemetry (no new UI, add to existing pipeline)

1. `oss_state.py` — add `OSSSessionStore` helper: `session_dir(slug, issue)`, `save_artifact(slug, issue, filename, content)`
2. `oss_routes_stage3.py` — after `build_agent_context`, call `session_store.save_artifact(context.md)`
3. `pipeline_orchestrator.py` `_collect_retrospective` — call `copilot-sessions.py summary` and `gh pr diff`, save to session dir, add `session_artifacts` paths to retro record
4. `oss_routes_stage4.py` signoff — save `upstream-pr-body.md` before `gh pr create`

### Phase 2 — Stage 6 Polling Backend

1. `services/stage6_poller.py` — PR polling, signal detection, health scoring
2. `routes/oss_routes_stage6.py` — new blueprint with all endpoints
3. `pipeline_loop.py` — add Stage 6 poll at 15-min cadence
4. `helpers/notifications.py` — rebuild Discord hooks around Stage 6 events

### Phase 3 — Stage 6 Frontend

1. Stage 6 tab + Zustand store slice
2. PR health table + filter bar
3. PR detail drawer with artifact panels
4. Close/respond action buttons

---

## Immediate Crisis PRs (Action Required Before Stage 6 is Built)

| PR | Action | Reason |
|---|---|---|
| [keras-team/keras #22455](https://github.com/keras-team/keras/pull/22455) | Close | Maintainer: "This is empty. Should this be closed?" |
| [solidjs/solid #2640](https://github.com/solidjs/solid/pull/2640) | Close | Maintainer: "No changes in this PR?" |
| [puppeteer/puppeteer #14791](https://github.com/puppeteer/puppeteer/pull/14791) | Close | "Don't send AI PRs" + fundamentally wrong approach |
| [storybookjs/storybook #34235](https://github.com/storybookjs/storybook/pull/34235) | Close | Fix confirmed not working |
| [payloadcms/payload #16008](https://github.com/payloadcms/payload/pull/16008) | Update title | Must follow Conventional Commits |
| [mermaid-js/mermaid #7511](https://github.com/mermaid-js/mermaid/pull/7511) | Add description + screenshot + changeset | Maintainer request |
| [opentofu/opentofu #3916](https://github.com/opentofu/opentofu/pull/3916) | DCO sign + re-open | Maintainer explicitly asked |

## Discord Webhook

Delete existing hooks (fire on useless test repos). Rebuild in Phase 2 around Stage 6 events only. Fix `DISCORD_WEBHOOK_URL` in `.env`.
