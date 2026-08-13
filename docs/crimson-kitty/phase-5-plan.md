# Phase 5 plan — from "operator-signoff works" to "shippable upstream"

> **Shipped 2026-04-27.** Every sub-phase below (5.1–5.5) landed — see the status
> table in [README.md](README.md). Kept as the design record for what each
> sub-phase was protecting against.

Phase 4 closed with an operator who can review + approve a fork-internal
preview PR and have its content cleanly mirrored to a real upstream PR.
But shipping at that boundary today would still be irresponsible: the
pipeline doesn't watch what happens after the upstream PR is opened,
doesn't comply with per-repo contribution conventions (DCO, conventional
commits, close-keyword syntax), and the inbox UI assumes operators
will `curl` to send signals.

Phase 5 is the work between "we *can* submit one" and "we can let a
batch run end to end overnight without supervision."

The five sub-phases are ordered by blocking-ness — earlier ones are
prerequisites or have higher leverage; later ones are polish or
data-quality work. The plan is ordered by what to build *first*, not
by dependency strictness — Phase 5.2 doesn't strictly need 5.1 done,
but doing 5.1 first prevents a class of "we shipped, then dropped the
review comment" outcomes.

## North-star check

> Every PR we submit, we'd be willing to defend in a Hacker News
> thread.

The Phase 5 question becomes: every PR we submit, **and every action
we take after submission**, we'd be willing to defend in a Hacker News
thread. A maintainer who leaves a review comment and gets ghosted by
the same account that opened the PR is the failure mode 5.1 prevents.

---

## Phase 5.1 — Post-submission lifecycle

**Why first:** until this exists, an operator approve at
`awaiting_signoff` opens an upstream PR that the pipeline then
forgets about. Maintainer review comments aren't seen. Merges /
closures aren't recorded. We can't scale to >1 simultaneous
submission without an unattended PR somewhere going stale.

**State machine additions:**

```
submitted ──► merged                  (terminal, success)
          ──► closed_by_upstream      (terminal, failure)
          ──► remediating_upstream    (back to fix loop on blocker)
remediating_upstream ──► submittable_v2 ──► submitted
```

**New activity: `watch_upstream_pr_state`**
- Polls `gh api repos/{upstream}/pulls/{N}` every 30 min (configurable).
- Returns `{state, merged, last_review_comment_id, blocking_review_count}`.
- Heartbeats so workflow stays alive across restarts.

**Workflow extension (`IssueWorkflow.run` after `submitted` state):**

```python
seen_review_ids: set[int] = set()
while True:
    poll = await workflow.execute_activity(
        "watch_upstream_pr_state",
        WatchInput(upstream_slug=..., pr_number=..., seen_review_ids=seen_review_ids),
        start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
    )
    if poll["merged"]:
        record_transition → merged
        return merged result
    if poll["closed_unmerged"]:
        record_transition → closed_by_upstream
        return closed result
    if poll["new_blocking_review"]:
        # Branch into remediation
        ...
    seen_review_ids = poll["all_seen_ids"]
    await asyncio.sleep(timedelta(minutes=30))
```

**New activity: `notify_human_comments_for_issue` (registration only)**
- Already exists in `watchers.py`, never wired into
  `temporal_activities.py`. Register it as an `@activity.defn`.
- Called from the same poll loop as `watch_upstream_pr_state`.

**Comment-triggered remediation:**
- When `watch_upstream_pr_state` reports a new blocking review:
  1. `record_transition: submitted → remediating_upstream`
  2. Run `request_remediation` (already exists) against the
     COPILOT branch — agent reads the new comments, makes commits
  3. Re-run `replicate_fix_as_operator` — squash the new agent
     commits onto a fresh operator-authored commit, force-push to
     `crimson-kitty-{N}`, update the existing operator preview PR
  4. Re-run submittable gates
  5. Re-enter `awaiting_signoff` (operator decides whether to
     re-ship the updated PR)
  6. On approve: `submit_upstream_pr` doesn't open a new PR; it
     pushes the updated branch to the existing upstream PR (gh API
     auto-updates since `head` is the same branch)

**Open questions:**

- *Polling cadence*: 30 min or longer? Trade-off: aggressive polling
  hits gh rate limit faster (5000/hr per token); lazier polling
  delays our remediation response. The legacy pipeline used X — if
  the operator remembers, drop the value here.
