# Phase 4 / Post-deadlock-fix smoke targets

Dispatched to verify the workflow-task-timeout deadlock fix (agent poll
loop now async-slept + heartbeat + 30-min wall-clock bound).

Fresh 5-repo set (disjoint from r9's hadoku-scraper / hadoku_site /
ArchiveBot / hadoku-task / vibecheck) so we're not retesting the same
upstreams.

| # | Upstream | Issue | Type | Difficulty |
|---|---|---|---|---|
| 1 | WolffM/epicmediabattle | #38 | markdownlint MD040 in README.md | easy |
| 2 | WolffM/fileSystemAgent | #43 | bandit B607 in scheduler.py | easy |
| 3 | WolffM/mtgProxyPrint | #7 | bandit B113 (4 occurrences) in main.py | medium |
| 4 | WolffM/checkmage-bot | #20 | osv-scanner GHSA-rx8g-88g5-qh64 dep upgrade | easy |
| 5 | WolffM/seaborn-ranked-animated | #15 | jscpd duplicate code (13 lines) in moveFiles.py | medium |

All 5 have vibeCheck-generated bodies ≥1000 chars, so no empty-brief
risk this time.

## Prereq

Repos added to hadoku-scrape bootstrap; trigger a scrape+rescore so the
aggregator has scored issues for them before dispatch.
