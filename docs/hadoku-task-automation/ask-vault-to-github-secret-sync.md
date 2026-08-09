# Ask: rotating a vault secret must reach GitHub Actions

**To:** hadoku_site
**From:** tenhands
**Date:** 2026-08-08
**Severity:** caused a silent production failure; the immediate half is a one-line fix

## The ask, in one line

`CLAUDE_CODE_OAUTH_TOKEN` was rotated in the vault and the GitHub Actions secret of the
same name still holds the old value, because **nothing syncs the two** — despite
`taskauto.yml` documenting that something does.

## Immediate unblock

```sh
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo WolffM/tenhands   # value: the vault item of the same name
```

Until this runs, `tenhands:taskauto` posts `status=failed` to `/health/api/jobs` on every
sweep (~every 15 min). That is deliberate — see "What we changed on our side" — but it will
keep paging.

## The actual bug

`.github/workflows/taskauto.yml` says, next to the secret:

> The secret NAME must match the vault item name: hadoku_site provisions GitHub secrets by
> pulling the vault item of the same name, so a name with no vault item behind it can never
> be refreshed by anything.

We took that at face value. It is not true today — or the job exists and did not run. We
could not find a sync path in `hadoku_site/scripts/`; the only `gh secret set` is a printed
instruction in `scripts/admin/create_child_app.py:542`, i.e. a manual step at app-creation
time. So a vault rotation reaches local dev and pytest instantly and reaches Actions never.

Either fix works for us, but please make the code and the comment agree:

1. **Provision for real** — a job that pushes vault items to the Actions secrets of the repos
   declaring them, so rotation is one write. This is what the comment already promises.
2. **Delete the promise** — drop the comment, and document rotation as a two-store operation
   with an explicit checklist. Worse, but honest.

If (1), please also emit a warning when a repo declares a secret in `.devvault.json` that has
no corresponding Actions secret, or whose Actions secret predates the vault item.

## Why it cost us more than a red build

The failure was **silent for four days**. A revoked `CLAUDE_CODE_OAUTH_TOKEN` makes
`claude -p` exit 1 in ~3.5s and print

```
Failed to authenticate. API Error: 401 OAuth access token has been revoked.
```

to **stdout**, with stderr empty. Our planning step returned that string as the plan; it
parsed to an empty document; the pipeline read "no plan and no questions" as "this looks
already done" and published it to a human's board as a completed planning pass. **The run
reported success.** Two real tasks came back with a body consisting entirely of
`_No open questions._` and nothing else.

Nothing in the vault was wrong — `dev-vault --check` reported 4/4 keys fetchable throughout,
and the local `pytest` suite (which fetches the token through the broker, correctly) was green.
That is precisely what made it hard to see: **every signal that reads the vault said healthy,
and only Actions was broken.**

## What we changed on our side

Fixed in `427cd11` and `388b55a`. An agent that cannot run now aborts the sweep and exits 3,
so the run goes red and reports `status=failed` rather than publishing fiction. Verified live:
run `31292117106` concluded `failure` with the health check posted. We are no longer
*silently* dependent on this — but we are still dependent on it.

## Scope

Only `WolffM/tenhands` holds this secret (checked across the WolffM repos with workflows
referencing it). It is consumed by two workflows: `taskauto.yml` and `test.yml`. Note
`test.yml` is a PR gate, so a stale token there fails PR checks for a reason that has nothing
to do with the PR.

## How to verify the fix

```sh
gh secret list --repo WolffM/tenhands     # CLAUDE_CODE_OAUTH_TOKEN timestamp should be today
gh workflow run taskauto.yml --repo WolffM/tenhands
```

A healthy planning pass takes **200s+**. A run that finishes a plan in under ~30s, or a task
whose notes contain only `## Questions / _No open questions._`, means the credential is still
dead. Two tasks are parked in `replan` (hadoku-pygmalion, hadoku-task) and will plan
themselves on the first sweep after the secret is correct.
