# Dispatch Readiness Overhaul

**Owner:** WolffM (drafted 2026-05-24, revised after consultant review)
**Scope:** spans `hadoku-scrape` → `hadoku-aggregator` → `tenhands`

> **Shipped 2026-05-24–27.** The tenhands side of this overhaul landed within days of
> drafting: the outcome snapshot activity (upstream PR status polling per dispatch),
> structured operator override capture at signoff, the baseline snapshot CLI
> (`scripts/snapshot_outcomes.py`), per-gate decision telemetry, and the
> `actionability_v1` rubric + gate (`backend/temporal/gates/actionability.py`,
> "judge in the middle"). The body below is kept as the historical design record —
> the outcome taxonomy and the why are still the reference for reading the data
> those pieces now produce.

## Why

We dispatched keycloak#46523 against an issue whose upstream had quietly
become an epic — 10 sub-issues, active redesign discussion among 6 maintainers,
in-flight rename to "parameterized scopes." The pipeline did everything
correctly *given the framing*: fork → repro → fix → submission_judge passed
at 0.89 → preview PR ready. The framing was wrong: a one-line
`EXPERIMENTAL → PREVIEW` enum flip will not close that issue.

The visible failure was one PR. The underlying problem is broader. From the
operational data (10 batches, 51 dispatches, May 2026):

| Outcome | Count | % |
|---|---|---|
| Pass (internal gates) | 23 | 45% |
| Defer (submission_judge) | 20 | 39% |
| Fail (any gate) | 8 | 16% |

**The keycloak shape is silent.** It sits in the 23-issue *pass* column —
dispatches that worked, got judge-approved, shipped a preview PR, and then
either get quietly closed without merge, ignored, or sit open until they
fall out of the changelog. The 16% hard-fails are loud; the silent loss in
the 45% pass column is what this overhaul targets.

This doc tracks the multi-phase overhaul to detect *upstream receptiveness*
before spending agent cycles, not just internal solvability.

## Success metric

**Upstream PR outcomes, not internal pass rate.**

For every dispatch, classify the upstream PR over time:

- `merged` — maintainer accepted; this is the only true win
- `closed_unmerged` — maintainer rejected; usually a sign we read the issue wrong
- `open_stale` — open with no maintainer engagement; measured at 30d and 90d
  *checkpoints on the same trajectory*, not as disjoint buckets. 90d is the
  harder "this isn't going to merge" signal; 30d is the early-warning
  checkpoint.
- `closed_by_us` — we abandoned it via operator decision

**"Maintainer engagement"** (resets the staleness clock) = any
maintainer-actor activity on the PR: comment, review, requested-changes,
status change, label change, milestone assignment. Automated bot activity
does not count.

The gate's job is to maximize `merged` and minimize the stale-open and
closed-unmerged categories. Internal gates passing is a *necessary* condition
for shipping but not a *sufficient* condition for success. Without
outcome-level data we can't tell if any change to the pipeline helps —
hence Phase 0 (below) must ship before Phase 3.

**Baseline.** Snapshot the May 2026 23-pass cohort's current upstream
status before any Phase 1+ work lands; this is the comparison point for any
gate-effectiveness claim later.

## High-level architecture

```
hadoku-scrape  →  KV  →  hadoku-aggregator  →  tenhands
   (Phase 1)            (Phase 2)              (Phase 3)
                                               ↑
                                  Phase 0 (telemetry, ships in parallel)
```

Phase 0 is the prerequisite that makes the overhaul measurable. Phases 1–3
are each independently shippable; Phase 0 runs in parallel with Phase 1
so a calibration corpus exists by the time Phase 3 needs one.

## Effort sizing (rough, solo operator)

| Phase | Estimate | Notes |
|---|---|---|
| Phase 0 | 1–2 days critical (a+b) + ~1 day non-blocking (c) | (a) outcome poller + (b) structured override codes gate Phase 3 calibration; (c) uniform gate telemetry can slip post-Phase-3 |
| Phase 1 | 3–5 days | Scraper Tier 0/1 reorganization + comment-coverage expansion + new Tier 3 fields |
| Phase 2 | 2–3 days | New ExtendedIssue fields plumbed through, readiness score endpoint |
| Phase 3 | 5–8 days | Backfill validation (1–2d), gate + rubric (3–5d), tuning ongoing. **Assumes the agent-instruction-adoption bug (see "Out of scope") is fixed before or alongside — without it, the structured evidence output never reaches the SWE agent and the dual-purpose contract collapses.** |

