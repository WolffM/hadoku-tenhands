---
title: TenHands
summary: >-
  An orchestration layer that dispatches coding agents at real work and
  earns the right to ship what they produce, open to any signed-in friend
  to read and reserved for service tier to operate.
features:
  - name: Pipeline dashboards
    summary: Read-only views of every pipeline's state, open to any signed-in friend.
    anchor: pipeline-dashboards
  - name: crimson-kitty
    summary: A 20-state Temporal workflow that finds, fixes and submits a real upstream contribution.
    anchor: crimson-kitty
  - name: taskauto
    summary: The same engine, aimed at a task board instead of an upstream repo, shipping to this repo's own main.
    anchor: taskauto
  - name: Evidence gates and the LLM judge
    summary: Every state transition needs an artifact; a judge scores relevance and submission quality before anything ships.
    anchor: evidence-gates-and-the-llm-judge
  - name: Cross-reference isolation
    summary: Strips every upstream reference from agent-facing content so unfinished work never pings a maintainer.
    anchor: cross-reference-isolation
  - name: The retrospective system
    summary: Reads every batch's own failures — especially human review comments — before the next batch runs.
    anchor: the-retrospective-system
  - name: Operating the pipeline
    summary: Dispatching, approving, claiming and signalling a run.
    anchor: operating-the-pipeline
    tier: service
  - name: Debug diagnostics
    summary: Read-only internals for a run's fork, assignment and context — one level above everyone else.
    anchor: debug-diagnostics
    tier: admin
trivia:
  - 'The repo''s first commit is titled, in full, "first commit" (`918a3e8`, 2026-01-07).'
  - "The batch that funded everything after it, jade-hare, dispatched 55 issues in five days and merged exactly one upstream (`d185227`)."
  - "The rename from the repo's original name to TenHands happened in two commits on the same day, hours apart: one for the brand, one because the public route prefix still answered to the old name (`12d5756`, `44970e0`)."
  - "taskauto's first day on its own board shipped seven unattended commits to this repo's own `main`, each one gated on the full test suite passing against the merge result, the last one found by the scheduler with nobody prompting it (`dee574a` .. `2c985b8`)."
---

# TenHands

TenHands dispatches coding agents at real work, and is built around the
discipline of earning the right to ship what they produce. The project
funded that discipline the hard way. Its **jade-hare** batch (March 2026)
dispatched 55 issues to real open-source repos and merged exactly one
upstream — with empty diffs, maintainer "AI slop" callouts, and a handful of
cross-reference notifications that reached upstream maintainers before any
human had reviewed the work (`d185227`). Everything since has been built to
make that ratio structurally impossible to repeat.

![TenHands' pipeline picker: VibeCheck, OSS Contribution, Crimson-Kitty and Task Automation, each with its own stages](images/dashboard.webp)

**Two pipelines share one engine.** **crimson-kitty** is the OSS-contribution
pipeline: eligibility, fork, reproduce, fix, verify, review, operator
signoff, upstream submission, then watching what happens, as one 20-state
Temporal workflow where every transition needs an evidence artifact.
**taskauto** is the same machinery with both ends swapped — work arrives
from a task board instead of a scored upstream issue, and it lands by
merging straight to this repo's own `main` instead of opening an upstream
PR, unattended.

**Who may do what.** The dashboard (reading pipeline state) is open to any
signed-in friend. Operating a pipeline — dispatching, approving, claiming,
merging — needs service tier and a seat on a named access list; an admin
account is not automatically on it (`backend/app.py`, `_enforce_tier`). A
handful of debug-only internals need admin specifically
(`backend/routes/debug/_middleware.py`, `require_admin`).

## Where to read next

| You want to                      | Read                                |
| --------------------------------- | ------------------------------------ |
| what it does, as a reader or operator | [features.md](features.md)      |
| run it, change it, or ship it    | [contributing.md](contributing.md)  |
| the whole arc, era by era        | [history.md](history.md)            |
| the odd facts                    | [trivia.md](trivia.md)              |

The full story, with every number and every lesson, is
[docs/HISTORY.md](../HISTORY.md); the deep engineering rules are in
[`AGENTS.md`](../../AGENTS.md).

## Trivia

The full list, each with its source, is in [trivia.md](trivia.md).
