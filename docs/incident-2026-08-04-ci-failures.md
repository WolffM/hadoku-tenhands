# Incident: taskauto run died with its runner — 1 failure (2026-08-04)

> Written 2026-08-05 by an outside investigation run from `hadoku_site`, working
> only from GitHub Actions logs and commit history — it never ran anything in
> this checkout. Treat every claim below as a **hypothesis to verify against
> this repo's own evidence** before acting on it. Verify first, then fix.

## What the daily CI digest showed

`tenhands / Task automation` — **1 failure**, latest run green. Failed run:
30950996997, started 2026-08-04 21:07 UTC on runner `hokon-tenhands`, marked
failed at 21:25.

## Evidence gathered from outside

- The run's logs are **gone** ("log not found") — nothing was ever uploaded.
  The job API shows the "Run the pipeline" step `cancelled` after ~17 minutes,
  the reporting step `skipped`, and "Complete job" stuck `in_progress`. That
  is the signature of the runner process dying mid-job, not of the pipeline
  failing.
- `taskauto.yml` already documents this exact incident in the comment on its
  first step: *"On 2026-08-04 the self-hosted runner lost its connection to
  GitHub mid-job — BrokerServer SocketException (125), then renewjob 404, then
  'Runner will be shutdown for UserCancelled'"* — and the mitigation (each run
  reports its predecessor's conclusion to `/health/api/jobs`, because a dead
  runner cannot self-report) is merged.
- The job-level `timeout-minutes: 45` was not the killer (the job died at ~17
  minutes).

## Root-cause hypothesis

Infrastructure, not code: the `hokon-tenhands` runner lost its GitHub
connection (or its host restarted) mid-job. The workflow-level mitigation for
the *reporting* gap is already in place; the *disconnect itself* is the open
question.

## Your task

1. **Verify independently.** Confirm the predecessor-reporter actually worked:
   the next scheduled run after 21:25 UTC on 2026-08-04 should have upserted
   `gha_30950996997` as failed into `/health/api/jobs` — check the record
   exists. Then check the runner's own logs on hokon around 21:07–21:25 UTC
   for the SocketException, and grep further back: is this disconnect a
   one-off or a recurring pattern on this host?
2. **Then fix what verification confirms.**
   - If disconnects recur: harden the runner service (network/DNS on hokon has
     a history — systemd-resolved split-DNS and a Tailscale instability track
     are already known on that host; a correlation with those is worth ruling
     in or out).
   - If the predecessor-reporter did NOT produce the record, that mitigation
     has a hole — fix it before the next silent death.
   - Consider whether an interrupted `TASKAUTO_LIVE` pipeline run can leave
     the board or checkout in a state the next run mishandles (the
     `cancel-in-progress: false` concurrency group serialises runs, but a
     killed run never released cleanly — verify the next run's log shows a
     clean start).

If your investigation contradicts anything above, trust your evidence, not
this document — and correct this file so the record is right.
