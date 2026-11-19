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
13 to 17), is the batch that paid for everything that followed. It
dispatched 55 issues and merged exactly one upstream: 21% of the returned
PRs held empty diffs, and a handful of cross-reference notifications
reached upstream maintainers before any human reviewed the work
(`d185227`, which rewrote this project's own public account of that
batch).

The pipeline itself ran as five dashboard stages. Target repos gave a
health overview. Scored issues were tiered GO/LIKELY/MAYBE/RISKY/SKIP by
the aggregator's own model. Fork and assign built agent context from the
aggregator's dossier, stripping upstream references before an agent ever
saw it. Review on fork ran a draft PR through static analysis and
remediation. Submit upstream opened a PR only after explicit operator
approval — the one point where a cross-reference such as `Fixes #N` was
allowed back in. Those five stages still run read-only in the dashboard
today, alongside the newer pipelines.

*Lesson it bought: volume with no evidence gates converts agent capacity
into maintainer annoyance at better than fifty to one.*

## Retrospective build-out, then crimson-kitty (late March to May 2026)

Before building a third pipeline, the project built the machinery to read
the first two honestly: batch identities, per-issue session artifacts, and
a report that treats a maintainer's own review comments as the single most
important signal. A full metadata sweep over the earlier batches fed that
report (`2a76c96`).

What followed was the redesign jade-hare paid for: **crimson-kitty**, a
20-state Temporal workflow where every transition needs an evidence
artifact. It was scaffolded and designed first (`f53cce8`), then built
phase by phase — foundational utilities (`8bde2ff`), then an operator UI
(`ec7271e`). Cross-reference leaks were fixed by stripping upstream
references from fork-facing content rather than trusting an agent not to
mention them (`2c24481`).

crimson-kitty's own first full smoke batch, five issues dispatched on
2026-04-16, submitted zero of them — every one aborted at the empty-diff
gate, correctly, because all five findings were already fixed upstream
([observation report](../crimson-kitty/smoke-phase3-observation-report.md),
2026-04-16). Two external dispatch attempts a few days later both ended
10/10 aborted for different reasons, but surfaced eight distinct pipeline
bugs before any maintainer ever saw a PR
([bug catalog](../crimson-kitty/phase4-retrospective.md), 2026-04-18).

*Lesson it bought: an abort with a clear reason is a success. The
pipeline's job is to make failure legible, not to make submission
inevitable.*

## taskauto (July 2026)

The proof the engine generalizes: the same Temporal machinery, aimed at a
task board instead of a scored upstream issue, lands by merging to this
repo's own `main` instead of opening an upstream PR (`f30e007`, which
added the CLI entry point and job planning). It discovers boards
automatically rather than needing one configured by hand (`a74b3fd`).

Its first day in production shipped seven unattended commits straight to
`main`, each gated on the full test suite passing against the merge
result. The scheduler found the last one entirely on its own, with nobody
prompting it: `dee574a`, `a2956dc`, `0966641`, `b8afd1e`, `96f5366`,
`41cbeb9`, `2c985b8`.

*Lesson it bought: once the middle of the pipeline is proven, the ends are
configuration — the same evidence discipline that protects a stranger's
repo protects this one's own `main`.*

## Trivia

The day-one run report this repo keeps
([docs/hadoku-task-automation/run-report-2026-07-25.md](../hadoku-task-automation/run-report-2026-07-25.md))
cites a different, shorter SHA for each of those seven commits than the
ones that actually exist in this repository's history today. Every one
listed above was found independently, by matching each commit's own
message, and verified directly. The rest of the best facts, each with its
source, are in [trivia.md](trivia.md).
