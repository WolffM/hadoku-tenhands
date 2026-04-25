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
| 12 | ~~Quarantine PAT~~ — **WITHDRAWN**: no new PAT needed. Pipeline uses the existing `gh` user token + `SAML_ORG_TOKEN` routing in `services/github_api.py`. (Superseded when decision #2 was revised, 2026-04-13.) | 2026-04-13 |
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

## Status (2026-04-25)

Pipeline reaches `awaiting_signoff` end-to-end on fresh batches.
Phase-4 bring-up is 25+ bug fixes deep (see
[state/crimson-kitty/phase4-retrospective.md](../../state/crimson-kitty/phase4-retrospective.md))
plus the operator-authorship + signoff redesign described below.
Operator-authored preview PRs render with rich content, no agent
vocabulary, and a clean single squashed commit per submission.

Zero upstream PRs have shipped, by design — every upstream
submission now requires an explicit operator `approve` signal at
`awaiting_signoff`.

## Phase 4.5 — operator-authored submission with signoff gate

The phase fixes two related gaps:

### 1. Authorship lineage (`replicate_fix_as_operator`)

The pipeline harvests a fix from Copilot's draft PR on the fork, but
those commits are authored by `copilot-swe-agent[bot]` on a
`copilot/<slug>` branch — not something we can defensibly ship to
upstream maintainers. The `replicate_fix_as_operator` activity runs
between `render_pr_body` and the submittable gates and:

1. Reads the agent's final tree SHA from the Copilot PR's head commit.
2. POSTs a NEW single commit whose parent is the fork's default-branch
   HEAD (no lineage to any agent commit), whose tree matches the
   agent's final state, and whose author is the operator's gh token
   identity.
3. Creates the `crimson-kitty-{N}` ref pointing at that commit.
4. Opens a fork-internal PR from `crimson-kitty-{N}` → fork default
   branch — the operator-authored preview.
5. Closes the agent's draft PR.
6. Rewrites `05-fixed/commits.json` and `commit_shas.txt` to contain
   only the new commit (originals archived to
   `agent_original_commits.json` / `agent_original_commit_shas.txt`)
   so downstream gates and the re-rendered body scan the real
   submission-bound history.

### 2. Signoff gate (`awaiting_signoff`)

`submit_upstream_pr` no longer fires automatically. After the
submittable gates pass, the workflow transitions to `awaiting_signoff`
and waits on the `submit_human_decision` signal — the fork preview PR
is the operator's editing surface (add screenshots, expand prose, fix
the repro narrative on GitHub directly). On `approve`, the activity
fetches the LIVE preview-PR title + body via `gh api`, re-runs the
output sanitizer on that content, then opens the upstream PR. On
`abort`, the workflow terminates without shipping.

`IssueInput.submit_to_upstream` controls whether the signoff prompt
appears. `false` (default): workflow stops at `replicated`, no inbox
entry, no upstream PR ever. `true`: pause at `awaiting_signoff` for
operator go/no-go.

The two judge-defer gates (`relevance` after `fixed`,
`submission_judge` after `submittable`) and the new `operator_signoff`
all use the same `submit_human_decision` Temporal signal. The inbox
distinguishes them by `gate_name`. See
[state-machine.md](state-machine.md) for the full transition table
and [pipeline-config.md](pipeline-config.md) for the inbox UX
distinction between defer and signoff cards.

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
