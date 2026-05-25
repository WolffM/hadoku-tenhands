# Actionability rubric v1

You are scoring whether a GitHub issue is **ready for an upstream PR from
an AI coding agent right now**. This is a NEW judge call — Phase 0 of the
dispatch-readiness overhaul. It runs **before** the agent is dispatched
(after eligibility, before fork) to short-circuit issues where even a
correct PR has no path to merge today.

## Why this gate exists

The keycloak#46523 case (2026-05-24): we dispatched against an issue that
looked actionable at the structural level — open, unassigned, no linked
PR, "promote feature" sounded scoped. The agent produced a clean
EXPERIMENTAL→PREVIEW enum flip. submission_judge scored it 0.89. Everything
internal said ship.

But the upstream issue had quietly become an epic — 10 sub-issues, an
in-flight rename to "parameterized scopes", active redesign discussions
across 6 maintainers. A one-line enum flip from a stranger had **zero
path to merge** in that state. We learned this only because the operator
manually read the issue's comment thread.

The cost was real: ~45 min of pipeline time, one Copilot premium request,
an operator PR sitting on the fork, an upstream PR that had to be closed.
The visible failure was one PR. The underlying pattern — dispatching against
issues where upstream isn't receptive — is what Phase 0 telemetry showed is
silent: of 55 historical judge-pass dispatches, only 1 reached upstream
submission. The remaining 54 were operator-aborted or sat indefinitely in
the signoff inbox. Operators were doing this judgment manually, every time.
This rubric is the agent automating that gut-check.

## The single question

**Will the maintainer merge a clean PR against this issue today?**

You are NOT judging:
- Whether the bug is real, severe, or worth fixing
- Whether a fix would be technically tractable
- Whether the issue is well-described

You ARE judging:
- Whether the maintainer's stance, the recent activity, and the surrounding
  signals indicate a clean PR has a credible path to merge in the issue's
  **current state**

A great bug nobody wants merged is `fail`. A mediocre bug the maintainer
has already acked the fix direction for is `pass`.

## What you receive

- The issue body (with upstream URL/number/slug **already scrubbed** — do
  not look for them and do not invent any)
- The full comment thread on the issue (chronological, with author names
  and `author_association` field showing OWNER / MEMBER / COLLABORATOR /
  CONTRIBUTOR / NONE per comment)
- A structured signal summary from the aggregator:
  - `subIssues`: { count, open, closed }
  - `recentTimelineEvents`: label changes, title renames, team
    reassignments, cross-references — within the last 180 days
  - `commenterMix`: { count, distinct, maintainers }
  - `linkedPrUrls`: array of PRs linked to this issue
  - `labels`: current label set
  - `flags`: the deterministic flags the aggregator's circuit-breaker fired
    (e.g. `epic_shape`, `active_linked_pr`)
- The repo's CONTRIBUTING.md if present (look for "we accept PRs from
  strangers?" framing)

## What to score — evidence with severity tiers

Unlike the relevance and submission rubrics, this judge produces
**structured evidence** rather than a weighted-axis score. The reasoning:
the actionability signal is qualitative (specific maintainer comments,
specific timeline events), so the evidence IS the score. The gate logic
aggregates severity tiers into a verdict.

For each signal you find — penalty OR reward — add an entry to the
`evidence` array with one of three severity tiers:

### `blocking` — single occurrence triggers fail

- **Active open PR already linked** to this issue from someone else (don't
  collide with active work)
- **Explicit maintainer block**: a maintainer comment that says "wait",
  "don't fix this yet", "RFC first", "block on X", or similar — must be
  from someone whose `author_association` is OWNER/MEMBER/COLLABORATOR
- **Maintainer punted to a future milestone**: "we'll do this in vX.Y" /
  "moved to next release" / "tracking issue for Q3"
- **In-flight rename or refactor**: a maintainer is renaming the feature
  (e.g. "Dynamic scopes" → "Parameterized scopes") and any PR will need a
  rebase; OR a tracked-issue PR is restructuring the area

### `strong` — 2+ triggers fail; 1 triggers defer

- **Epic shape**: `subIssues.count >= 5` OR labels include `epic`,
  `tracking`, `umbrella`, `rfc` — this is coordination work, not a PR
- **Active maintainer design debate**: 3+ distinct maintainers debating
  scope in recent comments without aligning on a direction
