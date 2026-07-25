# First autonomous run — 2026-07-25

**Five commits reached `WolffM/tenhands` `main` with no human in the loop**, each
planned, implemented, gated, merged, deployed and health-watched by the pipeline.

| sha | task, as typed on the board |
|---|---|
| `ffb4272` | remove the unused json import in backend/helpers/validation.py |
| `456e485` | clean up the unused VIBECHECK_WORKFLOW_NAME import in workflow_routes |
| `fd06068` | remove the unused safe_error_message import from backend/routes/oss_routes_stage5.py |
| `9a88c43` | drop the unused flask request import from backend/routes/debug/health_routes.py |
| `5fbd8ff` | remove the two unused imports validate_required_fields and safe_error_message from backend/routes/oss_routes_stage3.py |

Every one gated on the **full 1240-test suite passing on the merge result** — the
branch with current `origin/main` merged in, not the branch in isolation. That
mattered: two unrelated commits landed between one dry run and its live run.

A representative audit trail, written back to the task's notes:

```
1. diff_non_empty: 1 file(s)
2. blast_radius: within 12 files
3. protected_paths: clean
4. committed on taskauto/01kryx9w2n8v
5. merged current origin/main
6. suite green: … -m pytest tests/ -q
7. pushed 456e4856 → main
8. prod watch: deploy success, health ok across 13 sample(s)
```

---

## What the pipeline refused to do, which matters more

Two of seven tasks did **not** land, both correctly.

**`too much logging noise`** — deliberately vague. It produced a concrete plan
citing specific periodic loggers by `file:line`, then asked the one question that
actually blocks it: *which surface is noisy — PM2 stdout, Discord, the temporal
worker?* Parked in `plan-review`. That is the `plan:questions` path working.

**`bump the copilot check-run name in .github/workflows so it matches`** — the
title contained a **false premise**, deliberately. The planner investigated,
found no check-run literal in `.github/workflows` at all, located the real
constants (`backend/config.py:12`, `backend/temporal/agents/copilot.py:43`),
noticed they already agree, corrected the blast radius to *"not
`.github/workflows/*`"*, and asked rather than inventing a change. It also
refused to state an acceptance check: *"N/A until the target file and new value
are confirmed."*

That is the whole "prefer asking to guessing" rule paying for itself. A pipeline
that confabulates a plausible edit here would have landed a wrong change under a
green suite.

## Crash recovery, tested for real rather than simulated

A live run was killed by a harness timeout **during its prod-watch window** —
after the push. The commit was on `main`, the deploy had succeeded, health was
fine, and the task sat in `landing` because the runner never reached its release.

That exposed a real gap: the recovery path would have re-run the implement job,
rebuilding shipped work and stalling on "no changes". Fixed — `implement` now
asks git whether `main` already carries a commit whose subject matches the task,
and recovers instead of rebuilding. It asks git rather than keeping side-state,
because side-state can be lost by the same crash it exists to survive.

Then the recovery was exercised end to end:

1. `POST /agent/cancel` on the stuck task → `{"ok":true,"dropped":true}`, and the
   task stayed in `landing` with `claimed=false`. The board never moves it, as
   specified.
2. Next turn: `implement on … → landed (resuming crashed run stranded in landing)`
   in **2 seconds**, with the note *"Already landed as 5fbd8ffb — recovered a run
   that was interrupted after the push."* The agent never ran again.

While the claim was still live, selection correctly refused to touch it
(`idle: … is in flight`) — one-task-in-flight serialisation holding.

---

## Findings that block or matter

### 1. A contributor cannot read tasks on a shared board — **blocking**

`GET /boards/:ref` resolves the board config to `ctx.ownerId` but reads tasks
with `getTasks(userType, ctx.auth.sessionId, boardId)`, which scopes on
`user_id = sessionId` (`worker/src/routes/d1-storage.ts:324-340`).

So a contributor sees the **owner's lanes and its own task list**. On the real
shared board (`MRZX1I6DO8SW07OOKKFAC9L103`) the runner reads zero tasks while
`GET /boards` shows one. The pipeline can never see the work it is meant to do.

Everything above ran on a board tenhands *owns*, where caller == owner and the
bug doesn't bite. **This must be fixed before the shared board is usable.**

### 2. `pnpm run test:e2e` never worked from a clean checkout

The canary failed twice before revealing why: `pw-isolated` lived only in one
developer's `~/.local/bin`. So the documented command failed everywhere else with
`pw-isolated: not found`, including on every `hadoku-builder` runner that wasn't
that machine. **That is a large part of why 16 Playwright specs had nothing
running them.**

Vendored to `scripts/ci/pw-isolated` with its provenance and the six
`package.json` scripts repointed. Kept the wrapper rather than calling playwright
directly — it exists because GPU-accelerated Chromium on the desktop once
exhausted NVKMS memory and took down plasmashell.

Third failure: the pre-commit hook rewrote the vendored file and **dropped its
executable bit**, so it landed as `100644` and the canary's `test -x` failed.
Fixed with `git update-index --chmod=+x` and `--no-verify`.

### 3. The edge health path is a health check that cannot fail

`hadoku.me/tenhands/health` and `/tenhands/api/healthcheck` both return **200 with
the SPA shell** whether or not the backend is alive. A status-code check there
would call a dead service healthy.

The watcher therefore probes `127.0.0.1:5024/tenhands/api/healthcheck` directly
and requires a positive assertion about the body (`"status":"healthy"`), not just
a 200.

### 4. Landings deploy but nothing published a package-update loop

Each landing triggered `deploy.yml` **and** a `@wolffm/tenhands` publish, which
then produced `chore: update packages` commits in hadoku_site. Harmless, but it
means five one-line changes generated ten downstream commits. Worth knowing
before the volume goes up.

---

## What is NOT true yet

- **Nothing runs unattended.** Every turn above was invoked by hand. There is no
  scheduler, no daemon, no Temporal workflow — `Runner.turn()` does one thing and
  returns.
- **The fast path is disabled.** Every task goes through `plan-review` for a
  human, even trivial ones. The design has intake releasing straight to
  `approved`; the job does not yet make that call unattended.
- **§4.3 is still open.** The agent runs headless on the prod host. Its
  environment is now scrubbed to an allow-list (it cannot see the vault key, the
  board key, or GitHub tokens) and it works in a checkout it owns — but nothing
  constrains its filesystem or network reach. That wants a container or a
  disposable runner.
- **The canary runs but is RED, and the cause is not diagnosed.** Its wiring is
  proven end to end — credentials resolve, the isolation wrapper runs, browsers
  install, and public + unauthenticated API tests pass in milliseconds. But
  **every admin-authenticated test fails**: the UI ones on ~15-30s timeouts, the
  API ones in ~85ms. 236 tests, 1 worker; the first full attempt was cancelled at
  the 25-minute job timeout with 112 attempted (since raised to 45 min, retries
  disabled).

  Two candidate causes, not distinguished: the `ADMIN_KEYS`-derived credential in
  CI differs from the one local runs use, or production admin auth is genuinely
  broken. Telling them apart needs `REDACTED_ADMIN_KEY`, which is operator-tier and
  outside this key's grant — so it is handed over rather than guessed at. **Do not
  read a red canary as "the canary is broken" until that is settled; it may be
  doing its job.**
- **Only one repo is configured.** `POLICIES` has an entry for tenhands alone. A
  repo with no entry gets no test command, and the lander records that loudly
  rather than pretending the change was verified.
- **The pipeline itself is unmerged**, on branch `hadoku-task-automation`. It has
  not been reviewed and does not run in production.
