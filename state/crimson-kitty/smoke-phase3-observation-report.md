# Phase 3.2c — Per-issue observation report

Batch: `smoke-phase3-r5` (final successful run)
Dispatched: 2026-04-16T16:01:00Z
All 5 completed: 2026-04-16T17:37:00Z (~96 min wall clock)

## Summary

| # | Issue | Final state | Abort gate | Gates passed | Transitions | Events |
|---|-------|-------------|------------|-------------|-------------|--------|
| 1 | hadoku-scraper#2 | aborted | diff_non_empty | 4/6 | 5 | 101 |
| 2 | hadoku_site#145 | aborted | diff_non_empty | 4/6 | 5 | 113 |
| 3 | ArchiveBot#22 | aborted | diff_non_empty | 4/6 | 7 | 101 |
| 4 | hadoku-task#47 | aborted | diff_non_empty | 4/6 | 5 | 104 |
| 5 | vibecheck#343 | aborted | diff_non_empty | 4/6 | 5 | 95 |

**Result: 0/5 submitted, 5/5 aborted (all at diff_non_empty).**

All 5 SA findings were already resolved on `main`. Copilot successfully
reproduced each issue (ran the relevant linter/tool, confirmed the finding
existed historically) but produced an empty fix diff because the code had
already been corrected. The pipeline correctly identified this via the
`diff_non_empty` gate and aborted with a clear reason.

## Per-issue detail

### 1. hadoku-scraper#2 — Ruff F401 unused import in test_signer.py

- **Gates**: eligibility pass, input_context_clean pass, environment_works pass, repro_evidence_present pass, diff_non_empty **fail**, relevance **defer** (CLAUDE_CODE_OAUTH_TOKEN missing)
- **Copilot PR**: WolffM/hadoku-scraper#28 (draft, +53/-0, 2 commits)
- **What Copilot did**: Created reproduction notes + trace artifact confirming the import was already removed
- **Abort reason**: `diff is empty — no commits ahead of base`
- **Assessment**: Correct abort. The unused import was removed in a prior commit.

### 2. hadoku_site#145 — markdownlint MD060 in TEMPLATE.md

- **Gates**: eligibility pass, input_context_clean pass, environment_works pass, repro_evidence_present pass, diff_non_empty **fail**, relevance **defer** (token missing)
- **Copilot PR**: WolffM/hadoku_site#162 (draft, +25/-0, 2 commits)
- **What Copilot did**: Created repro notes + trace
- **Abort reason**: `diff is empty — no commits ahead of base`
- **Assessment**: Correct abort. The markdownlint finding was already addressed.

### 3. ArchiveBot#22 — markdownlint MD040 in CLAUDE.md

- **Gates**: eligibility pass, input_context_clean pass, environment_works pass, repro_evidence_present pass, diff_non_empty **fail**, relevance **defer** (token missing)
- **Copilot PR**: WolffM/ArchiveBot#25 (draft, +53/-13, 2 commits)
- **What Copilot did**: Created failing repro test + notes (7 transitions — more than others, indicating a retry loop in the repro phase)
- **Abort reason**: `diff is empty — no commits ahead of base`
- **Assessment**: Correct abort. MD040 findings already fixed.

### 4. hadoku-task#47 — knip unused Type in useToast.ts

- **Gates**: eligibility pass, input_context_clean pass, environment_works pass, repro_evidence_present pass, diff_non_empty **fail**, relevance **defer** (token missing)
- **Copilot PR**: WolffM/hadoku-task#50 (draft, +52/-0, 4 commits)
- **What Copilot did**: Created repro notes, clarified executable command, formatted code block (3 iterative commits on the repro)
- **Abort reason**: `diff is empty — no commits ahead of base`
- **Assessment**: Correct abort. Unused type already removed.

### 5. vibecheck#343 — jscpd 13-line duplicate in findings-to-workitems.ts

- **Gates**: eligibility pass, input_context_clean pass, environment_works pass, repro_evidence_present pass, diff_non_empty **fail**, relevance **defer** (token missing)
- **Copilot PR**: WolffM/vibecheck#345 (draft, +178/-0, 2 commits)
- **What Copilot did**: Created repro notes + failure trace
- **Abort reason**: `diff is empty — no commits ahead of base`
- **Assessment**: Correct abort. The duplicate code was already refactored.

## Checklist (per Phase 3.2)

- [x] Did each reach a terminal state? **Yes** — all 5 aborted
- [x] If aborted, was the abort reason clear and correct? **Yes** — `diff_non_empty` with "diff is empty" is unambiguous
- [ ] If submittable, did all 9 mechanical gates run and pass? **N/A** — none reached submittable
- [ ] If submitted, did the upstream PR contain zero leaked refs? **N/A**
- [x] Did the operator inbox surface the right defers? **Partial** — relevance gate deferred due to missing CLAUDE_CODE_OAUTH_TOKEN (a config issue, not a pipeline logic issue)

## Pipeline mechanics observations

1. **Parallel execution worked**: all 5 issues ran concurrently after the asyncio.gather fix
2. **Gate ordering is correct**: diff_non_empty fires before relevance, so the empty-diff abort preempts the judge call
3. **Copilot assignment + polling worked end-to-end**: all 5 forks got context issues, Copilot was assigned, PRs were created, commits were polled
4. **Evidence download worked**: repro_evidence_present passed on all 5 after the _download_agent_files fix
5. **Staleness detection is clean**: the pipeline doesn't special-case stale issues — it runs the full workflow and the fix gate catches the empty diff naturally