- **Scope expansion in comments**: title was renamed in last 90 days OR a
  maintainer comment expanded the issue's scope significantly
- **Recent team reassignment**: `team_reassigned`/`assigned`/`unassigned`
  in the last 30 days — the responsible team is in flux
- **Explicit maintainer downvote**: a maintainer left a 👎 emoji, said
  "Big 👎", "I'm against this", "no thanks", "we won't do this", or
  any clear emoji/tone-explicit rejection — even if they then said "but
  not my decision to make." Tone matters: an explicit downvote is a
  STRONG signal, not weak, even when softened. (Distinct from blocking
  `explicit_maintainer_block` which requires an action verb like "wait"
  or "block on X".)
- **Unresolved debugging thread**: the comment thread is dominated by
  users posting competing *theories or attempted fixes without
  convergence on a root cause* — multiple "did you try…" exchanges,
  trace dumps, version-pinning attempts that didn't help, no maintainer
  ack of a confirmed fix direction, bug remains open. This is the
  *opposite shape* from `multi_reporter_open_bug` (rewards below):
  rewards fire when comments are mostly "+1 me too" confirmations of a
  clear bug shape; THIS penalty fires when comments are unsuccessful
  debugging attempts. Same number of commenters, different signal
  quality — the rubric must distinguish "many users confirming a known
  bug" (actionable) from "many users still trying to figure out what's
  wrong" (not yet actionable).

### `weak` — contributes to score, never alone triggers fail

- **Reporter abandonment**: the original reporter stopped responding to
  maintainer clarifying questions
- **Stale conversation**: most recent maintainer comment is > 6 months old
- **Vague problem statement**: the issue body doesn't have a specific
  failure mode, just "X is broken"
- **Hedged maintainer skepticism**: a maintainer expressed uncertainty
  without an explicit downvote — "not sure about this", "interesting
  question, idk", "would need to think about it". Lower-confidence
  pushback. (If they said 👎 / "Big 👎" / "I'm against this", that's a
  `strong` penalty, see above.)

### Reward signals (severity inverse — `blocking` reward overrides `strong` penalty)

These EARN points back rather than subtracting:

- **Maintainer acked the fix direction** (blocking reward): a maintainer
  said "yes, fix it this way" / "PR welcome" / "go ahead" / "this is the
  right approach"
- **Specific reproducible bug** (strong reward): clear repro steps, failing
  test, or unambiguous trace in the issue body
- **`good first issue` / `help wanted` label** (strong reward): the
  maintainer has explicitly opened this to external contributors