- *Termination condition*: when does the watcher give up? After
  N days of inactivity? When upstream goes stale (`stale` label
  applied)? Need a max-watch-duration default so workflows don't
  run forever.
- *Notification channels*: should every poll cycle that finds a new
  comment also fire Discord (existing `notify_human_comment`
  helper)? Or only when `blocking` severity?

**Acceptance criteria:**
- A merged upstream PR transitions the workflow to `merged` and the
  workflow execution completes
- A closed-without-merge upstream PR transitions to `closed_by_upstream`
- A new blocking review comment routes back through remediation and
  produces an updated operator preview PR + new `awaiting_signoff`
  inbox entry
- All polling failures are recoverable (network blip, rate limit) —
  workflow doesn't go to `aborted`, just retries

---

## Phase 5.2 — Local remediation branch

**Why second:** small change, prevents an entire class of "Copilot
Review found a real problem on the fork preview but the workflow
ignored it" failures.

**The gap:** `IssueWorkflow.run` currently runs `run_review`, then
falls straight through to `render_pr_body`. The `request_remediation`
activity exists, the `remediation_complete` gate exists, the
`reviewed → remediated → submittable` transition is documented in
`state-machine.md` — but the workflow code never branches.

**Fix:**

```python
# After run_review writes 07-reviewed/severity_summary.json:
review_summary = await workflow.execute_activity(
    "read_review_summary",  # NEW small read-only activity
    state_root=inp.state_root,
    start_to_close_timeout=_SHORT_ACTIVITY_TIMEOUT,
)
if review_summary["blocking"] > 0:
    await self._transition(
        target="remediated",
        activity_name="request_remediation",
        arg=RemediationInput(...),
        inp=inp,
        long=True,
    )
    # Re-run review on the remediated branch
    await self._transition(
        target="reviewed",  # back to reviewed
        activity_name="run_review",
        arg=ReviewInput(...),
        inp=inp,
        run_gates_after=False,
    )
    # Loop with a max iteration cap (3) to avoid infinite remediation
    ...
```

**Acceptance criteria:**
- Copilot Review flagging a blocking comment triggers
  `request_remediation`
- Loop terminates after `MAX_REMEDIATION_ITERATIONS=3` even if
  blockers persist (workflow goes to `aborted` with a clear reason)
- Existing tests still pass; new test exercises the
  blocker → remediated path

---

## Phase 5.3 — Per-repo contribution conventions

**Why third:** at this point the pipeline submits *and* listens.
Without conventions, we still ship PRs that DCO-required repos
auto-reject and that conventional-commit-style projects close as
"please follow our conventions." This is the "doesn't get
auto-rejected" gate.

