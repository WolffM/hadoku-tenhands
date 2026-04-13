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
                                                         submittable
                                                              │
                                                              ▼
                                                         submitted ──► merged
                                                                   ─► closed_by_upstream

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
**Entry**: Quarantine fork created in `WolffM-temporal/{repo-hash}`.
**Evidence required**:
- `forked/quarantine_url` — `WolffM-temporal/...`
- `forked/clone_log.txt`
- `forked/branch_name` — hashed, no issue ref
**Next**: `environment_ready` | `aborted`
**Notes**: Public `WolffM/{repo}` is **not** touched at this stage. The fork
exists in the quarantine org only.

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
**Entry**: All blocking review comments addressed in subsequent commits.
**Evidence required**:
- `remediated/diff.patch` — the additional commits
- `remediated/resolved_comments.json` — mapping of comment → resolution
**Next**: `submittable` | `aborted`

### `submittable`
**Entry**: Pre-submission gates all pass. PR body is rendered.
**Evidence required**:
- `submittable/pr_title.txt`
- `submittable/pr_body.md` — rendered against upstream's PULL_REQUEST_TEMPLATE
- `submittable/sanitizer_scan.json` — confirmed no upstream refs
- `submittable/template_compliance.json` — confirmed template fields filled
- `submittable/public_fork_url` — `WolffM/{repo}` (created here, not earlier)
**Next**: `submitted` | `aborted`
**Notes**: This is where we cross the line from quarantine to public. The
sanitizer-rewritten branch gets pushed to the public fork, and only then do
we open the upstream PR.

### `submitted`
**Entry**: Upstream PR opened.
**Evidence required**:
- `submitted/upstream_pr_url`
- `submitted/upstream_pr_number`
**Next**: `merged` | `closed_by_upstream`
**Notes**: The workflow continues to run, watching for upstream events:
review comments, merge, close. `notify_human_comments` fires Discord
alerts from this state as a side effect — it does NOT change the
workflow state. The workflow stays in `submitted` until upstream merges
or closes.

### `merged` (terminal, success)
**Entry**: Upstream PR merged.
**Evidence required**: `merged/merge_sha`, `merged/merged_at`.

### `closed_by_upstream` (terminal, failure)
**Entry**: Upstream PR closed without merge.
**Evidence required**: `closed/closed_at`, `closed/closer`,
`closed/last_comment.json`.
**Notes**: We capture the closing comment so the retro tool can categorize
why we lost.

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
| `eligible` | `forked` | activity: `fork_to_quarantine` | `quarantine_isolation` |
| `forked` | `environment_ready` | activity: `setup_environment` | `environment_works` |
| `environment_ready` | `reproduced` | activity: `agent_reproduce` | `repro_evidence_present` |
| `reproduced` | `fixed` | activity: `agent_fix` | `diff_non_empty` + `relevance` |
| `fixed` | `verified` | activity: `agent_verify` | `verified_evidence_present` |
| `verified` | `reviewed` | activity: `run_review` | — |
| `reviewed` | `remediated` | activity: `agent_remediate` (if blockers) | `remediation_complete` |
| `reviewed` | `submittable` | (no blockers) | — |
| `remediated` | `submittable` | direct | — |
| `submittable` | `submitted` | activity: `submit_upstream_pr` | `no_upstream_refs` + `pr_template_compliance` |
| `submitted` | `merged` | watcher: upstream PR merged | — |
| `submitted` | `closed_by_upstream` | watcher: upstream PR closed | — |
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
        quarantine_url
        clone_log.txt
        branch_name
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
        public_fork_url
      10-submitted/
        upstream_pr_url
        upstream_pr_number
      11-merged/             OR    11-closed_by_upstream/    OR    11-aborted/
        merge_sha                  closed_at                       reason.md
        merged_at                  closer                          aborted_at
                                   last_comment.json               aborted_by
      gates.jsonl              # full gate audit trail (append-only)
      transitions.jsonl        # full state transition log (append-only)
      events.jsonl             # external events (PR comments, reviews) — feeds notify_human_comments
```

The directory layout doubles as the on-disk schema. The retro tool reads
straight from these files. Temporal stores workflow state separately in
PostgreSQL but the *artifacts* live here in plain files so we can grep them,
back them up, and inspect them without a Temporal client.