Phase 0 + Phase 1 in parallel → Phase 2 → Phase 3 backfill → Phase 3 ship.
Calibration is ongoing after ship; Phase 0 telemetry feeds it.

---

## Phase 0: Telemetry prerequisites

**Goal:** put the measurement infrastructure in place before the overhaul
that depends on it. Without these, any later "did the gate help?" question
is unanswerable.

### What ships

**(a) Upstream PR outcome tracking — historical + ongoing.**

tenhands already polls dispatched PR state via `watch_upstream_pr_state`
(test coverage in `backend/tests/temporal/test_activities.py`:
open / merged / closed-unmerged / blocking-review / review-dedupe). The
extension: a **standalone cron-driven activity** that crawls every recorded
upstream PR URL across all evidence dirs, classifies state, and writes back
to evidence. Works on historical / terminal dispatches without re-entering
their workflows.

Poll cadence: ~daily is enough; PR state doesn't change minute-by-minute.
ETag-conditional via the existing `_get_with_etag` infra keeps the cost
near-zero for stable PRs.

Polling beats webhooks for this workload: volume is tens of PRs, no public
endpoint / secret / signature-verification infra needed, backfill works on
historical PRs with zero setup. Operator-marks-it is actively wrong —
relies on discipline that won't give us retrospective signal, which is
exactly the corpus the rubric needs.

**(b) Structured operator override capture.**

Today an operator can approve / abort / retry a deferred run via the inbox
signal endpoint. The reason is free text (or absent). Replace with a
structured field: `{decision, reason_code, reason_text}` where `reason_code`
is a constrained vocabulary tuned over time. Initial codes:

- `approve_clean` — preview PR looks good as-is
- `approve_after_edit` — edited the preview PR, then approved
- `abort_scope_mismatch` — issue's actual scope ≠ what we worked on
- `abort_quality` — fix is wrong / partial / unsafe
- `abort_active_upstream` — someone else already has a PR
- `abort_stale_issue` — issue is dead / wrong version / closed-elsewhere
- `abort_other` — escape hatch, with free-text required

Codes evolve; the point is making override reasons *queryable* from day one
so the calibration corpus is rich enough to tune the actionability rubric
against.

**(c) Per-gate decision telemetry.** *(Non-blocking — nice-to-have for
funnel analysis but not required for Phase 3 calibration. May slip
post-Phase-3.)*

Beyond pass/fail, capture for every gate: the gate name, verdict, score
(where applicable), evidence cited (where applicable), and the decision
timestamp. Already partially present in `submission_judge.json`; extend to
every gate uniformly so funnel analysis is one query, not a state-tree walk.

### Phase 0 tasks

- [ ] Standalone outcome-snapshot activity: cron-driven, walks evidence
      dirs, polls upstream PR URL, classifies state, writes
      `outcomes/<batch>/<issue>/upstream_state.json`. Extends
      `watch_upstream_pr_state` for the out-of-workflow case.
- [ ] Snapshot the May 2026 23-pass cohort's current upstream status — this
      is the historical baseline.
- [ ] Replace the inbox-signal free-text reason with the structured
      `reason_code` vocabulary above. Frontend dropdown + backend validation.
- [ ] *(non-blocking)* Uniform gate-decision evidence: every gate writes
      `<batch>/<issue>/gate_decisions/<gate_name>.json` with
      `{verdict, score?, reasoning, evidence, at}`.
- [ ] *(non-blocking)* Backfill the existing batches' gate decisions into
      the uniform shape so historical analysis works without special cases.

### Phase 0 open questions

- **Override-reason vocabulary tuning cadence.** Quarterly review? After
  every 50 overrides? Lean: review when the `abort_other` rate climbs
  above 20% — that's a signal codes are missing.
- **Should outcome polling re-run forever, or stop at a final state?**
  Lean: stop at `merged` or `closed_unmerged`; keep polling `open` until
  90d stale; then move to "indexed for retro only" and stop polling.

---

## Phase 1: Scraper tiered enrichment

**Goal:** spend GH-API budget on issues we might actually dispatch against,
capture richer state (timeline, comment threads, sub-issues) for those.
Tier 0 is *scraper-side budget protection that prevents the scraper from
spending API on issues we'd reject downstream anyway* — not a new
filtering layer.

### Current state (2026-05-24)

