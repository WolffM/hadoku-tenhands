# State machine

## States

Each issue moves through a series of states. Every state has an entry
condition (the gate that lets it in), an evidence requirement (what artifact
must exist), and a set of legal next states.

```
candidate ──► eligible ──► forked ──► environment_ready ──► reproduced
                                                                │
                                                                ▼
                              ┌───────────────────────────  fixed
                              │                                │
                              ▼                                ▼
                         abandoned                         verified
                                                              │
                                                              ▼
                                                          reviewed
                                                              │
                                                              ▼
                                                         remediated
                                                              │
                                                              ▼
                                                         replicated
                                                              │
                                                              ▼
                                                         submittable
                                                              │
                                                              ▼
                                                       awaiting_signoff
                                                              │
                                                              ▼
                                                         submitted ──► merged
                                                              ▲     ─► closed_by_upstream
                                                              │     ─► remediating_upstream
                                                              │             │
                                                              │             ▼
                                                              │       submittable_v2
                                                              │             │
                                                              │             ▼
                                                              │       awaiting_signoff (re-entry)
                                                              │             │
                                                              └─────────────┘

       (any state)  ──► aborted   (with reason)
       (any state)  ──► awaiting_human_review  ──► (resumes after operator decision)
```

## State definitions

### `candidate`
**Entry**: Issue identified by upstream-issue selection (manual or automated).
**Evidence required**: Issue ref (`{slug, number}`), source (manual / batch).
**Next**: `eligible` (passes eligibility gate) | `aborted`
**Notes**: Cheap to reach. No external action taken.

### `eligible`
**Entry**: Eligibility gate passed.
**Evidence required**:
- `eligibility/dossier.json` — full repo dossier from aggregator
- `eligibility/issue_brief.json` — issue brief from aggregator
- `eligibility/contributing_check.json` — AI-policy scan result
- `eligibility/decision.json` — `{passed: true, reason: "..."}`
**Next**: `forked` | `aborted`
**Notes**: This is the high-bar filter. We refuse to dispatch hostile repos,
already-claimed issues, or issues without a fixable scope.

### `forked`
**Entry**: Fork ensured at `WolffM/{repo}` (created on first use via
`gh repo fork`, reused otherwise) AND the issue brief has been scrubbed of
all real upstream refs.
**Evidence required**:
- `forked/fork_url` — `https://github.com/WolffM/{repo}`
- `forked/branch_name` — operator-readable, e.g. `fix-blank-cells-xlsx`
- `forked/scrubbed_brief.md` — the brief that will be handed to the agent
- `forked/scrub_report.json` — `{stripped: [{pattern, span, replacement}, ...]}`
**Next**: `environment_ready` | `aborted`
**Notes**: This is where input-context isolation happens. The agent never
sees `forked/` evidence directly — it receives `scrubbed_brief.md` as its
assignment context. The `input_context_clean` gate scans the scrubbed brief
for any real upstream ref that survived; survival aborts the workflow.

### `environment_ready`
**Entry**: Repo cloneable, dependencies install, dev server starts (where
applicable).
**Evidence required**:
- `environment/install_log.txt`
- `environment/dev_server_log.txt` (if applicable)
- `environment/health.json` — `{installable: true, runnable: true}`
**Next**: `reproduced` | `aborted`
**Notes**: A "can we run this thing" smoke test before we burn Copilot
tokens.