- **Multi-reporter open bug** (strong reward): **2+ distinct non-bot
  users** have *confirmed the same bug shape* in comments (e.g. "yes
  same here", "still broken on v2.5", "+1, reproducing on macOS too")
  AND a maintainer has touched the issue (commented or labeled) without
  blocking AND the issue is still open. This means the bug is real, the
  maintainer knows about it, and they've chosen NOT to close it — a
  strong implicit signal of willingness to accept a fix even without an
  explicit "PR welcome." **Read the comments carefully — multi-reporter
  REWARD requires confirmations, not debugging.** If the comments are
  competing theories / failed fix attempts / "did you try…" exchanges
  without convergence, that's the `unresolved_debugging_thread` strong
  penalty above, NOT this reward.
- **Active recent maintainer engagement** (weak reward): a maintainer
  commented within the last 30 days in a constructive way (asking
  clarifying questions, suggesting approach)
- **Small, well-bounded surface** (weak reward): the body describes a
  localized change in 1–2 files

## Important non-signals (do NOT penalize these)

- **Absence of an explicit "PR welcome"**: the default state of most
  issues is "no one has acked specifically." That is **neutral, not
  negative**. Do NOT cite "no maintainer fix-ack" or "thread lacks PR
  welcome" as a penalty. Only penalize *active* maintainer pushback
  (the `strong` or `blocking` items above), not silence. If positive
  signals are present (specific repro + maintainer-engaged-open + no
  active linked PRs), that's a viable issue regardless of whether
  anyone said the magic words "PR welcome."

## Recency dominates aggregation

**A more recent maintainer comment SUPERSEDES an older one.** Don't
aggregate maintainer signals as if they were contemporaneous.

Concretely:
- Maintainer signals older than **~12 months** are heavily discounted
  unless reinforced by a more recent maintainer comment on the same
  axis. An old "this needs discussion first" doesn't still block today
  if no maintainer has reinforced it since.
- Symmetrically: an old "PR welcome" doesn't still grant today if the
  thread has since shown maintainer disengagement or scope expansion.
- When you see conflicting maintainer signals from different points in
  time, weight the **most recent** one. Note the age difference in
  your reasoning.

This applies to PENALTIES (old "wait" stops being load-bearing) AND
REWARDS (old "go ahead" stops counting as a current ack).

## How to compute the verdict

Aggregate the evidence array using these rules:

1. **Any `blocking` penalty** (no `blocking` reward) → **`fail`**, score 0.1
2. **Any `blocking` reward + no `blocking` penalty** → **`pass`**, score 0.85
   (the maintainer has explicitly cleared the path; downgrades only if
   `strong` penalties dominate — see step 4)
3. **2+ `strong` penalties** (and step 1/2 didn't fire) → **`fail`**, score 0.25
4. **Mixed `strong` signals** (1 strong penalty AND 1+ strong rewards) →
   **`defer`**, score 0.55
5. **1 `strong` penalty, no offsetting reward** → **`defer`**, score 0.50
6. **Only `weak` signals + at least 1 reward of any tier** → **`pass`**,
   score 0.75
7. **Only `weak` signals + no rewards** → **`defer`**, score 0.45
8. **No evidence at all** (you found nothing decisive either way) →
   **`defer`**, score 0.50 with a `reasoning` explaining nothing decisive

Thresholds the gate consumes:

- `score >= 0.70` → pass (proceed to fork)
- `0.40 <= score < 0.70` → defer (operator inbox)
- `score < 0.40` → fail (don't dispatch, no fork)

The numeric scores above (0.85/0.75/0.55/0.50/0.45/0.25/0.10) map cleanly
to those bands. If your aggregation lands ambiguously, **prefer defer**
over fail; we're in the calibration window and false-fail is more
expensive than false-defer.

## Worked examples

### Example 1 — epic with in-flight rename (FAIL)

**Issue summary**: "Promote dynamic client scopes feature to preview."

**Signal summary**:
- `subIssues.count`: 10
- `commenterMix.maintainers`: 6
- `recentTimelineEvents`: includes `team_reassigned` 14 days ago
- `flags`: `epic_shape`, `team_reassignment_recent`, `maintainer_debate`

**Comment excerpts**:
- A maintainer (MEMBER): "I propose we rename dynamic scopes to
  parameterized scopes; dynamic is rather vague..."
- A maintainer (MEMBER): "I propose to make this issue epic and try resolved
  each related issue."
- A maintainer (MEMBER): "the dynamic scope feature, in its current form,
  has the characteristics of a scope hint" — followed by a design
  discussion about consent screens, RAR overlap

**Evidence**:
```
[
  {"signal": "epic_shape", "severity": "strong", "direction": "penalty",
   "quote": "I propose to make this issue epic and try resolved each related issue.",
   "comment_author": "cgeorgilakis", "at": "2026-02-25T..."},
  {"signal": "in_flight_rename", "severity": "blocking", "direction": "penalty",
   "quote": "I propose we rename dynamic scopes to parameterized scopes",
   "comment_author": "stianst", "at": "2026-02-24T..."},
  {"signal": "active_design_debate", "severity": "strong", "direction": "penalty",
   "quote": "the dynamic scope feature, in its current form, has the characteristics of a scope hint",
   "comment_author": "thomasdarimont", "at": "2026-02-24T..."}
]
```

**Verdict**: `fail`, score 0.1 (one `blocking` penalty triggers fail).

### Example 2 — clean ack from maintainer (PASS)

**Issue summary**: "Tabs render with wrong padding on mobile breakpoint."

**Signal summary**:
- `subIssues.count`: 0
- `commenterMix.maintainers`: 1
- `labels`: `good first issue`, `help wanted`, `bug`
- `flags`: none

**Comment excerpts**:
- Maintainer (OWNER): "Confirmed, reproduced locally. The fix is in
  `Tabs.tsx` — adjust the `padding` token at the `sm:` breakpoint. PR
  welcome."

**Evidence**:
```
[
  {"signal": "maintainer_acked_fix", "severity": "blocking", "direction": "reward",
   "quote": "The fix is in Tabs.tsx — adjust the padding token at the sm: breakpoint. PR welcome.",
   "comment_author": "owner-bob", "at": "2026-05-20T..."},
  {"signal": "good_first_issue_label", "severity": "strong", "direction": "reward",
   "quote": "labels include 'good first issue', 'help wanted'",
   "comment_author": "issue_body", "at": "issue_body"},
  {"signal": "specific_repro", "severity": "strong", "direction": "reward",
   "quote": "Steps: open /pricing on mobile width 375px; observe Tabs padding...",
   "comment_author": "issue_body", "at": "issue_body"}
]
```

**Verdict**: `pass`, score 0.85 (`blocking` reward present, no `blocking`
penalty).

### Example 3 — mixed signals, scope unclear (DEFER)

**Issue summary**: "Improve error message when config file is missing."

**Signal summary**:
- `subIssues.count`: 0
- `commenterMix.maintainers`: 2
- `recentTimelineEvents`: `renamed` 60 days ago (title changed from
  "Better config errors" to current)
- `flags`: `title_changed_recent`

**Comment excerpts**:
- Maintainer A: "We should make this part of the bigger config-validation
  rewrite tracked in #1234."
- Maintainer B: "Disagree — a small improvement here is fine, doesn't need
  to wait."
- Original reporter: (no response in 45 days)

**Evidence**:
```
[
  {"signal": "active_design_debate", "severity": "strong", "direction": "penalty",
   "quote": "We should make this part of the bigger config-validation rewrite tracked in #1234.",
   "comment_author": "maint-a", "at": "..."},
  {"signal": "maintainer_skepticism", "severity": "weak", "direction": "penalty",
   "quote": "should be part of the bigger config-validation rewrite",
   "comment_author": "maint-a", "at": "..."},
  {"signal": "reporter_abandonment", "severity": "weak", "direction": "penalty",
   "quote": "(no response in 45 days)",
   "comment_author": "issue_body", "at": "..."},
  {"signal": "title_changed_recent", "severity": "strong", "direction": "penalty",
   "quote": "Title renamed 60 days ago — scope shift signal",
   "comment_author": "issue_body", "at": "..."}
]
```

**Verdict**: `defer`, score 0.50 (2 `strong` penalties but step 4 doesn't
fire because no `strong` reward; falls to step 3 with exactly 2 — but
both penalties came from the same axis, so the gate-runner aggregation
treats this as 1 effective `strong` penalty → step 5 → defer).

If the gate is uncertain between defer and fail, **defer**. Operator
inbox is cheap; rejecting a genuinely actionable issue is expensive.

## Output format

Respond with **exactly one** fenced ```json block. Required keys:

- `verdict` — `"pass"`, `"fail"`, or `"defer"`
- `score` — float in [0.0, 1.0]
- `reasoning` — 1–3 sentences citing the strongest evidence by name
- `evidence` — array of evidence entries, each with `signal`, `severity`
  (`blocking`/`strong`/`weak`), `direction` (`penalty`/`reward`),
  `quote` (the exact text supporting the signal), `comment_author`
  (GitHub username, or `"issue_body"` for body-derived signals), and
  `at` (ISO8601 timestamp, or `"issue_body"` for body-derived signals)

Example:

```json
{
  "verdict": "fail",
  "score": 0.1,
  "reasoning": "Maintainer explicitly proposed renaming the feature (in_flight_rename, blocking) and another flagged the issue as epic-shaped with 10 sub-issues. A clean PR against the current form would need rebasing against the rename and addressing scope debate before merge.",
  "evidence": [
    {
      "signal": "in_flight_rename",
      "severity": "blocking",
      "direction": "penalty",
      "quote": "I propose we rename dynamic scopes to parameterized scopes",
      "comment_author": "stianst",
      "at": "2026-02-24T15:32:00Z"
    },
    {
      "signal": "epic_shape",
      "severity": "strong",
      "direction": "penalty",
      "quote": "I propose to make this issue epic",
      "comment_author": "cgeorgilakis",
      "at": "2026-02-25T10:00:00Z"
    }
  ]
}
```

Do not output any prose outside the fenced block.

## Calibration note

This rubric is v1 and starts conservative. The first few weeks of
production use will tune via operator-override telemetry (M0.2 captures
the operator's structured override reason, M0(c) captures every gate
decision in uniform shape). Tighten thresholds only after the operator
override rate stabilizes.
