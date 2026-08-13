Operational runbook for the dispatch demo: seed a sandbox, dispatch preview-only
work through the real pipeline, watch it, then discard everything.

Argument (`$ARGUMENTS`): `start` | `status <batch-id>` | `reset <batch-id>`.

The demo targets a throwaway sandbox repo (`WolffM/tenhands-demo-target`, or
`$CRIMSON_DEMO_REPOS`). Every demo batch id starts with `demo-`, which makes the
server force `submit_to_upstream=false` and restrict the batch to the sandbox
allowlist — so a demo can NEVER open an upstream PR, even if someone clicks
approve in the inbox. All scripts refuse to mutate any repo but the sandbox.

## One-time setup (before the first demo ever)

1. `python3 scripts/demo/bootstrap_sandbox.py` — creates the sandbox repo from
   `demo/sandbox-template/` with backdated history, creates labels, and triggers
   an aggregator index.
2. Wait for the aggregator to index it, then confirm the health score:
   `python3 scripts/demo/bootstrap_sandbox.py --check` and
   `python3 scripts/demo/preflight.py` (needs `maintainerHealthScore >= 10`).
3. `python3 scripts/demo/seed_issues.py` — creates the three demo issues and
   records their numbers in `demo/issues/seeded.lock.json` (commit that file).

## `start`

1. `python3 scripts/demo/preflight.py` — everything must be READY (Temporal +
   worker up, gh auth, judge canary, aggregator health, sandbox clean, no
   leftover demo batches).
2. `python3 scripts/demo/seed_issues.py --verify` — seeded issues open, correct.
3. `python3 scripts/demo/run_demo.py --count 2` — dispatches a preview-only
   `demo-YYYYMMDD-HHMM` batch (2 issues fit the Copilot concurrency cap of 2).
   Prints the watch links and the UI URL.
4. Open the UI at the printed `?view=temporal&batch=<id>` link and narrate the
   states walking candidate → forked → reproduced (a Copilot draft PR appears
   live on the sandbox) → fixed → verified → reviewed → replicated, then the
   inbox shows `operator_signoff`.
5. Click **Approve** in the inbox. Because this is a demo batch the run
   terminates at `submittable` — the preview PR exists on the fork, nothing
   reaches upstream. That is the brake, on stage.

Timing note: a real Copilot run is ~45–90 min end to end. Choreograph it:
fire a **warm** batch ~2h before (`run_demo.py`), narrate the early states on a
**fresh** batch dispatched live, and demo the late states + signoff on the warm
one.

## `status <batch-id>`

`python3 scripts/demo/run_demo.py --dry-run` to preview a payload, or poll:
`GET {base}/api/temporal/batch/<batch-id>` and `GET {base}/api/temporal/inbox`.

## `reset <batch-id>`

`python3 scripts/demo/teardown.py <batch-id>` — aborts/terminates the workflows,
closes all sandbox PRs and their branches, closes context issues, reopens the
seeded issues byte-identical, resolves this batch's inbox entries, archives and
deletes the batch's `state/` dir (so it leaves the batches list and Archive
tab), and re-runs preflight. Add `--deep-clean` to delete context issues rather
than close them, `--no-archive` to skip the tarball.

After `reset`, `preflight.py` should report READY again — the sandbox is back to
three open seeded issues, no open PRs, and the demo can run again.