Cited from `hadoku-scrape/hadoku_scrape/scrapers/ossrecon/`:

- `ExtendedIssueFetcher` (`fetchers/issues.py`): lists top-100 open issues
  per repo by `updated`, then for **every** issue fetches Timeline (linked
  PRs) and conditionally last-comment metadata.
- `CommentThreadFetcher` (`fetchers/comments.py`): full comment threads for
  `max_comment_threads=20` issues per repo, selected by thumbs-up + recency.
- Rate-limit-aware: `_check_rate_limit` adapts to `X-RateLimit-Limit`,
  pauses near `rate_limit_floor=100` (`fetchers/base.py:233`).
- ETag conditional requests via `_get_with_etag`. 304s **do not count
  against the primary rate limit** (per GitHub docs).
- Retry: 403 org-token retry + 5xx exponential backoff.

### GH API constraints

Per GitHub's documented rate-limit semantics (worth re-verifying before
implementation):

- **REST primary:** 5,000 req/hr authenticated, ~1.39 req/sec sustained.
- **Search API:** separate 30/min bucket — strict. Avoid; we don't use it.
- **GraphQL:** complexity-based, 5,000 points/hr default. Useful for
  graph-shaped queries; complexity scales with field count.
- **Secondary rate limits:** concurrent requests (~100 max), abuse
  heuristics. Read-only sequential GETs are safe.
- **304 Not Modified:** does NOT count against primary rate limit.
  Conditional requests via `If-None-Match` are effectively free for
  unchanged resources.
- GitHub cares about **both** request count AND complexity (GraphQL); for
  REST GETs count is the binding constraint.

### Tier design — relationship to eligibility

**Important:** the existing tenhands eligibility gate
(`backend/temporal/gates/eligibility.py:43–49`) already checks
`issue.assignee` and `state == open`. Tier 0 below is NOT new filtering —
it's a scraper-side mirror of the consumer-side checks, applied earlier so
we don't enrich issues we'd reject anyway. Both layers exist deliberately
and must stay in sync (decision-log entry below).

### Tier 0 — free filtering at list time

Every field is already in the `/issues?state=open` response payload, so
this costs **zero** additional requests:

| Reject condition | Rationale |
|---|---|
| `assignees.length > 0` | Someone is already on it (mirrors eligibility) |
| `labels` ∈ `{wontfix, duplicate, invalid, tracking, epic, rfc, blocked, on-hold}` | Maintainer-signalled non-actionable |
| `updated_at` > 18 months ago | Cold; abandoned or punted |
| Title starts with `RFC:`, `[Epic]`, `[Tracking]`, `Discussion:` | Coordination, not work |

**Thresholds marked "instrument first, set second":**

| Reject condition | Rationale |
|---|---|
| `body.length < N` chars | Low signal (template-only / "+1") — N TBD from real distribution |
| `comments` count > repo-p95 × M | Epic-shaped — M TBD from real distribution |

Pick `N` and `M` after one cron cycle of instrumentation, not by guess.

### Tier 1 — per-issue enrichment, only for Tier-0 survivors

Same calls scraper makes today (`/timeline`, last-comment), gated by Tier 0
pass:

| Reject after Tier 1 | Rationale |
|---|---|
| Any open linked PR on `/timeline` | Someone shipping; we'd collide |
| Closed linked PR < 90 days ago | Recent attempt failed; needs human read |

### Tier 2 — full comment thread, only for Tier-1 survivors

Currently capped at 20 most-engaged per repo. **Proposal:** drop the
engagement cap; fetch threads for every Tier-1 survivor — that's the
population we might actually dispatch against. Bounded by Tier 0+1 filters.

### Tier 3 — sub-issues + recent timeline events

New work. The sub-issues panel is a recent GitHub feature (REST
`/issues/{n}/sub_issues` or GraphQL `subIssues` connection). Recent
timeline events (label changes, title changes, team reassignments) live on
`/timeline` but the scraper only extracts cross-references today.

**Sub-issue confound noted.** `subIssues.count` partly measures whether the
repo *adopted* the sub-issues feature. Older or feature-non-adopting repos
can be epic-shaped with zero sub-issues. Mitigation: treat sub-issue count
as a *strong* signal where present, and treat `epic` / `tracking` /
`umbrella` labels and a comment-mention pattern (`> 5 distinct
maintainers debating scope`) as *parallel* signals. Not "paired" — these
are independent OR'd indicators of epic shape.

