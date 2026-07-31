# Every PR must be covered by at least one check that always runs

**Status:** blocking autonomous landing · **Scope:** one workflow change per repo
**Filed from:** tenhands, after auditing why the pipeline can't merge its own PRs

## The invariant

> For every pull request a repo can receive, at least one **required** status
> check must report a result.

Not "the repo has CI." Not "most PRs get checked." *Every* PR, including one that
touches a single asset file in a directory nobody thought about.

This is the prerequisite for autonomous landing, and it is currently false in
every repo the pipeline drives except tenhands.

## Why "the repo has CI" is the wrong question

GitHub's auto-merge waits only for **required** checks, and a required check that
never runs never reports, so the PR waits forever. That gives two failure modes,
and a repo can have both at once:

| situation | `--auto` does | branch protection does |
|---|---|---|
| no required checks configured | merges **immediately**, ignoring CI | nothing |
| required check that doesn't run on this PR | never merges | blocks forever |

So a path-filtered gate is not a partial gate. It is a gate that is *absent* on
some PRs and *fatal* on others, depending on which knob you turn.

## The evidence

hadoku_site is the best-covered repo in the fleet — `lint`, `typecheck`, `test`,
`inventory-test`, all real. On 2026-07-30 it received five pipeline PRs:

```
#218  src/components/…             → lint, scan, typecheck   ✅
#219  src/…                        → lint, scan, typecheck   ✅
#220  src/…, e2e/…                 → lint, scan, typecheck   ✅
#221  pocs/**, public/v1/_astro/** → (none)                  ❌
#222  public/audio/player.js       → (none)                  ❌
```

All four of its `pull_request` workflows are path-filtered, and the union of
those filters is `src/ workers/ services/ templates/ scripts/ e2e/` plus a few
root files. Nothing covers `pocs/**` or `public/**`. Two of five PRs got no
check at all — and #221 modified a content-hashed build artifact
(`public/v1/_astro/cosmos.*.js`), which is exactly the kind of change you want a
gate to notice.

Fleet-wide, measured:

| repo | PR-triggered workflows | always runs? |
|---|---|---|
| tenhands | `test.yml` | **yes** — no `paths:` filter |
| hadoku_site | 4 workflows | no — all filtered |
| hadoku-pygmalion | `typecheck.yml` | no — `frontend/**` only |
| watchparty | `build-ui.yml` | no — `apps/ui/**`, `packages/**` only |
| hadoku-task | `kate-plugin.yml` | no — `plugins/kate/**` only |
| hadoku-conjure | none | **no CI at all** |

hadoku-task's only PR workflow is scoped to a Kate editor plugin, which is why
PR #72 sat open for two days with **zero** checks.

## What to do, per repo

Pick whichever fits; the invariant is what matters, not the mechanism.

**Option A — drop the filter from the cheapest meaningful job.** Usually
typecheck or lint. A PR touching only assets then runs a check that passes
trivially, which is honest: there was nothing of that kind to verify, and you
still get a status to require. Cheapest change, and the right default.

**Option B — an always-on `gate` job that dispatches internally.** `on:
pull_request` with no `paths:`, one job that inspects the changed files and runs
the relevant validations. Always reports, so it is safe to require. Use this when
unfiltered CI would be genuinely expensive.

**Anti-pattern — a job that always passes.** A required check that reports
success without verifying anything satisfies the letter of this document and
none of its purpose. If a class of file has no meaningful validation, say so in
the workflow rather than papering over it. For `public/**` in hadoku_site, a
real check would be "does this PR modify a generated artifact under
`_astro/`" — that is a genuine question with a genuine answer.

## Then, and only then

Once a repo has a check that always runs:

```bash
# 1. required check (strict:false — do NOT force branches up to date, that is
#    the staleness treadmill this pipeline is trying to escape)
gh api -X PUT repos/OWNER/REPO/branches/main/protection --input protection.json

# 2. auto-merge capability (already enabled fleet-wide as of 2026-07-29)
gh api -X PATCH repos/OWNER/REPO -f allow_auto_merge=true
```

with:

- `enforce_admins: false` — direct pushes to `main` are the normal workflow here
  and must keep working. Verified: pushing to a protected `main` succeeds with
  this off.
- `required_pull_request_reviews: null` — **do not require reviews.** Pipeline
  PRs are authored by `WolffM`, GitHub forbids self-approval, and requiring one
  approval would deadlock every pipeline PR permanently.

tenhands is configured this way today and is the reference.

## The check to run before declaring a repo done

Not "is CI green" — that proves nothing here. Open a PR that touches **only** the
most-ignored corner of the repo (an asset, a doc, a fixture) and confirm a
required check still reports on it. That is the invariant, stated as a test.
