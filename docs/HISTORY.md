# History

TenHands is four generations of the same idea — *dispatch coding agents at real
work, and earn the right to ship what they produce* — with each generation built
on the specific, measured failures of the one before. This repo carries the
whole arc: the pipelines, the retrospectives that indicted them, and the designs
that answered. This page is the map.

## vibedispatch / vibecheck — January 2026

The repo began life as **vibedispatch**: a dispatcher for
[vibecheck](https://github.com/WolffM/vibecheck), a static-analysis GitHub
Action. Point it at a repo, run the analyzers, turn findings into issues, hand
the issues to an agent. The vibecheck workflow-management surface from that era
still ships in the UI (`VibecheckView`), and the repo kept the old name until it
was renamed **vibedispatch → tenhands on 2026-06-16**.

*Lesson bought: generating work for agents is the easy half; the whole problem
is deciding what's worth doing and proving the result is right.*

## OSS pipeline v1 + dusty-lizard — February 2026

The first outward turn: a five-stage pipeline (target repos → scored issues →
fork & assign → review on fork → submit upstream) driven by the
hadoku-aggregator's Contribution Viability Score. **dusty-lizard** was its first
batch — 8 issues, dispatched before per-issue tracking existed, so the record is
thin by design failure rather than by choice.

*Lesson bought: you can't learn from a batch you didn't instrument.*

## jade-hare — March 13–17, 2026

The batch that motivated everything after it. **55 issues dispatched, 1 merged
upstream.** 21% of the PRs came back with empty diffs, roughly 49% of dispatches
never produced an upstream PR at all, 18% of the ones that did drew "AI slop"
callouts from maintainers, and **3 cross-reference notifications leaked to
upstream maintainers from unfinished fork work** — the failure that later became
[cross-ref isolation](crimson-kitty/cross-ref-isolation.md). The numbers are
catalogued batch-by-batch in
[vision-retrospective-v2.md](vision-retrospective-v2.md) and every bug class is
mapped to the gate that now kills it in
[crimson-kitty/gates.md](crimson-kitty/gates.md).

*Lesson bought: volume without evidence gates converts agent capacity into
maintainer annoyance at a 55:1 ratio.*

## Retrospective build-out — late March 2026

Before building a third pipeline, the project stopped and built the machinery to
read the first two: batch identity (`{adjective}-{animal}` naming, backfilled
onto old records), per-issue session artifacts, and reporting that treats
**human review comments as the single most important signal**. The design is
[vision-retrospective-v2.md](vision-retrospective-v2.md); the tools are
`scripts/retro_report.py`, the `retro-pr` / `retro-batch` skills, and the
RetroView UI.

*Lesson bought: the retrospective is read-only — action happens in the next
batch, not in the postmortem.*

## crimson-kitty — the Temporal refactor, April–May 2026

The redesign jade-hare paid for: a [20-state Temporal workflow](crimson-kitty/state-machine.md)
where **every transition requires an evidence artifact**, a
[gate registry](crimson-kitty/gates.md) with each jade-hare bug class mapped to
the gate that kills it, an LLM judge for relevance and submission quality,
[input-context scrubbing](crimson-kitty/cross-ref-isolation.md) so no
notification reaches a maintainer before explicit operator signoff, and a
sandboxed test runner. It was hardened the honest way — smoke batches against
our own repos first, with every surprise logged
([S1–S13](crimson-kitty/smoke-phase3-surprise-log.md)) and every bug catalogued
with root cause and lesson
([the Phase 4 bug catalog](crimson-kitty/phase4-retrospective.md)). May's
[dispatch-readiness overhaul](planning/dispatch-readiness-overhaul.md) then
shifted the success metric from "our gates passed" to "the maintainer merged
it." The full design index is [docs/crimson-kitty/](crimson-kitty/README.md).

*Lesson bought: an abort with a clear reason is a success — the pipeline's job
is to make failure legible, not to make submission inevitable.*

## taskauto / hadoku-task-automation — July 2026

The proof the engine generalizes:
[hadoku-task-automation](hadoku-task-automation/README.md) reuses crimson-kitty's
machinery with both ends swapped — work arrives from a task board (a sentence
typed on a phone) instead of the aggregator, and lands by merging to **this
repo's own `main`** instead of opening an upstream PR. On its
[first day](hadoku-task-automation/run-report-2026-07-25.md), it shipped **7
unattended commits to `main`**, each gated on the full test suite passing
against the merge result, the last found by the scheduler with no prompting at
all.

*Lesson bought: once the middle is proven, the ends are configuration — the
same evidence discipline that protects a stranger's repo protects your own.*