### `reproduced`
**Entry**: Failing test, screenshot, or trace exists that demonstrates the
bug.
**Evidence required** (one of):
- `reproduced/test.{py|ts|js|...}` — a failing test
- `reproduced/before.png` — screenshot of the broken state
- `reproduced/trace.zip` — Playwright/Puppeteer trace
- `reproduced/notes.md` — agent's written explanation, mandatory in all cases
**Next**: `fixed` | `aborted`
**Notes**: This is the gate that kills the puppeteer-class failure ("agent
claimed a fix without ever reproducing the bug"). The check is fully
mechanical (presence + structural), so this state only transitions to
`fixed` (pass) or `aborted` (fail). The agent is told upfront: "produce
a repro artifact and a structured `notes.md` or declare the issue out of
scope."

### `fixed`
**Entry**: Diff exists, has commits ahead of base, touches files relevant to
the issue.
**Evidence required**:
- `fixed/diff.patch`
- `fixed/commit_shas.txt`
- `fixed/files_touched.txt`
- `fixed/relevance_check.json` — `{relevant_files: [...], unrelated_files:
  [...]}` (catches the markitdown unrelated-imports class)
**Next**: `verified` | `aborted`
**Notes**: This is where the empty-PR class dies (`diff_non_empty` gate).

### `verified`
**Entry**: The previously-failing test now passes, OR an "after" screenshot
exists and is visually different from "before."
**Evidence required**:
- `verified/test_output.txt` (passing) OR `verified/after.png`
- `verified/diff_from_repro.json` — `{visual_diff_score: 0.x, ...}` for
  screenshot-based verification
**Next**: `reviewed` | `aborted`
**Notes**: This is where the "claimed fix that doesn't work" class dies
(puppeteer saga). The agent can no longer self-certify a fix. The visual
diff check is pixel-comparison (not LLM), so this state has no defer
path — pass or abort only.

### `reviewed`
**Entry**: A code review pass (Copilot Review) has produced review
comments, classified by severity. **Not an LLM judge call** — the
review tool is whatever existing code-review service we use (Copilot
Review in v1). The two LLM judge calls in the entire pipeline are
`relevance` (after `fixed`) and `submission_judge` (after `submittable`),
both documented in [gates.md](gates.md).
**Evidence required**:
- `reviewed/comments.json` — `[{path, line, severity, body}, ...]`
- `reviewed/severity_summary.json` — `{blocking: N, suggested: N, nit: N}`
**Next**: `remediated` (if blockers exist) | `submittable` (no blockers) |
`aborted`

### `remediated`
**Entry**: Phase 5.2 — `read_review_summary` reported `blocking > 0` and
`request_remediation` was dispatched. The Copilot agent reads the
review comments and pushes additional commits to the fork branch.
**Evidence required**:
- `08-remediated/diff.patch` — the additional commits
- `08-remediated/agent_result.json` — the agent's harvest
**Next**: `reviewed` (workflow re-runs `run_review` against the
updated branch) | `aborted` (hit MAX_LOCAL_REMEDIATION_ITERATIONS=3)
**Notes**: The legacy `remediation_complete` gate (which expected an
explicit per-comment `resolved_comments.json` map) is intentionally
skipped — Copilot doesn't produce per-comment annotations. The
remediation loop's re-run of `run_review` is the actual
blocker-resolution check: if the next severity_summary still has
blockers we remediate again until the cap fires.

### `replicated`
**Entry**: Agent's fix has been re-authored under the operator's git
identity — a single squashed commit whose tree matches the agent's
final branch, whose parent is the fork's default-branch HEAD, and
whose author is the operator (not the agent bot). A fork-internal
operator PR is opened pointing at this new branch.

The agent's original draft PR and branch are closed / deleted as
part of this step since the fix has been fully replicated.

This state was added to sever the agent-attribution lineage before
the pipeline considers submitting anywhere real. Commits on the
submission-bound branch must have no `Co-authored-by: copilot-swe-agent`
or references to agent-created commits.

**Evidence required**:
- `submittable/operator_pr_url` — the fork-internal preview PR
- `submittable/operator_pr_number`
- `submittable/squashed_commit_sha` — the new single commit
- `05-fixed/commits.json` — now updated to contain ONLY the new commit
  so downstream gates scan the real submission-bound history
- `05-fixed/agent_original_commits.json` — preserves the agent's commit
  list for audit

**Next**: `submittable` | `aborted`

**Notes**: The squash commit message follows the upstream repo's
convention bundle (when the aggregator exposes one — see TODO in
[components.md](components.md)). Until that signal is available the
message is derived from the rendered PR title + Summary paragraph.

### `submittable`
**Entry**: Pre-submission gates all pass. PR body is rendered.
**Evidence required**:
- `submittable/pr_title.txt`
- `submittable/pr_body.md` — rendered against upstream's PULL_REQUEST_TEMPLATE
- `submittable/sanitizer_scan.json` — confirmed no upstream refs
- `submittable/template_compliance.json` — confirmed template fields filled
**Next**: `awaiting_signoff` | `aborted`
**Notes**: The fork's `crimson-kitty-{N}` branch carries a single
operator-authored squashed commit (produced in `replicated`). The
`no_upstream_refs` gate runs the output sanitizer on title, body, and
the squashed commit message here; any real upstream ref blocks the
submission.

`IssueInput.submit_to_upstream` gates the *submit call*, not entry into
`awaiting_signoff`. Every run that clears the submittable gates advances
to `awaiting_signoff` so the operator inbox and signoff UI always run —
this matters for demos and previews, where exercising the signoff path is
the point. The flag decides what an `approve` does: with `true` (the
default) approve opens the upstream PR; with `false` (forced on demo
batches, and settable per-batch/per-issue) approve instead records a
terminal `awaiting_signoff → submittable` transition and the run finishes
without ever touching upstream. `submit_upstream_pr` also refuses to run
when the flag is `false`, as defense in depth.

### `awaiting_signoff`
**Entry**: Submittable gates passed. The
fork-internal preview PR is the operator's editing surface — they may
edit the PR body directly on GitHub (add screenshots, expand prose,
tighten the repro, fix anything the renderer got wrong). The pipeline
stays paused on `workflow.wait_condition` for the
`submit_human_decision` signal.

The inbox entry that lands when entering this state names the gate
`operator_signoff` so the UI distinguishes it from earlier
judge-defer entries.

**Evidence required**: same as `submittable`. The `awaiting_signoff/`
directory is empty by design — the live source of truth is the PR on
the fork, not a snapshot in evidence.

**Next**: `submitted` (operator signal=`approve`) | `aborted`
(signal=`abort`).

**Notes**: When `approve` arrives, `submit_upstream_pr` re-fetches the
fork preview PR's CURRENT title and body (whatever the operator left)
and re-runs the output sanitizer on that live content before opening
the upstream PR. This is the only place a human-edited string lands
in upstream-visible text, so the re-scan is non-negotiable: an
operator who pasted an upstream URL into the body must not break the
isolation invariant.

### `submitted`
**Entry**: Upstream PR opened.
**Evidence required**:
- `submitted/upstream_pr_url`
- `submitted/upstream_pr_number`
**Next**: `merged` | `closed_by_upstream` | `remediating_upstream`
**Notes**: The workflow continues to run, watching for upstream events
via the Phase 5.1 post-submission poll loop:

- `watch_upstream_pr_state` polls every 30 minutes (5 minutes for the
  hour after a new comment/review arrives). Drives `merged`,
  `closed_by_upstream`, and `remediating_upstream` transitions.
- `notify_human_comments_for_issue` fires Discord alerts on each new
  human comment as a side effect — does NOT change workflow state.

If no upstream activity occurs for 30 days, the watcher transitions to
`closed_by_upstream` with `reason="stale"` so workflows don't run
forever. Transient poll failures (network blip, gh rate limit) just
cause the loop to retry on the next tick — they don't abort the
workflow.

### `remediating_upstream`
**Entry**: A new blocking review (`CHANGES_REQUESTED` from a non-bot
user) was detected by `watch_upstream_pr_state` while in `submitted`.
**Evidence required**: `events.jsonl` carries the triggering
`blocking_review` record (review id, user, body excerpt). The
remediation produces `08-remediated/diff.patch` and
`08-remediated/agent_result.json` as before.
**Next**: `submittable_v2` | `aborted`
**Notes**: `request_remediation` fires (routed to `copilot-tq`); the
agent reads the new comments and pushes more commits. Capped at
`MAX_REMEDIATION_CYCLES=3` per workflow lifetime so an adversarial
reviewer can't keep us in the loop forever.

### `submittable_v2`
**Entry**: Remediation cycle completed; `replicate_fix_as_operator` ran
in update mode (force-pushed `branch_name`, PATCHed the existing
operator preview PR's title/body) and the submittable gates re-ran on
the refreshed content.
**Evidence required**: same as `submittable` (`09-submittable/*.md`,
`sanitizer_scan.json`, `template_compliance.json`) — the existing files
get overwritten with the post-remediation rendering.
**Next**: `awaiting_signoff` (re-entry) | `aborted`
**Notes**: Distinct state name so the transitions log captures the
remediation cycle in `from→to` history. The workflow then re-uses the
existing `awaiting_signoff` state for the operator's go/no-go on the
remediated content.

### `merged` (terminal, success)
**Entry**: Upstream PR merged.
**Evidence required**: `merged/merge_sha`, `merged/merged_at`.

### `closed_by_upstream` (terminal, failure)
**Entry**: Upstream PR closed without merge OR the workflow gave up
after 30 days of no upstream activity (`reason="stale"`).
**Evidence required**: `11-closed_by_upstream/closed_at`,
`11-closed_by_upstream/close_info.json` (includes `closer`,
`upstream_slug`, `pr_number`).
**Notes**: We capture the closer's login so the retro tool can categorize
why we lost. The stale path doesn't have a closer (no human action) —
the transition's `reason` field carries `stale: 30d no upstream activity`.

### `aborted` (terminal, intentional)
**Entry**: Operator or gate decided the issue is not viable.
**Evidence required**: `aborted/reason.md`, `aborted/aborted_at`,
`aborted/aborted_by` (`gate:diff_non_empty` | `human:WolffM` | `system:timeout`).
**Notes**: Aborts are first-class outcomes. The retro tool counts them
separately from closures.

### `awaiting_human_review` (transient)
**Entry**: A **judge gate** returned `Defer`. Reachable only from `fixed`
(via `relevance` defer) or `submittable` (via `submission_judge` defer).
Mechanical gates do not produce defers — they pass or abort.

Notification activities like `notify_human_comments` are NOT entries to
this state. They fire Discord alerts as side effects while the workflow
continues running in its current state.

**Evidence required**: `awaiting/gate_results.json`,
`awaiting/inbox_entry.json`, `awaiting/queued_at`.

**Resume**: Operator clicks `approve` / `abort` / `retry-stage` in the
Pipeline Inbox UI; the workflow receives a Temporal signal and resumes
to the next state (or aborts).

## Transitions table

| From | To | Triggered by | Gate |
|---|---|---|---|
| `candidate` | `eligible` | activity: `check_eligibility` | `eligibility` |
| `candidate` | `aborted` | gate: `eligibility` fail | — |
| `eligible` | `forked` | activity: `fork_and_scrub_brief` | `input_context_clean` |
| `forked` | `environment_ready` | activity: `setup_environment` | `environment_works` |
| `environment_ready` | `reproduced` | activity: `agent_reproduce` | `repro_evidence_present` |
| `reproduced` | `fixed` | activity: `agent_fix` | `diff_non_empty` + `relevance` |
| `fixed` | `verified` | activity: `agent_verify` | `verified_evidence_present` |
| `verified` | `reviewed` | activity: `run_review` | — |
| `reviewed` | `remediated` | Phase 5.2: activity: `read_review_summary` finds blocking>0 → `request_remediation` (capped at MAX_LOCAL_REMEDIATION_ITERATIONS=3) | — (gate skipped; loop's re-run of `run_review` is the actual blocker check) |
| `remediated` | `reviewed` | activity: `run_review` re-run on remediated branch | — |
| `reviewed` | `replicated` | `read_review_summary` finds blocking=0 → fall through | — |
| `reviewed` | `aborted` | hit MAX_LOCAL_REMEDIATION_ITERATIONS=3 with blockers persisting | `local_remediation_cap` (synthetic) |
| `replicated` | `submittable` | direct (evidence written, gates run next) | — |
| `submittable` | `awaiting_signoff` | submittable gates pass (always — `submit_to_upstream` gates the submit call, not this entry) | `no_upstream_refs` + `pr_template_compliance` + `submission_judge` |
| `awaiting_signoff` | `submitted` | signal: `approve` AND `submit_to_upstream=true` → activity: `submit_upstream_pr` (live fork-PR content + sanitizer re-scan) | — |
| `awaiting_signoff` | `submittable` | signal: `approve` AND `submit_to_upstream=false` → terminal preview-only finish (no upstream PR) | — |
| `awaiting_signoff` | `aborted` | signal: `submit_human_decision=abort` | — |
| `submitted` | `merged` | watcher: upstream PR merged | — |
| `submitted` | `closed_by_upstream` | watcher: upstream PR closed (or 30d stale) | — |
| `submitted` | `remediating_upstream` | watcher: new blocking review | — |
| `remediating_upstream` | `submittable_v2` | activity: `request_remediation` + `replicate_fix_as_operator` (update mode) | — |
| `submittable_v2` | `awaiting_signoff` | submittable gates re-pass | `no_upstream_refs` + `pr_template_compliance` + `submission_judge` |
| `awaiting_signoff` | `submitted` | signal: `submit_human_decision=approve` → activity: `submit_upstream_pr` (update existing upstream PR via `gh pr edit`) | — |
| `fixed` or `submittable` | `awaiting_human_review` | judge gate Defer (only the 2 judge-state transitions) | — |
| any | `aborted` | gate fail OR operator decision | — |

## Evidence store layout

```
state/
  {batch-id}/                       # e.g. crimson-kitty
    {origin-slug-encoded}-{issue}/  # e.g. microsoft__markitdown-183
      00-candidate.json
      01-eligible/
        dossier.json
        issue_brief.json
        contributing_check.json
        decision.json
      02-forked/
        fork_url
        branch_name
        scrubbed_brief.md
        scrub_report.json
      03-environment/
        install_log.txt
        dev_server_log.txt
        health.json
      04-reproduced/
        test.py | before.png | trace.zip
        notes.md
      05-fixed/
        diff.patch
        commit_shas.txt
        files_touched.txt
        relevance_check.json
      06-verified/
        test_output.txt | after.png
        diff_from_repro.json
      07-reviewed/
        comments.json
        severity_summary.json
      08-remediated/
        diff.patch
        resolved_comments.json
      09-submittable/
        pr_title.txt
        pr_body.md
        sanitizer_scan.json
        template_compliance.json
      10-submitted/
        upstream_pr_url
        upstream_pr_number
      11-merged/             OR    11-closed_by_upstream/    OR    11-aborted/
        merge_sha                  closed_at                       reason.md
        merged_at                  close_info.json                 aborted_at
        merge_info.json            (closer, upstream_slug, pr_n)   aborted_by
      gates.jsonl              # full gate audit trail (append-only)
      transitions.jsonl        # full state transition log (append-only)
      events.jsonl             # external events (comments, blocking reviews,
                               # upstream_merged, upstream_closed_unmerged,
                               # upstream_pr_updated) — feeds notify + retro
```

The directory layout doubles as the on-disk schema. The retro tool reads
straight from these files. Temporal stores workflow state separately in
PostgreSQL but the *artifacts* live here in plain files so we can grep them,
back them up, and inspect them without a Temporal client.