**Cross-repo dependency:** the contract for the new aggregator
endpoint (P5-1) is filed at
[hadoku-aggregator/docs/TENHANDS-PHASE5-ASKS.md](https://github.com/WolffM/hadoku-aggregator/blob/main/docs/TENHANDS-PHASE5-ASKS.md).
Phase 5.3 can ship local consumption first using the documented
default fallback; we light up real-data behavior when the endpoint
goes live.

**Aggregator ask — new endpoint:**

```
GET /recon/{slug}/contribution-conventions

Response:
{
  "commit_style": "conventional" | "freeform" | "prefix-required",
  "title_prefix_pattern": "^(fix|feat|docs|chore)(\\(.+\\))?: .+$" | null,
  "signoff_required": true | false,
  "body_structure": ["Summary", "Why", "Test plan"] | [],
  "references": {
    "close_keyword": "Fixes" | "Closes" | "Resolves" | null,
    "syntax": "Fixes #N" | "Closes #N" | null,
    "in_body": true | false  // some repos forbid Fixes in body, only commit msg
  }
}
```

The aggregator already scrapes CONTRIBUTING.md, PR templates, and
merged commits. This endpoint synthesizes those signals into a
machine-consumable bundle.

**Local consumption:**

- `_build_title` (in submission.py) prepends the prefix pattern when
  `commit_style="conventional" | "prefix-required"`.
- `_render_default` reorders sections to match `body_structure` if
  populated; otherwise keeps the current default order.
- `replicate_fix_as_operator` builds the squash commit message with
  the prefix; appends `Signed-off-by: WolffM <...>` if
  `signoff_required=true`.
- `submit_upstream_pr` uses `references.close_keyword` and `syntax`
  for the `Fixes #N` line; omits the in-body line if
  `in_body=false`.

**Acceptance criteria:**
- A submission to apache/* (DCO required) carries `Signed-off-by`
  in the commit
- A submission to a conventional-commits repo has `feat:` / `fix:`
  prefix in title + commit message
- A submission to a repo whose CONTRIBUTING.md says "do not include
  Fixes in body" doesn't include the close keyword in the body
  (still in commit message if `references.in_body=false`)

---

## Phase 5.4 — Operator inbox UI for signoff

**Why fourth:** quality-of-life, not correctness. Operator can drive
everything via `curl` today. But once 5.1–5.3 are in place we'll
have signoff entries landing routinely; the curl experience won't
scale.

**Backend: already done.** Inbox JSON contains
`gate_name=operator_signoff`, `state=awaiting_signoff`, the operator
PR URL is in evidence (`09-submittable/operator_pr_url`).

**Frontend changes — `components/temporal/PipelineInbox.tsx`:**

Switch on `gate_name`:

- `relevance` / `submission_judge` → judge-defer card. Show score,
  judge reason, evidence file links. Buttons: Approve / Abort /
  Retry.
- `operator_signoff` → signoff card. Show **fork preview PR URL
  prominently** as the primary call-to-action ("Review on GitHub →"),
  not the evidence browser. Surface the rendered body summary inline
  (first 500 chars). Buttons: **Approve & ship upstream** / Abort.

The signoff card should make the "edit the fork PR if you want, then
approve" workflow obvious. A small note: "Edits to the fork preview
PR are picked up live when you approve. The pipeline re-runs the
sanitizer on the live content."

**Acceptance criteria:**
- Both card types render distinctly in the inbox
- Signoff card has a button that opens the fork preview PR in a new
  tab
- Approve / Abort buttons fire the existing signal endpoint, no curl
  needed
- Existing judge-defer cards still work unchanged

---

## Phase 5.5 — Judge calibration

**Why last:** thresholds (`MIN_PASS=0.75`, `MIN_DEFER=0.55`) are
hand-picked, not data-driven. Until we have submission volume,
hand-picked is fine. But before tuning anything, we need fixtures.

**Build:**

- 10 hand-labeled fixtures for `relevance_v1`:
  - 4 obvious passes (clean fix, scoped to issue)
  - 3 obvious fails (lockfile-only, completely unrelated changes)
  - 3 borderline (partial impl, scaffolding-only, scope creep)
- 10 fixtures for `submission_judge`:
  - 4 strong PR bodies
  - 3 thin/incomplete bodies
  - 3 borderline (good problem statement but weak verification, etc.)

**Each fixture:**

```
calibration_fixtures/relevance/01_clean_fix/
  brief.md
  diff.patch
  files_touched.txt
  expected.json   # {verdict: "pass", score_min: 0.85, ...}
```

**Calibration script:**

```bash
python -m temporal.calibration --rubric relevance_v1
# Runs each fixture through the live judge, prints score distribution,
# computes precision/recall at current thresholds, suggests adjustments.
```

**Acceptance criteria:**
- 20 fixtures committed
- Calibration script runs end to end against the live `claude` CLI
- Output suggests threshold adjustments if observed accuracy drops
  below 80% pass-recall or 90% fail-precision

---

## What this plan deliberately doesn't include

- **Multi-agent support.** Single-agent (Copilot) for v1 was a Phase 1
  decision. Adding Claude/Cursor/etc. is post-Phase 5.
- **Auto-dispatch of new issues** without operator pick. Aggregator
  scoring drives the candidate list but the operator picks the batch.
- **Cross-pipeline migration.** crimson-kitty stays separate from
  vibecheck/oss-contribution. Old pipelines keep running for archival;
  new dispatches go through crimson-kitty.
- **Dispatching to private repos.** The cross-ref isolation model
  doesn't currently account for the auth surface of private upstreams.
  Future phase.

## Order of operations summary

| # | Phase | Blocking? | Roughly LOE |
|---|---|---|---|
| 5.1 | Post-submission lifecycle | YES — without it we can't ship | ~2 days |
| 5.2 | Local remediation branch | No (small) | ~half a day |
| 5.3 | Per-repo conventions | Soft-blocking (DCO repos auto-reject) | ~1 day local + aggregator ask |
| 5.4 | Inbox signoff UI | No | ~half a day |
| 5.5 | Judge calibration | No | ~1 day fixtures + tuning |

Sum: ~5 working days of focused build + 1 aggregator-team dependency.
