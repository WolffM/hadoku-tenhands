# crimson-kitty — design index

The third-generation contribution pipeline for vibedispatch. Coexists with
`vibecheck` and `oss-contribution` as a separate pipeline configuration in the
UI; does **not** replace them during the build phase.

Built on Temporal. Designed around the lessons from the `jade-hare` batch
(55 dispatched, 1 merged, 21% empty PRs, 3 cross-reference leaks, 18% AI-slop
callouts, 49% never reached upstream).

## North star

> Every PR we submit, we'd be willing to defend in a Hacker News thread.

## Decisions log (locked)

| # | Decision | Date |
|---|---|---|
| 1 | Workflow engine: **Temporal** (self-hosted) | 2026-04-13 |
| 2 | Cross-ref isolation: **input-context scrubbing** — strip upstream URL/slug/number from the brief before the agent sees it. Agent works directly on existing `WolffM/{repo}` forks. (Supersedes earlier "quarantine org" decision, 2026-04-13.) | 2026-04-13 |
| 3 | Agent for v1: **Copilot SWE** via a modular `Agent` adapter (cost optimization) | 2026-04-13 |
| 4 | Operator UX: **inbox model** — easy issues flow through, blocked issues queue | 2026-04-13 |
| 5 | Coexistence: **new pipeline tab** in the UI alongside vibecheck and oss-contribution; old pipelines stay forever (archival, no cutover required) | 2026-04-13 |
| 6 | Reuse philosophy: **prefer existing utilities** from vibedispatch helpers + hadoku-aggregator API; only rewrite the orchestration layer | 2026-04-13 |
| 7 | Evidence-first: **every state transition requires an artifact**, not just a timestamp | 2026-04-13 |
| 8 | Untrust the agent: **all Copilot output passes through sanitization and gates** before touching anything GitHub indexes | 2026-04-13 |
| 9 | Temporal hosting: **same WSL host, Docker Compose, pm2-managed via mgmt-api** (no unmanaged daemons) | 2026-04-13 |
| 10 | Aggregator endpoints: **add new scrapes to hadoku-aggregator** (CONTRIBUTING, PR template, issue templates, codeowners, ai labels) | 2026-04-13 |
| 11 | LLM judge: **spawn local `claude` CLI subprocess** (uses existing Claude Max subscription, no API key required) | 2026-04-13 |
| 12 | ~~Quarantine PAT~~ — **WITHDRAWN**: no new PAT needed. Pipeline uses the existing `gh` user token + `MSFT_SSO` routing in `services/github_api.py`. (Superseded when decision #2 was revised, 2026-04-13.) | 2026-04-13 |
| 13 | retro_report: **separate tool per pipeline** (`retro_report.py` for legacy, `temporal_retro_report.py` for crimson-kitty); RetroView UI gets tabs | 2026-04-13 |
| 14 | Smoke test: **first batch dispatches against your own repos** before going to external upstreams | 2026-04-13 |
| 15 | Eligibility failure: **no auto-retry** — first failure escalates to inbox | 2026-04-13 |
| 16 | Existing forks under `WolffM/*`: **delete all old jade-hare-era forks** before crimson-kitty's first run; backup fork list to JSONL first | 2026-04-13 |

## Document map

| Doc | Purpose |
|---|---|
| [architecture.md](architecture.md) | Five principles, Temporal rationale, system diagram |
| [state-machine.md](state-machine.md) | Issue states, transitions, evidence requirements per state |
| [gates.md](gates.md) | Gate registry; each jade-hare bug class mapped to its killing gate |
| [cross-ref-isolation.md](cross-ref-isolation.md) | Input-context scrubbing model, output sanitizer, leak vector mapping |
| [components.md](components.md) | Reuse map across vibedispatch, hadoku-aggregator, hadoku-scrape, hadoku-site |
| [pipeline-config.md](pipeline-config.md) | How crimson-kitty plugs into the existing pipeline-select UI |

## Status (2026-04-24)

Pipeline reaches `submittable` and submission_judge consistently on
fresh batches. Phase-4 bring-up is 25 bug fixes deep (see
[state/crimson-kitty/phase4-retrospective.md](../../state/crimson-kitty/phase4-retrospective.md)).
Bodies pulled from evidence now pass the `no_upstream_refs` and
`pr_template_compliance` gates; submission_judge scores trend
0.58–0.74 on the latest batch (v12).

Zero upstream PRs have shipped — intentionally held until the
authorship-replication step (below) is in place.

## In-flight work — operator-authored submission (phase 4.5)

**Problem:** the pipeline harvests a fix from Copilot's draft PR on the
fork, but the commits on that branch are authored by
`copilot-swe-agent[bot]` and the branch itself is `copilot/<slug>`.
`submit_upstream_pr` is wired to push `WolffM:crimson-kitty-{N}` →
upstream, but nothing ever puts the fix onto that branch under the
operator's git identity. Result: no upstream submission could succeed
even after all gates pass, and any submission that did would carry
bot-attribution commits — not something we can defend upstream.

**Fix:** a new activity `replicate_fix_as_operator` runs between the
existing `render_pr_body` step and the submittable gates. It:

1. Reads the agent's final tree SHA from the Copilot PR's head commit.
2. Writes a NEW single commit whose parent is the fork's default-branch
   HEAD (no lineage to agent commits), whose tree matches the agent's
   final state, and whose author is the operator's gh token identity.
3. Creates the `crimson-kitty-{N}` ref pointing at that commit.
4. Opens a fork-internal PR from `crimson-kitty-{N}` → fork default
   (the operator-authored preview).
5. Closes the Copilot draft PR with a short "superseded by #<N>" note.
6. Rewrites `05-fixed/commits.json` to contain only the new commit so
   `no_upstream_refs` scans the real submission-bound history (agent's
   original commit list is preserved at `05-fixed/agent_original_commits.json`).

The existing `submit_upstream_pr` is gated behind a new
`IssueInput.submit_to_upstream` flag (default `false`). While the flag
is false the pipeline stops at the fork-internal preview PR; operators
review, then flip the flag when ready to actually ship to real upstream.

### Operator signoff + manual edits to the preview PR

When `submit_to_upstream=true`, the workflow does NOT submit upstream
immediately. After the submittable gates pass, it transitions to a
new `awaiting_signoff` state and waits on `submit_human_decision`. The
fork preview PR is the operator's editing surface: they may edit the
body directly on GitHub (add screenshots that the pipeline couldn't
capture, expand prose, tighten the repro narrative) before approving.

On `approve`, `submit_upstream_pr` re-fetches the fork PR's CURRENT
title + body via `gh api repos/{fork}/pulls/{op_pr_num}` and uses
that as the upstream PR content — NOT the rendered evidence files.
Whatever the operator left in the preview PR is what ships. The
output sanitizer re-runs on the live content because human edits are
the only path that can introduce upstream refs after the
`no_upstream_refs` gate has already passed.

On `abort`, the workflow terminates as `aborted` with
`deferred_at=signoff` recorded.

### Open follow-up: per-repo PR conventions

The squash commit message currently comes from the rendered PR title +
first paragraph of the body. This is a placeholder. Upstream
conventions (Conventional Commits prefix, Signed-off-by/DCO
requirement, repo-specific title rules, issue-link syntax) should come
from the aggregator — it already scrapes CONTRIBUTING.md, PR templates,
and merged-commit history. We need a new aggregator endpoint along the
lines of `/recon/{slug}/contribution-conventions` returning a bundle:

```json
{
  "commit_style": "conventional" | "freeform" | "prefix-required",
  "title_prefix_pattern": "^(fix|feat|docs|chore)\\(.+\\): .+$",
  "signoff_required": true,
  "body_structure": ["Summary", "Why", "Test plan"],
  "references": { "close_keyword": "Closes", "syntax": "Closes #N" }
}
```

`replicate_fix_as_operator` and `render_pr_body` both consume this
bundle. Tracked as a concrete aggregator ask — file once the local
MVP is in place.
