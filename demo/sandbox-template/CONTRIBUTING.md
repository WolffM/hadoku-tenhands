# Contributing to demotool

Contributions are welcome, including automated ones from coding agents.

## Workflow

1. Pick an open issue (the `demo` label marks small, well-scoped bugs).
2. Reproduce it, then fix the underlying source — not just the symptom.
3. Add or update a test that fails before your fix and passes after.
4. Run `pytest -q` and make sure the whole suite is green.
5. Open a pull request describing the problem, the fix, and how you verified it
   (see the pull request template).

## Style

- Keep changes small and focused on the issue.
- Match the surrounding code; no unrelated refactors in a bug-fix PR.
- Every bug fix ships with the test that would have caught it.

AI-assisted and fully automated pull requests are explicitly allowed here, as
long as they follow the steps above.
