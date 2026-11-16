# Trivia

The best facts about TenHands, each with its source.

## Beginnings

- The repo's first commit, on 2026-01-07, is titled, in full, "first commit"
  (`918a3e8`).
- It carried its original name, vibedispatch, for five months before being
  renamed TenHands in two commits on the same day — one for the brand, one
  because the public route prefix still answered to the old name
  (`12d5756`, `44970e0`).

## The batch that paid for everything

- jade-hare, March 13 to 17, 2026, dispatched 55 issues to real open-source
  repositories and merged exactly one of them upstream (`d185227`).
- The gate that catches an empty diff — a PR with no real change in it — is
  the single highest-ROI fix in the whole system: by itself it kills 21% of
  jade-hare's failure rate (`d185227`).
- Three of jade-hare's dispatches leaked a GitHub cross-reference
  notification to an upstream maintainer before any human had reviewed the
  work, which is the one specific failure the project built an entire
  isolation layer to make structurally impossible to repeat (`d185227`).

## taskauto's first day

- Its very first day in production, 2026-07-25, shipped seven unattended
  commits straight to this repo's own `main` — every one of them a
  dead-code cleanup. Each was gated on the full test suite passing against
  the merge result rather than the branch alone: `dee574a`, `a2956dc`,
  `0966641`, `b8afd1e`, `96f5366`, `41cbeb9`, `2c985b8`.
- The last of those seven was found by the scheduler with nobody prompting
  it at all (`2c985b8`).
- The project's own day-one run report
  ([docs/hadoku-task-automation/run-report-2026-07-25.md](../hadoku-task-automation/run-report-2026-07-25.md))
  cites a different, shorter SHA for every one of those seven commits —
  none of the seven it lists resolve in this repository today. The real
  ones, above, were found independently by matching each commit's own
  message.

## Naming

- Batches get a `{adjective}-{animal}` identity (`jade-hare`,
  `dusty-lizard`, `crimson-kitty`) specifically so they can be discussed and
  compared by name rather than by date or number (`e682a45`).
- crimson-kitty, the redesign, takes its own name from that same
  convention. The doc that defines the `{adjective}-{animal}` pattern names
  `crimson-kitty` as its own example, three weeks before any design work on
  the pipeline itself began (`e682a45`; the pipeline's own design doc is
  `f53cce8`).
