#!/usr/bin/env bash
#
# The taskauto backstop sweep, on a timer we actually own.
#
# WHY THIS EXISTS
#
# `.github/workflows/taskauto.yml` declares `schedule: '*/15 * * * *'`, and
# GitHub does not honour it. Measured across 73 consecutive delivered runs of
# that workflow:
#
#     configured                15 min
#     shortest gap observed     24 min   <- not one sample under this
#     mean gap                  ~45 min
#     max gap                   86 min
#
# GitHub deprioritises the `schedule` trigger and drops roughly two ticks in
# three. Tightening the expression does nothing, because the throttle is on
# delivery rather than on the expression. So the workflow's own backstop is,
# in practice, a ~45-minute timer that occasionally takes an hour and a half.
#
# We do not have to accept that. The runner is SELF-HOSTED — this box — so the
# only reason the schedule ever lived at GitHub is that the job happens to run
# in Actions. A crontab entry here fires on time, every time, and costs one
# `gh workflow run` call.
#
# The GitHub `schedule` block stays in the workflow deliberately. It is free,
# it is occasionally faster than us, and it is the one thing that still fires
# if this box's crontab is wiped by a reimage — which is exactly the failure
# this script would otherwise hide. Two unreliable timers beat one.
#
# WHY IT IS SAFE TO OVERLAP
#
# The workflow's `concurrency: taskauto` group serialises runs, so a tick that
# lands while a run is in flight queues rather than doubling up, and GitHub
# keeps only the newest pending run per group. An idle sweep is one board-API
# call and an exit, ~18 seconds, so an unnecessary tick costs nothing.
#
# INSTALL (on the runner host, as the runner user):
#
#     crontab -l | { cat; echo '*/15 * * * * /home/hadoku/repos/tenhands/scripts/taskauto-cron.sh >> /home/hadoku/logs/taskauto-cron.log 2>&1'; } | crontab -
#
# Verify it is firing:  tail -f ~/logs/taskauto-cron.log
# Verify runs land:     gh run list --workflow=taskauto.yml --limit 10

set -euo pipefail

REPO="WolffM/tenhands"

# cron runs with a near-empty PATH; gh lives in ~/.local/bin.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

if ! command -v gh >/dev/null 2>&1; then
  log "ERROR: gh not on PATH — cannot fire the backstop sweep"
  exit 1
fi

# `gh` needs a credential under cron, where there is no interactive keyring.
# GH_TOKEN in the environment wins; otherwise fall back to whatever `gh auth`
# has stored for this user. Fail loudly rather than silently not sweeping —
# a backstop that stopped working without saying so is the failure mode this
# whole file exists to prevent.
if [ -z "${GH_TOKEN:-}" ] && ! gh auth status >/dev/null 2>&1; then
  log "ERROR: gh is not authenticated and GH_TOKEN is unset — backstop sweep did NOT run"
  exit 1
fi

# `live=true mode=pr` matches what the workflow does on its own triggers:
# open a pull request, never merge. A human still presses the button.
if gh workflow run taskauto.yml --repo "$REPO" -f live=true -f mode=pr; then
  log "backstop sweep dispatched"
else
  log "ERROR: could not dispatch the backstop sweep (exit $?)"
  exit 1
fi
