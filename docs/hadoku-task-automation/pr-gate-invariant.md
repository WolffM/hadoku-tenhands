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

### Re-measured 2026-08-04

Two rows moved and one repo appeared. **hadoku_site is done** — `main` is protected requiring
`lint`, `typecheck`, `site-tests`, `mgmt-api-tests`, `No committed build output` and
`Build variants`, with `enforce_admins: false` and `required_pull_request_reviews: null`, exactly
the shape this doc specifies. Their blocker was that the `auto-format` janitor pushes back to `main`
as `github-actions[bot]`, which is not an admin and so cannot waive a required check; they fixed it
to push as an admin first (`e3df7f66`).

| repo | always-runs check | `main` protected |
|---|---|---|
| tenhands | ✅ `test.yml` | ✅ `backend pytest` |
| hadoku_site | ✅ | ✅ **(new)** |
| hadoku-pygmalion | ❌ `tests.yml` + `typecheck.yml`, both filtered | ❌ |
| hadoku-watchparty | ❌ `build-ui.yml`, filtered | ❌ |
| hadoku-task | ❌ `kate-plugin.yml`, filtered | ❌ |
| hadoku-conjure | ❌ no PR CI | ❌ |
| **hadoku-resume-bot** | ❌ no PR CI | ❌ **(new board, new repo)** |

`hadoku-resume-bot` is a seventh automation board enrolled after this doc was written — a reminder
that the list is discovered, not fixed, so this table is a snapshot and re-measuring is part of the
job. Auto-merge is enabled on all seven, which means the top row of the table above ("no required
checks → `--auto` merges immediately, ignoring CI") is armed on five of them. It is not currently
reachable: the pipeline runs in `pr` mode and never passes `--auto`, so a human still merges. That
is the only thing standing between those five repos and an unchecked auto-merge.

### Closed out 2026-08-04, same evening

Three more repos done, each verified with the acceptance test this doc prescribes — a PR touching
only the most-ignored corner of the repo, confirming a required check still *reports*:

| repo | contexts now required | skip-path probe |
|---|---|---|
| hadoku-pygmalion | `frontend-build`, `python-tests` | docs-only PR → both green in 9s / 8s |
| hadoku-task | `typecheck`, `lint`, `worker-tests` | docs-only PR → all green in 8–17s |
| hadoku-conjure | `check` | docs-only PR → green in 8s |
| hadoku-resume-bot | `typecheck`, `lint` | docs-only PR → both green in 8s / 9s |

All three took the same shape as hadoku_site's fix: the path list moves off the `pull_request`
trigger and into a scope step inside the job, copied verbatim so coverage cannot regress, with every
expensive step guarded by `if: steps.scope.outputs.run == 'true'`. The jobs always report; an
unrelated PR skips the install and goes green in seconds.

Three things worth carrying to the next repo:

- **`checkout` needs `fetch-depth: 0`.** The scope step diffs `base.sha..head.sha`, and a shallow
  clone has no common ancestor to diff against.
- **`setup-node` must come before `corepack enable`.** Otherwise corepack tries to symlink its
  shims next to the *system* node and dies with `EACCES: permission denied, symlink ... ->
  '/usr/bin/yarn'`. This failed all three hadoku-task jobs in 11s on the first run.
- **Not every step should be scope-gated.** pygmalion's "Assert dist is not committed" needs no
  install and costs nothing, so it stays unguarded — a PR that adds `frontend/dist` without touching
  `frontend/` is exactly what a scoped gate waves through. That is the difference between a job that
  skips honestly and the always-passes anti-pattern below.

hadoku-task is the largest gap closed: it had **no PR CI for the application at all**, only the Kate
plugin build. `typecheck`, `lint` and `worker-tests` were already in `package.json` and had simply
never run in CI. Likewise hadoku-conjure's `check` script, which its own `package.json` already
documented as the CI-safe set.

hadoku-resume-bot was the other repo with no PR CI at all; `typecheck` and `lint` were sitting in
its `package.json` unused. Its `allow_auto_merge` was also `false` — the only one in the fleet — and
is now `true`, set *after* protection rather than before, which is the safe order: with auto-merge
on and no required checks, `--auto` merges immediately and ignores CI entirely.

**Still open: `hadoku-watchparty` alone** — `build-ui.yml` is still filtered to `apps/ui/**` and
`packages/**`, and `main` is unprotected. Six of seven are done.

One correction to the row above while re-measuring: `watchparty` in the original table means
`WolffM/hadoku-watchparty`. A separate, stale `WolffM/watchparty` exists with no workflows at all,
and querying the wrong one returns plausible-looking answers about the wrong repo.

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
