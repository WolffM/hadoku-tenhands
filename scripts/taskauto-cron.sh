#!/usr/bin/env bash
#
# The taskauto backstop sweep — hourly, GATED, and not the pipeline's clock —
# and the outermost of three layers of "did that work?".
#
# THIS IS NOT HOW WORK ARRIVES. Read that first, because this file used to be
# the answer to "what makes taskauto run" and is not any more. A human writing
# a task fires a `repository_dispatch` from hadoku-task and a run is queued
# within seconds (verified end to end 2026-09-04). This script exists for the
# things no write can push, and for nothing else.
#
# GATED means it asks before it fires: `scripts/taskauto_pending.py` reads the
# boards from here and this script dispatches only if a sweep would actually
# advance something. On an idle board — which is nearly always — the hour costs
# a few board-API calls off this host and produces NO Actions run at all. See
# THE GATE below, and that script's header for what counts as pending.
#
# ALERTING LAYERS, and why one is not enough:
#
#   1. The run reports its own outcome (taskauto.yml, last step, `if: always()`).
#      Covers success and failure. Cannot cover its own death: when the runner
#      process disappears, no condition is ever evaluated.
#   2. The NEXT run reports its predecessor (taskauto.yml, FIRST step). Covers
#      layer 1's blind spot — a killed or cancelled run — within the hour.
#      Needs a run to happen.
#   3. THIS script. Covers the case where no run happens at all: the dispatch
#      is refused, or it succeeds and nothing ever picks the work up. Neither
#      in-workflow reporter can see that, because both need a run.
#
# The gate does not weaken layer 3, and it is worth being precise about why.
# Layer 3 detects "there was work and nothing ran". When the gate suppresses a
# tick it has just established there is no work, so there is nothing for that
# layer to be blind to; the moment a board has anything pending the dispatch
# goes out unconditionally and the layer is back. The stuck-queue check below
# runs BEFORE the gate on purpose, so a runner that has stopped consuming is
# still caught on an idle hour.
#
# Layer 3 still has a floor: if this host is down, nothing here runs either.
# That case is covered from off-site by monitoring-api's 5-minute edge
# heartbeat, which lists `tenhands` in CRITICAL_SERVICES.
#
# WHY THIS EXISTS AT ALL, NOW THAT THE EVENT PATH WORKS
#
# Two things advance with no human write behind them, so events alone strand
# both:
#
#   - **Completion.** `reconcile.py` is the pipeline's main completion path. A
#     task sits in `landed`, GitHub auto-merges the PR on green, and only a
#     sweep notices and archives it. Nothing sends us "your PR merged".
#   - **Crash recovery.** It fires on lease expiry — the ABSENCE of a heartbeat
#     (`CLAIM_LEASE_SECONDS = 900`) — which by construction nothing can push.
#     Same for a dispatch lost while these services restart mid-deploy.
#
# WHY HOURLY, AND WHY IT USED TO BE EVERY 15 MINUTES
#
# It was `*/15` because this was the pipeline's real clock: the fast path only
# fired on a lane change, so a freshly captured task waited for a sweep. It
# does not wait any more. What `*/15` bought after that was 96 runs a day to
# archive merged PRs a bit sooner, and it cost ~25% of every job the fleet
# reported (840 runs from 2026-08-25). Neither thing this script still covers
# is latency-sensitive to the quarter hour: an hour-late archive is invisible,
# and a crashed claim's 15-minute lease has to expire anyway.
#
# The gate makes an idle tick free, so the obvious next thought is to put the
# cadence back to `*/15` and get faster archiving for nothing. It is not for
# nothing: the gate suppresses on an EMPTY board, and a PR that stays open —
# CI red, or nobody merging it — leaves a task in `landed` that is genuinely
# pending every time we ask. At `*/15` that is 96 sweeps a day for as long as
# the PR sits there, which is the old bill arriving on the days the system is
# actually in use. Hourly caps that at 24 and still archives a normal
# auto-merge within the hour.
#
# The GitHub `schedule` block that used to sit alongside this is GONE (see
# taskauto.yml). It was a second unreliable timer — measured across 73
# consecutive delivered runs, shortest gap 24 min, mean ~45, max 86 — and its
# one remaining argument was "it still fires if this box's crontab is wiped by
# a reimage". That is a real gap and this does not close it; an off-host timer
# would, and a trigger that cannot keep time is not one.
#
# WHY IT IS SAFE TO OVERLAP
#
# The workflow's `concurrency: taskauto` group serialises runs, so a tick that
# lands while a run is in flight queues rather than doubling up, and GitHub
# keeps only the newest pending run per group. An idle sweep is one board-API
# call and an exit, ~21 seconds, so an unnecessary tick costs nothing.
#
# INSTALL (on the runner host, as the runner user):
#
#     crontab -l | { cat; echo '17 * * * * /home/hadoku/repos/hadoku-tenhands/scripts/taskauto-cron.sh >> /home/hadoku/logs/taskauto-cron.log 2>&1'; } | crontab -
#
# Minute 17 rather than 0: nothing else needs to happen exactly on the hour,
# and the top of the hour is where every other cron on this box already piles
# up.
#
# The path is the repo's REAL directory name. It was `repos/tenhands` here for
# long enough that a crontab installed from this comment pointed at nothing
# after the repo took the fleet-wide `hadoku-` prefix; cron then logged
# "not found" every 15 minutes and the backstop was simply gone. Nothing
# noticed, because layer 3 is the layer nothing else watches.
#
# Verify it is firing:  tail -f ~/logs/taskauto-cron.log
# Verify runs land:     gh run list --workflow=taskauto.yml --limit 10