### Cost framing

Per-repo request count stays comparable to today (≈170 req/repo).
**Savings aren't the point.** What changes is *data quality on the
population that matters*: comments cover every dispatch candidate (not
just top-20 engaged), sub-issues + recent timeline events are captured.
Downstream gates have better evidence to work with.

### Phase 1 tasks

- [ ] Implement Tier 0 filter in `ExtendedIssueFetcher.fetch()` before
      per-issue calls.
- [ ] Drop `max_comment_threads` engagement cap; fetch comments for all
      Tier-1 survivors.
- [ ] Add Tier-3: sub-issue count + recent timeline-event summary as new
      `ExtendedIssue` fields.
- [ ] Persist Tier-0 reject reasons to a new KV namespace
      `recon:{slug}:rejects` for operator audit. *(New shape — no precedent
      in scraper today; repo-level `recon:{slug}` exists, per-issue
      rejection is new.)*
- [ ] Instrument body-length and comment-count distributions for one cron
      cycle before setting Tier-0 thresholds. **Lifecycle:** during
      instrumentation, capture `body_length` and `comment_count` on every
      issue (as fields on the keep-or-reject record), but only enable
      Tier-0 rejection on the deterministic rules (assignees, labels, age,
      title prefix). Add the size-based rejects after one cycle once
      thresholds are data-driven.
- [ ] Verify ETag cache survives Tier reorganization (304 hits should
      still short-circuit per-issue enrichment).
- [ ] Telemetry: per-tier survival counts per repo.

### Phase 1 open questions

- **Comment-thread coverage for dispatch tail.** If a Tier-0 survivor has
  zero comments at scrape time but accumulates a debate before dispatch,
  we miss it. Mitigation: gate-time freshness re-fetch in Phase 3.
- **Sub-issues endpoint stability.** Recent feature; endpoint may move.
  Pin to REST and accept some breakage risk, or use GraphQL `subIssues`
  for stability at higher complexity cost?
- **Recent-timeline-event extraction.** Whitelist event types (label,
  title, cross-reference, transferred) or capture all and filter at
  aggregator time?

---

## Phase 2: Aggregator scoring + brief enrichment

**Goal:** expose the richer Tier-3 fields downstream, and add a
deterministic *cost-control circuit-breaker* score so tenhands can
make obvious rejects without an LLM round-trip. The aggregator's score is
**not** a competing intelligence layer — its job is cheap, conservative,
low-false-negative on obvious bads. LLM judgment lives in tenhands.

### CVS vs readiness — explicit boundary

Both signals exist, both are canonical for their consumer, and they
overlap intentionally on the competition axis. Document the overlap;
don't dedupe.

| Signal | Question it answers | Time horizon | Consumer |
|---|---|---|---|
| **CVS** (Contribution Viability Score) | Should we ever look at this issue? | Slow — backlog filter | Aggregator's scored-issues sort |
| **Readiness** (dispatchReadinessScore) | Can we dispatch on it *right now*? | Fast — volatile | Tenhands's pre-dispatch gate |

