# History

TenHands is four generations of the same idea — dispatch coding agents at
real work, and earn the right to ship what they produce — each one built on
the measured failure of the one before. The fuller version, with every
number, is [docs/HISTORY.md](../HISTORY.md); this page hits the same eras
with their commits.

## vibedispatch (January to June 2026)

The repo's first commit is titled, in full, "first commit" (`918a3e8`,
2026-01-07). It began as **vibedispatch**, a dispatcher for a separate
static-analysis GitHub Action: point it at a repo, run the analyzers, turn
findings into issues, hand the issues to an agent. A week later the project
reorganized into `backend/` and `frontend/` directories (`dcbb8fd`) and the
frontend moved to a React 19 micro-frontend (`6b4200d`). The repo kept its
original name for five more months, renamed to **TenHands** in two commits
on the same day: the rebrand itself, and a fix because the public route
prefix still answered to the old name (`12d5756`, `44970e0`).

*Lesson it bought: generating work for agents is the easy half. Deciding
what is worth doing, and proving the result is right, is the whole
problem.*

## OSS pipeline v1, and jade-hare (February to March 2026)

A five-stage pipeline — target repos, scored issues, fork & assign, review
on fork, submit upstream — went after real open-source issues, scored by a
separate service's own contribution-viability model. Its first batch,
**dusty-lizard**, ran before per-batch tracking existed, so its record is
thin by design gap rather than by choice. Its second, **jade-hare** (March
13 to 17), is the batch that paid for everything that followed: 55 issues
dispatched and exactly one merged upstream, with 21% of the returned PRs
holding empty diffs and a handful of cross-reference notifications that
reached upstream maintainers before any human reviewed the work (`d185227`,
which rewrote this project's own public account of that batch).

*Lesson it bought: volume with no evidence gates converts agent capacity
into maintainer annoyance at better than fifty to one.*

## Retrospective build-out, then crimson-kitty (late March to May 2026)

Before building a third pipeline, the project built the machinery to read
the first two honestly: batch identities, per-issue session artifacts, and
a report that treats a maintainer's own review comments as the single most
important signal, fed in part by a full metadata sweep over the earlier
batches (`2a76c96`). What followed was the redesign jade-hare paid for:
**crimson-kitty**, a 20-state Temporal workflow where every transition needs
an evidence artifact, scaffolded and designed first (`f53cce8`), then built
phase by phase — foundational utilities (`8bde2ff`), then an operator UI
(`ec7271e`) — with cross-reference leaks fixed by stripping upstream
references from fork-facing content rather than trusting an agent not to
mention them (`2c24481`).

*Lesson it bought: an abort with a clear reason is a success. The
pipeline's job is to make failure legible, not to make submission
inevitable.*

## taskauto (July 2026)

The proof the engine generalizes: the same Temporal machinery, aimed at a
task board instead of a scored upstream issue, landing by merging to this
repo's own `main` instead of opening an upstream PR (`f30e007`, which
added the CLI entry point and job planning; `a74b3fd`, discovering boards
automatically rather than needing one configured by hand). Its first day in
production shipped seven unattended commits straight to `main`, each gated
on the full test suite passing against the merge result, the last one found
entirely by the scheduler with nobody prompting it: `dee574a`, `a2956dc`,
`0966641`, `b8afd1e`, `96f5366`, `41cbeb9`, `2c985b8`.

*Lesson it bought: once the middle of the pipeline is proven, the ends are
configuration — the same evidence discipline that protects a stranger's
repo protects this one's own `main`.*

## Trivia

The day-one run report this repo keeps
([docs/hadoku-task-automation/run-report-2026-07-25.md](../hadoku-task-automation/run-report-2026-07-25.md))
cites a different, shorter SHA for each of those seven commits than the
ones that actually exist in this repository's history today — every one
listed above was found independently by matching each commit's own message
and verified directly. The rest of the best facts, each with its source,
are in [trivia.md](trivia.md).