set -uo pipefail

#: GitHub redirects the old name, so `WolffM/tenhands` still resolved after the
#: rename — which is precisely why this sat wrong without failing.
REPO="WolffM/hadoku-tenhands"
REPO_DIR="/home/hadoku/repos/hadoku-tenhands"
VAULT="/home/hadoku/repos/hadoku_site/scripts/secrets/dev-vault.mjs"
STATE="$HOME/.taskauto/cron-state"
#: The gate — see `has_pending_work`. Runs from the repo's own venv, the same
#: one the pm2 services use, because it imports `services.task_board`.
GATE="$REPO_DIR/scripts/taskauto_pending.py"
GATE_PY="$REPO_DIR/.venv/bin/python"
#: The gate's "I looked, and there is nothing" code. Any OTHER non-zero is a
#: crash and must NOT be read as an answer — see `has_pending_work`.
GATE_NOTHING_PENDING=10
#: A run sitting queued longer than this means nothing is picking work up —
#: the runner is down while this host is still fine. Generous, because a long
#: sweep legitimately makes the next one queue behind it (concurrency group).
STUCK_QUEUE_MIN=45

# cron runs with a near-empty PATH. gh is in ~/.local/bin; node comes from fnm,
# whose *shell* path (/run/user/…/fnm_multishells/…) is per-session and will not
# exist here — the `aliases/default` symlink is the stable one.
export PATH="$HOME/.local/bin:$HOME/.local/share/fnm/aliases/default/bin:/usr/local/bin:/usr/bin:/bin"

log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

# EVERY vault call below depends on this line, and it has to come after `log`.
#
# dev-vault resolves the repo's key from `process.cwd()` —
# `resolve(process.cwd(), '.devvault.local.json')`, packages/dev-vault/dev-vault.mjs
# — and cron runs a job from $HOME, where that file does not exist. So
# `node "$VAULT"` exits 1 with "drop it in .devvault.local.json", and the
# caller sees a failure it has no way to read as "wrong directory".
#
# That was not theoretical. `report()` is the only alerting path this script
# has, and under cron it could never authenticate, so every failure it ever
# tried to report died as "WARNING: could not report ... to monitoring-api" in
# a log file nobody reads — layer 3 has been silently voiceless the whole time.
# Verified 2026-09-04: the identical vault invocation exits 1 from $HOME and 0
# from here.
#
# `cd` rather than a DEVVAULT_FILE override because the gate needs this working
# directory anyway; one line that fixes both beats two that each fix one.
cd "$REPO_DIR" || {
  log "ERROR: cannot cd to $REPO_DIR — the vault key is only readable from there"
  exit 1
}