The competition axis (no linked PR, not assigned) is in both deliberately:
it gates backlog inclusion (don't show in scored-issues if someone else has
a PR) AND dispatch (don't dispatch even if backlog-eligible). Same signal,
different decision points.

### Current state

From `hadoku-aggregator` (per the API contract in `tenhands/CLAUDE.md`):

- `/recon/{slug}/issue-brief/{id}` — issue + repoHealth + brief
- `/recon/{slug}/scored-issues` — ScoredIssue[] with CVS
- `/recon/{slug}/dossier` — 6-section markdown
- `linkedPrUrls` already present on ExtendedIssue
- CVS = Contribution Viability Score (0–100), weighting freshness,
  activity, content quality, competition (no linked PR / not assigned),
  complexity bonus (`issue-scorer.ts`).
- Comment-digest exists internally (`comment-digest.ts`) but feeds CVS;
  **does not appear in the 6-section dossier**.

### New ExtendedIssue fields (from Phase 1 scraper output)

```
subIssues: { count: int, open: int, closed: int }
recentTimelineEvents: [{ event: str, actor: str, at: iso8601, detail: str }]
commenterMix: { count: int, distinct: int, maintainers: int }
```

### New aggregator-computed field: dispatchReadinessScore

**Penalty-only formula** — score reflects "how bad is the evidence." This
is a cost-control circuit-breaker, not a full assessment; positive signals
(reward) belong to the LLM tier in tenhands.

```
score = 1.0
- 0.30 × (subIssues.count >= 5 OR labels ∩ {epic, tracking, umbrella})
- 0.30 × (any linked PR is open)
- 0.20 × (recentTimelineEvents has team_reassigned in <30d)
- 0.15 × (commenterMix.maintainers >= 3)
- 0.10 × (updatedAt > 12 months ago AND comments > 0)
- 0.10 × (title changed in <90 days)
clamp [0, 1]
```

No `+0.10 good first issue` bonus — CVS already captures that via its
complexity bonus; duplicating it in readiness is double-counting.

**Weights are intentional first guesses, not calibrated values.** Expect
them to shift once Phase 0 telemetry has enough signal to back numeric
tuning. The formula reads as commitments; treat the numbers as starting
points pending real data.

`dispatchReadinessFlags` = list of triggered rules, surfaced to operators.

### New endpoint

`/recon/{slug}/dispatch-readiness/{id}` →
`{ score, flags, signals: { subIssues, recentTimelineEvents, commenterMix, ... } }`.
Computed on read (cheap), not baked into KV.

### Phase 2 tasks

- [ ] Plumb new ExtendedIssue fields end-to-end (scraper → KV reader →
      API response).
- [ ] Implement `dispatchReadinessScore` + flags (penalty-only, formula
      above).
- [ ] Add `/recon/{slug}/dispatch-readiness/{id}` endpoint.
- [ ] Document the rubric in `hadoku-aggregator/docs/`.
- [ ] **No calibration** of weights at this stage — weights are intentional
      first guesses tied to the cost-control circuit-breaker framing.
      Calibration happens once Phase 0 outcome telemetry has signal.

### Phase 2 open questions

- **Score vs. flags first.** Both, with score for the fast circuit-break
  and flags for the LLM judge's signal summary.
- **Reactivity.** Re-compute on read (already chose), not baked. Daily-cron
  scraper data + on-read aggregator math + dispatch-time re-fetch (Phase 3)
  = three-layer freshness model.

---

## Phase 3: tenhands actionability gate

**Goal:** insert an `actionability` gate after eligibility, before fork.
Two-tier: deterministic circuit-break from aggregator signals, LLM judge
for the middle band. Output is **structured evidence with severity tiers**
— dual-purpose for the gate decision AND for downstream SWE agent
briefing (same artifact, two consumers; shape shared, aggregations may
diverge).

### Gate-zero validation (BEFORE any production wiring)

The single cheapest way to know if the rubric has signal is to backfill
it on dispatches whose outcomes we know. **Do this first.** If the rubric
can't separate the 23 historical passes by upstream outcome, no amount of
plumbing fixes that.

Validation sequence:

1. **Prompt smoke test (~5 issues).** Pick a handful from the 23 — keycloak,
   a known clean merger, an open-but-stale, one with an active maintainer
   debate. Run the rubric, eyeball the structured evidence output. Goal:
   catch obvious prompt failures (judge ignores the comment thread, judge
   fabricates "blocking" evidence, judge always returns the same score)
   before committing to the full backfill.
2. **Full 23-issue backfill.** For each:
   - Pull current upstream PR state (Phase 0 outcome data)
   - Pull current upstream issue state
   - Run actionability_v1 retrospectively using ORIGINAL brief + FRESH
     comment thread
   - Bin by retrospective verdict (pass/defer/fail) × actual outcome
3. **Decision:**
   - Uniform verdict distribution across outcomes → rubric has no signal;
     iterate the prompt
   - Clear separation (fails correlate with stale/closed-unmerged, passes
     with merges) → ship and tune in production
   - Mixed → tune rubric weights then re-run

The keycloak case is the canary: the rubric MUST classify it as `fail`
or `defer` given the sub-issue count + comment-thread evolution. But it's
**one case in the backfill**, not the rubric's validation pivot.

### Freshness re-fetch — mandatory gate step

The brief is **frozen** at eligibility time (`activities/eligibility.py:125`).
The actionability gate cannot rely on it for volatile state. Before any
judgment runs, the gate fetches LIVE:

- Current comment thread (since-eligibility delta minimum)
- Current sub-issue count
- Current linked-PR state

~1 GH call per dispatch. Confirmed cheap.

### Tier A — deterministic circuit-breaker (no LLM)

Reads aggregator's `dispatchReadinessScore` + flags. The score below is the
**aggregator's deterministic score**, not the LLM judge's score — different
threshold systems that happen to share the 0.40 / 0.70 bands. Don't conflate.

```
Aggregator deterministic score → routing:

score >= 0.70 AND no critical flag      → Tier B (LLM judge runs)
score <  0.40 OR  has critical flag     → fail (don't dispatch)
otherwise                                → Tier B (LLM judge runs)
```

**Tier A only short-circuits at the FAIL end.** It never auto-passes — the
LLM always weighs in unless the deterministic signals already say "fail."
This avoids Tier A blind spots in the pass column (the column we care
about). Cost: every dispatch gets one LLM call; trade we make for the
silent-pass column being the actual target.

**Critical flags (binary, single-occurrence triggers fail):**

- `active_open_pr` — someone is already shipping
- `explicit_maintainer_block` — maintainer said "don't"
- `maintainer_punted_to_future_milestone` — explicit "next release / RFC"

Everything else is graded evidence the LLM weighs, not a hard flag.

### Tier B — LLM scope-judge (receptiveness framing)

The judge answers ONE question: **will the maintainer merge a clean PR
against this issue today?** Not "is this solvable" — solvability is
necessary but not sufficient. The actual question is upstream receptiveness.

#### Inputs

- Issue body (from frozen brief)
- Full comment thread (fresh, from gate-time re-fetch)
- Aggregator signal summary (flags, score, recent timeline)
- Repo CONTRIBUTING.md (for "good first issue" / "we accept PRs from
  strangers?" framing if present)

#### System prompt (draft v0)

```
You are evaluating whether a GitHub issue is ready for an upstream PR from
an AI coding agent. You receive: the issue body, the full comment thread,
a structured signal summary, and the repo's CONTRIBUTING.md if available.

Answer ONE question: will the maintainer merge a clean PR against this
issue today? You are NOT judging whether the bug is real, severe, or
worth fixing — only whether a competent agent's PR has a path to merge
in the issue's current state.

Penalize (in roughly decreasing severity):
- An open PR already linked to this issue from someone else (blocking)
- Maintainer explicitly said "wait" / "punt to <milestone>" / "RFC first" (blocking)
- Active design debate among maintainers with no acked direction (strong)
- Sub-issue tree or "tracking" labels — this is coordination work, not a PR (strong)
- Title changes or scope expansion in comments (strong)
- A pending rename / refactor that will require this PR to be rebased (strong)
- Original reporter has abandoned the thread; maintainer asked clarifying
  questions and never got answers (weak)

Reward:
- Specific reproducible bug with a failing test or clear repro steps
- Maintainer alignment on the fix direction acked in comments
- Small, well-bounded surface area
- "good first issue" / "help wanted" alignment in the labels
- Active recent maintainer engagement with the reporter

Output ONLY this JSON structure:

{
  "verdict": "pass" | "defer" | "fail",
  "score": 0.0-1.0,
  "evidence": [
    {
      "signal": "short descriptor",
      "severity": "blocking" | "strong" | "weak",
      "direction": "penalty" | "reward",
      "quote": "exact comment / body text quoted",
      "comment_author": "GitHub username or 'issue_body'",
      "at": "ISO8601 timestamp or 'issue_body'"
    }
  ],
  "reasoning": "1-3 sentences citing the strongest evidence"
}

Severity definitions (you apply these consistently):
- blocking: single occurrence triggers fail verdict
- strong: 2+ triggers fail; 1 triggers defer; affects score heavily
- weak: contributes to score but never alone triggers fail
```

#### Structured evidence — dual-purpose contract

Same `evidence[]` shape is consumed by **two** downstream systems:

1. **The gate decision** aggregates evidence by severity to compute the
   verdict (severity rules above).
2. **The downstream SWE agent's briefing** (when verdict = pass and we
   dispatch) lifts the evidence into the agent's context: "the maintainer
   has been pushing back on X; address it explicitly in the PR body." The
   same artifact that determined we should dispatch tells the agent how to
   dispatch *well*.

**Shape is shared, aggregations may diverge.** If gate logic evolves in
v2, the agent briefing may keep consuming the same evidence shape. Document
that the contract is the shape, not the consumer logic.

### Thresholds (initial, tune from Phase 0 corpus)

The score below is the **LLM judge's score** from Tier B (a different
threshold system than Tier A's aggregator-deterministic score above —
same numbers, different inputs, don't conflate).

| LLM judge score → verdict | verdict | action |
|---|---|---|
| `>= 0.70` | pass | proceed to fork |
| `0.40–0.70` | defer | inbox with evidence + reasoning; operator decides |
| `< 0.40` | fail | reject, write `01-eligible/actionability_reject.md`, no fork |

**Do not inherit submission_judge's 0.55/0.75.** Those thresholds have no
empirical backing — unchanged since the initial commit, never tuned. Build
actionability's calibration corpus from Phase 0 outcome telemetry, then
tune.

Start conservative: bias toward `defer` rather than `fail` for the first
batches. We see what's getting caught, the structured override telemetry
tells us why, then we tighten.

### Phase 3 tasks

- [ ] **Gate-zero validation:** prompt smoke test on ~5 issues, then full
      backfill on the 23 historical passes. **No gate code lands until
      this validates.**
- [ ] New rubric file: `backend/temporal/judge/rubrics/actionability_v1.md`
      (the prompt above, formalized).
- [ ] New gate: `backend/temporal/gates/actionability.py`, after
      eligibility, before fork.
- [ ] Freshness re-fetch helper that pulls live comment thread +
      sub-issue count + linked-PR state at gate execution time.
- [ ] Tier A (deterministic) implementation reads aggregator signals.
- [ ] Tier B (LLM) implementation reuses existing `judge.py` infrastructure
      — confirmed pluggable, the relevance gate is the precedent at
      `gates/fix.py:89`. Actionability is a drop-in rubric, no judge
      changes needed.
- [ ] Evidence output validation: enforce JSON schema, reject malformed
      outputs (defer with `system:judge_parse_error` if schema fails).
- [ ] Inbox surface: render `evidence[]` with severity coloring across
      all three surfaces (Discord, web UI, disk marker) — payload
      already structured.
- [ ] Downstream agent briefing: when verdict = pass, pass `evidence[]`
      into the agent context. (Coupled to the agent-instruction-delivery
      issue tracked separately — see "Out of scope" below.)
- [ ] **Regression test** (in addition to the backfill, not in place of it):
      replay keycloak#46523's actual state through the gate and assert
      `fail` verdict citing the sub-issue count + scope expansion evidence.
      The backfill remains the validation pivot; this is a regression
      check so the keycloak case can't silently regress.

### Phase 3 open questions

- **Sample-skip the LLM call once calibration is trusted?** Plan as
  written: every dispatch outside Tier A's fail zone gets one LLM call
  (there's no Tier A pass zone — Tier A only short-circuits at fail).
  Cheaper alternative once the rubric is reliable: 1-in-N audit-only
  LLM calls. Lean: every-call for v1; revisit after the first 100
  dispatches of production data.
- **Operator override re-dispatch.** When an operator overrides a defer
  and re-dispatches, do we bypass the gate or re-run it? Lean: bypass
  for that dispatch, log the override decision into the calibration
  corpus.
- **Cost model.** Currently using OAuth-style requests, not pay-as-you-go
  metered API. Pricing analysis deferred — designing for correctness
  first, will revisit gate aggressiveness once cost shape is known.

---

## Validation: Retrospective backfill

**This is the only validation that counts before ship.**

Run the actionability_v1 rubric retrospectively against the 23 May 2026
internal-pass dispatches. For each, we have:

- Original brief at dispatch time (preserved in evidence)
- Original gate decisions (Phase 0 backfilled into the uniform shape)
- Current upstream PR + issue state (Phase 0 outcome poller)
- Fresh comment thread at validation time

The rubric runs on the original brief + fresh comment thread (so it sees
the post-dispatch evolution, which is exactly the keycloak signal).

**Pass criteria for shipping:**

- Rubric distinguishes `merged` outcomes from `open_stale` (at the 90d
  checkpoint) / `closed_unmerged` outcomes
- Sensitivity: how often does it fail something that actually merged?
  Target < 25% false-fail rate (we'd rather miss a merger than burn
  cycles on a non-merger, but not by a huge margin)
- Specificity: how often does it pass something that went stale?
  Target < 50% false-pass rate (better than the current ~all-pass rate)

If the rubric clears these bars on the 23-issue retrospective, ship. If
not, iterate the prompt and re-run.

**Keycloak is one data point, not the validation pivot.** Designing rules
*against* keycloak then validating *against* keycloak is circular. The
retrospective is the honest test.

---

## Out of scope

- **Agent-instruction-adoption bug from 2026-05-22.** When the workflow's
  `request_fix` / `request_verify` phases adopt the existing repro context
  issue (per the batch-scoped adoption logic), the fix/verify instructions
  never reach Copilot — only the repro instruction is ever delivered.
  This is a real bug affecting `fix_summary.md` / `test_command.txt`
  delivery and verification-phase quality. **Tracked separately.** It
  interacts with Phase 3's downstream agent briefing (whatever evidence
  we pass into the agent context only matters if it actually reaches the
  agent), so resolve before / alongside Phase 3 ship.
- **Per-repo prompts.** Deferred indefinitely; revisit when we have
  enough repeat-repo volume to justify the maintenance cost.
- **Upstream PR submission UX changes.** Tracking PR state is in scope
  (Phase 0); UX changes to the operator's submission flow remain out.
- **Frontend changes** beyond the new inbox-defer-with-evidence rendering.

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-24 | Three-phase split (scraper → aggregator → dispatch) + Phase 0 parallel | Each phase shippable independently; Phase 0 makes the whole thing measurable |
| 2026-05-24 | Lazy at dispatch, eager at scrape (raw data only) | Bounded per-dispatch cost; staleness penalty acceptable for raw data; intelligence happens lazily |
| 2026-05-24 | Aggregator score is a hint, not a verdict | Preserves "aggregator computes evidence, tenhands decides" boundary |
| 2026-05-24 | Backfill rubric on historical passes BEFORE any gate code | Cheapest sanity check; if no signal in retrospective, plumbing won't save it |
| 2026-05-24 | Polling > webhooks for upstream outcome tracking | `watch_upstream_pr_state` already exists; volume doesn't need webhook infra; backfill works without setup |
| 2026-05-24 | Don't model actionability calibration on submission_judge | submission_judge thresholds (0.55/0.75) unchanged since `2ffa3cd` — never tuned. Build override + outcome telemetry from day one |
| 2026-05-24 | Success metric is upstream PR outcomes, not internal pass rate | The silent-pass column is the actual problem; internal gates passing doesn't measure success |
| 2026-05-24 | Tier 0 and eligibility-gate rules share a canonical source | Both layers exist deliberately (scraper budget vs consumer check); must stay in sync |
| 2026-05-24 | CVS and readiness are orthogonal-but-overlap on the competition axis | Same signal serves different decision points; document the duplication rather than dedupe |
| 2026-05-24 | Brief is frozen at write; gate must actively re-fetch volatile fields | `activities/eligibility.py:125` snapshot is the post-eligibility source of truth; volatile state needs fresh fetch |
| 2026-05-24 | Aggregator computes deterministic signals + cost-control score; tenhands judge owns LLM intelligence | Clean boundary: aggregator does cheap math, tenhands does nuanced judgment |
| 2026-05-24 | Judge output is structured evidence with severity tiers | Dual-purpose: gate decision + downstream SWE agent briefing |
| 2026-05-24 | Critical-flag list is short and binary | `active_open_pr`, `explicit_maintainer_block`, `maintainer_punted_to_future_milestone` only — everything else is graded |
| 2026-05-24 | Reframe judge prompt around upstream receptiveness, not internal solvability | Solvability is necessary but not sufficient; the actual question is merge-ability |
| 2026-05-24 | Drop `+0.10 good first issue` bonus from readiness score | CVS already captures it via complexity bonus; double-counting |
| 2026-05-24 | Sub-issue count is one of three OR'd epic-shape signals | Feature-adoption confound; pair with labels (epic/tracking/umbrella) and maintainer-debate patterns |
| 2026-05-24 | Body-length and comment-count thresholds: instrument first, set second | Don't commit numeric thresholds before seeing real distributions |
| 2026-05-24 | Cost model deferred | OAuth-style requests, not metered API. Design for correctness now; revisit aggressiveness once cost shape known |
| 2026-05-24 | Reporter-abandonment severity stays "weak" in the default judge prompt | The LLM judge has latitude to upgrade severity per case via structured evidence; over-specifying in the system prompt biases away from context-driven grading. Reasonable to disagree — 1-word change either way |
| 2026-05-24 | Phase 0(c) uniform gate telemetry is non-blocking | Outcome tracking (a) and structured override codes (b) are what Phase 3 calibration needs; (c) is funnel-analysis nice-to-have, can slip post-Phase-3 |
