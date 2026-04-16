# Phase 3 smoke targets

Five issues hand-picked for the Phase 3 pipeline-correctness smoke test
(docs/crimson-kitty/phase-1-plan.md § Phase 3.1).

Selection criteria:
- One issue per repo (five distinct repos, five distinct tools)
- Each is a single-tool, single-file, mechanical fix an agent can make
  in a <10 line diff
- Known-resolvable by the operator in <30 min
- Deliberately includes stale findings — many of these were opened by
  vibeCheck against older commits and may already be fixed on `main`.
  Staleness is the test: does the pipeline abort cleanly when there is
  nothing left to fix, or does it open a no-op PR that the gates catch?

## Targets

| # | Repo                | Issue | Tool         | Rule / scope                                              |
|---|---------------------|-------|--------------|-----------------------------------------------------------|
| 1 | WolffM/hadoku-scraper | #2  | ruff         | F401 unused import in `test_signer.py`                    |
| 2 | WolffM/hadoku_site    | #145 | markdownlint | MD060 in `TEMPLATE.md`                                    |
| 3 | WolffM/ArchiveBot     | #22 | markdownlint | MD040 (3 occurrences, missing code-fence langs) in `CLAUDE.md` |
| 4 | WolffM/hadoku-task    | #47 | knip         | Unused Type in `useToast.ts`                              |
| 5 | WolffM/vibecheck      | #343 | jscpd        | 13-line duplicate in `findings-to-workitems.ts`           |

## What we're measuring

Per Phase 3.2, for each issue record:
- Did it reach a terminal state (`merged`, `closed_by_upstream`,
  `aborted`, or still `submitted` after 48h)?
- If `aborted`, was the reason clear and correct (e.g. "finding already
  resolved on main")?
- If `submittable`, did all 9 mechanical gates run and pass?
- If `submitted`, did the upstream PR contain zero leaked refs?
- Did the operator inbox surface the right defers?

## Expected surprises (predictions)

Recording these up front so Phase 3.3 can score prediction accuracy:

1. At least 2 of 5 findings are already fixed on `main`; agent either
   opens a no-op PR (gate rejects at `diff_non_empty`) or short-circuits
   at the repro activity.
2. markdownlint fixes are trivial enough that Copilot may not add a test
   — `fix` gate should still pass because the `relevance` check is
   content-level, not test-level.
3. The jscpd duplicate finding (#5) is the riskiest: "fix" could mean
   "extract helper" which is a larger refactor than a one-line fix.
   Agent may misjudge scope.