# ---------------------------------------------------------------------------
# Telling someone when THIS script is the thing that is broken.
#
# The workflow reports its own outcome, and each run reports its predecessor's
# (taskauto.yml, "Report the PREVIOUS run"). Both of those need a run to have
# happened. When the dispatch itself fails there IS no run, so this script is
# the only witness — and until now it wrote "ERROR" to a log file nobody reads.
#
# The credential comes through the vault broker, which is a dependency worth
# naming: a sealed vault means no report. That is acceptable here precisely
# because the failures this reports (gh unauthenticated, dispatch refused,
# runner not consuming the queue) are independent of whether the vault is
# sealed. It is not acceptable as the ONLY alerting path, which is why it
# isn't one.
#
# Best-effort throughout: reporting must never stop the sweep being dispatched.
# ---------------------------------------------------------------------------
report() {  # report <status> <error-text>
  local status="$1" err="${2:-}"
  [ -f "$VAULT" ] || { log "no vault script at $VAULT — cannot report"; return 0; }
  command -v node >/dev/null 2>&1 || { log "no node on PATH — cannot report"; return 0; }

  local payload
  payload=$(jq -n --arg st "$status" --arg err "$err" \
    '{job_name: "tenhands:taskauto-cron", status: $st, duration_ms: 0}
     + (if $err == "" then {} else {error: $err} end)') || return 0

  # The key only ever exists in the child process' environment.
  PAYLOAD="$payload" timeout 60 node "$VAULT" -- bash -c '
      curl -sS -f -X POST https://hadoku.me/health/api/jobs \
        -H "X-User-Key: $HADOKU_SERVICE_KEY" \
        -H "Content-Type: application/json" \
        --data "$PAYLOAD" >/dev/null
    ' >/dev/null 2>&1 \
    && log "reported $status to monitoring-api" \
    || log "WARNING: could not report $status to monitoring-api"
}

#: Report a failure, and remember we did — so the recovery is reportable too.
#: Without the state file a recovery never fires, the alert stays open, and the
#: NEXT real breakage arrives as a throttled reminder instead of a new alert.
fail() {
  mkdir -p "$(dirname "$STATE")" 2>/dev/null || true
  log "ERROR: $1"
  report failed "$1"
  echo failed > "$STATE" 2>/dev/null || true
  exit 1
}

#: Only reports on the transition, so a healthy cron stays silent instead of
#: writing 96 rows a day to say nothing happened.
recovered_if_needed() {
  if [ "$(cat "$STATE" 2>/dev/null || echo ok)" = "failed" ]; then
    report succeeded ""
    echo ok > "$STATE" 2>/dev/null || true
  fi
}

if ! command -v gh >/dev/null 2>&1; then
  fail "gh not on PATH — cannot fire the backstop sweep"
fi

# `gh` needs a credential under cron, where there is no interactive keyring.
# GH_TOKEN in the environment wins; otherwise fall back to whatever `gh auth`
# has stored for this user. Fail loudly rather than silently not sweeping —
# a backstop that stopped working without saying so is the failure mode this
# whole file exists to prevent.
if [ -z "${GH_TOKEN:-}" ] && ! gh auth status >/dev/null 2>&1; then
  fail "gh is not authenticated and GH_TOKEN is unset — backstop sweep did NOT run"
fi

# Is anything actually CONSUMING what we dispatch?
#
# The other failure with no run to report it: the host is fine, this script
# keeps firing happily, and the self-hosted runner is dead — so every dispatch
# lands in a queue nobody drains. Dispatching succeeds, no run ever completes,
# and both of the in-workflow reporters need a run that ran. From out here it
# is one cheap query, and a queue that is not moving is unambiguous.
oldest_queued=$(gh run list --workflow=taskauto.yml --repo "$REPO" --limit 20 \
                  --json status,createdAt \
                  --jq '[.[] | select(.status == "queued" or .status == "pending")
                             | .createdAt] | sort | first' 2>/dev/null || echo "")

if [ -n "$oldest_queued" ] && [ "$oldest_queued" != "null" ]; then
  queued_epoch=$(date -u -d "$oldest_queued" +%s 2>/dev/null || echo 0)
  if [ "$queued_epoch" -gt 0 ]; then
    waited_min=$(( ( $(date -u +%s) - queued_epoch ) / 60 ))
    if [ "$waited_min" -ge "$STUCK_QUEUE_MIN" ]; then
      fail "a taskauto run has been queued ${waited_min}m (>= ${STUCK_QUEUE_MIN}m) — the self-hosted runner is not consuming work"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# THE GATE: is there anything a sweep would actually advance?
#
# Firing a run to prove an empty board is still empty is what made this job
# ~25% of every job the fleet reported. The boards are empty nearly all of the
# time, so ask from HERE — a few board-API calls off the host — and dispatch
# only on a yes. An idle hour then costs no Actions run, no runner slot and no
# row in the job ledger. `scripts/taskauto_pending.py` holds the definition of
# "pending" and the reasoning for each case.
#
# ONLY the exact `nothing pending` code suppresses the sweep. Everything else
# — a crash, a missing venv, an unreadable board, a traceback — falls through
# and dispatches. That asymmetry is the whole safety argument: a broken gate
# must degrade into the old unconditional cron, never into silence, because a
# gate that quietly answers "no work" whenever it is broken has deleted the
# backstop rather than made it cheaper.
#
# Deliberately NOT reported as a failure when it errors. The sweep still goes
# out, so nothing is lost, and the run it dispatches does its own reporting;
# paging on a degraded optimisation would be noise about noise.
# ---------------------------------------------------------------------------
has_pending_work() {
  [ -x "$GATE_PY" ] || { log "no venv python at $GATE_PY — sweeping unconditionally"; return 0; }
  [ -f "$GATE" ]    || { log "no gate script at $GATE — sweeping unconditionally"; return 0; }
  [ -f "$VAULT" ]   || { log "no vault script at $VAULT — sweeping unconditionally"; return 0; }
  command -v node >/dev/null 2>&1 || { log "no node on PATH — sweeping unconditionally"; return 0; }

  # The board key reaches the gate the same way it reaches `report`: only ever
  # in the child process' environment, never in this shell's.
  local rc=0
  timeout 120 node "$VAULT" -- "$GATE_PY" "$GATE" || rc=$?

  case "$rc" in
    0)  return 0 ;;
    "$GATE_NOTHING_PENDING") return 1 ;;
    *)  log "gate exited $rc (not a verdict) — sweeping unconditionally"
        return 0 ;;
  esac
}

if ! has_pending_work; then
  log "nothing pending on any board — no sweep dispatched"
  # A skipped tick is still a HEALTHY tick: the check ran, the vault answered,
  # the board answered. If a previous run reported a failure, that has now
  # recovered and has to be said, or the alert stays open until the next time
  # a board happens to be busy.
  recovered_if_needed
  exit 0
fi

# `live=true mode=pr` matches what the workflow does on its own triggers:
# open a pull request, never merge. A human still presses the button.
if gh workflow run taskauto.yml --repo "$REPO" -f live=true -f mode=pr; then
  log "backstop sweep dispatched"
  recovered_if_needed
else
  fail "could not dispatch the backstop sweep"
fi
