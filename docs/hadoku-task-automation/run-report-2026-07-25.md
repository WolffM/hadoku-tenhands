# hadoku-task-automation — first day, 2026-07-25

Designed, built, shipped to production, and **seven commits reached
`WolffM/tenhands` `main` with no human writing the code.** The pipeline is live
and runs unattended.

| sha | task, as typed on the board |
|---|---|
| `ffb4272` | remove the unused json import in backend/helpers/validation.py |
| `456e485` | clean up the unused VIBECHECK_WORKFLOW_NAME import in workflow_routes |
| `fd06068` | remove the unused safe_error_message import from backend/routes/oss_routes_stage5.py |
| `9a88c43` | drop the unused flask request import from backend/routes/debug/health_routes.py |
| `5fbd8ff` | remove the two unused imports … from backend/routes/oss_routes_stage3.py |
| `028e3dd` | remove the unused safe_error_message import from backend/routes/action_routes.py |
| `7457153` | remove the unused validate_required_fields import from oss_routes_stage4.py |

Every one gated on the **full suite passing against the merge result** — the
branch with current `origin/main` merged in, not the branch in isolation. That
mattered: unrelated commits landed between a dry run and its live run more than
once.

The last two came through the **real shared board**, and `7457153` was found by
the scheduler with no prompting at all.

---

## The autonomy proof

A task was filed and then left alone:

```
tick 1: idle: 1 inbox task(s) still settling (< 300s since last edit)
tick 2: idle: no changes
tick 3: idle: no changes
tick 4: acted: plan on 01KT8H3E… → plan-review (new capture, settled)
```

Two things worth noticing. It **held the task for the settle delay** rather than
planning at a sentence still being typed. And it was picked up by the **periodic
sweep, not the change feed** — the task became eligible through elapsed time,
with no board event to fire. That is precisely the case a webhook cannot cover,
and it is why the scheduler polls (see `scheduler.py`'s module docstring).

## What the pipeline refused to do

Two tasks correctly did **not** land.

**`too much logging noise`** — deliberately vague. It produced a concrete plan
citing specific periodic loggers by `file:line`, then asked the one question that
actually blocks it: *which surface is noisy?*

**`bump the copilot check-run name in .github/workflows`** — the title contained
a **false premise**. The planner investigated, found no check-run literal in
`.github/workflows` at all, located the real constants, noticed they already
agree, corrected the blast radius to *"not `.github/workflows/*`"*, and refused
to state an acceptance check. A pipeline that confabulated a plausible edit here
would have landed a wrong change under a green suite.

## Failure paths exercised for real, not simulated

- **Crash mid-landing.** A run was killed during its prod-watch window, after the
  push. Recovery would have rebuilt shipped work, so `implement` now asks git
  whether `main` already carries the commit. Verified: recovered in 2 seconds
  without re-running the agent.
- **Owner cancel.** `POST /agent/cancel` → `{"ok":true,"dropped":true}`, task
  stayed put with `claimed=false`, next turn recovered it.
- **Serialisation.** While a claim was live, selection correctly refused to touch
  the task.

---

## Incidents

**Production outage, self-inflicted (~30 min).** Adding a vault key to the
*shared* `tenhands-wrapper.mjs` crashlooped `tenhands` and `tenhands-temporal`
(16 and 6 restarts): `vault-fetch` resolves every declared key and throws if any
is inaccessible, so one missing secret took down three services. Reverted,
restarted, and taskauto now has its own wrapper.

**The lesson: a wrapper's key list is blast radius, not configuration.** Reusing
it was right about the code and wrong about the failure mode.

## Bugs found in this pipeline's own code, all fixed

- `path.lstrip("./")` strips a *character set*, not a prefix — every dotfile on
  the protected-paths deny-list silently stopped matching. Failed in the
  dangerous direction.
- The plan document silently **dropped a human's inline answer** — it appeared in
  neither `questions` nor `human_text`.
- `untagged()` tested "no tags at all" when it meant "no lane tag", so a task
  labelled `urgent` was invisible to every branch of selection.
- A first plan was labelled "pass 2", burning a round off the cap.
- The credential fell back to the environment on an explicit empty key, so a
  deliberately keyless client authenticated as the real service account.
- Discovery **fabricated claim state**: `GET /boards` does not populate `claimed`,
  so every task read as unclaimed. Nothing consumed it yet, but it is exactly
  what produces a double-claim.

## Retracted

A "blocking shared-board read bug" was reported to the hadoku-task team and was
**my error** — I addressed the board by its *slug* rather than its *handle*.
Slugs are per-user and collide. Their sharing works correctly.

**Address boards by handle, never by slug.**

---

## Current state

**Live.** `tenhands-taskauto` is committed to `ecosystem.config.cjs` with its own
wrapper, defaulting to `TASKAUTO_LIVE=0` — it runs the entire pipeline and stops
before the push until deliberately armed.

**Boards are discovered, not configured.** Any board shared with the service key
that is activated and records a repo gets driven. Sharing at `contributor` *is*
the enrolment step.

**Not yet true:**

- `tenhands-taskauto` **is reloaded on the host but not running.** It needs a
  vault credential that does not exist yet: `hadoku_site/services/pm2/
  taskauto.vaultkey` (mode 0600, gitignored, host-local), granted
  `TENHANDS_SERVICE_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` and `HADOKU_SITE_TOKEN`.
  Generating one is operator-tier. Until then the service is `stopped` —
  deliberately, so it is not flapping.

  Watch the name: vault-fetch derives the keyfile from the *wrapper* filename
  (`taskauto-wrapper.mjs` → `taskauto.vaultkey`), **not** the pm2 service name
  `tenhands-taskauto`. Without it no `X-User-Key` is sent, the loopback bypass
  does not cover ACL-gated secrets, and it dies on `403` against
  `TENHANDS_SERVICE_KEY` — which reads like a missing grant rather than a
  missing key. `vault-fetch.mjs` now warns with the exact path it wanted
  (hadoku_site `4ec59804`).

  The tenhands key already holds all three grants, so symlinking it would start
  the service immediately — but it carries 16 grants including
  `TENHANDS_ADMIN_KEY` and `MSFT_SSO`, and handing the identity that supervises
  an autonomous agent more reach than it declares is the wrong direction while
  §4.3 is still open.
- The **fast path is disabled** — every task goes through `plan-review`, even
  trivial ones. The design has intake releasing straight to `approved`.
- **No parallelism.** One task in flight per repo. A task parked in `plan-review`
  does *not* block — only a live claim does. To parallelise, give each task its
  own worktree and serialise **only the landing**, since two commits inside one
  watch window cannot be attributed if health goes red.
- **§4.3 open.** The agent runs headless on the prod host. Its environment is
  scrubbed to an allow-list (no vault key, no board key, no GitHub tokens) and it
  works in a checkout it owns, but nothing constrains its filesystem or network.
- **On a shared board we cannot clear our own stuck claim** — `POST /agent/cancel`
  is owner-only, so a crash mid-landing means waiting out the 15-minute lease.
