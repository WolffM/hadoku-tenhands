# Dispatch demo

A repeatable, discard-after demonstration of the crimson-kitty pipeline: seed a
throwaway sandbox repo with real small bugs, dispatch them to Copilot coding
agents through the actual Temporal state machine, watch the work flow in the UI,
then reset so it can be run again.

Nothing here can reach a real upstream repo. Demo batch ids start with `demo-`,
which the dispatch endpoint uses to force `submit_to_upstream=false` and to
restrict the batch to the sandbox allowlist (`CRIMSON_DEMO_REPOS`). Every script
also refuses to mutate any repo but the sandbox.

## Layout

- `sandbox-template/` — the source of the sandbox project (`demotool`, a tiny
  CSV report tool). Three genuine bugs are seeded in edge-case paths the test
  suite does not cover, so the repo is green when seeded but each bug truly
  reproduces:
  - issue 01 — `page_count` floor-division drops the final partial page
  - issue 02 — `to_display` swaps month/day (MM/DD vs the promised DD/MM)
  - issue 03 — `average([])` raises `ZeroDivisionError`
- `issues/*.md` — the issue manifests (front-matter + Steps/Expected/Observed),
  seeded verbatim so dispatch payloads are deterministic. `seeded.lock.json`
  records the created issue numbers (committed).
- `archive/` — teardown drops evidence tarballs here (gitignored).

## Running it

See the `/demo` skill (`.claude/commands/demo.md`) for the full runbook:
`bootstrap_sandbox.py` (one-time) → `seed_issues.py` → `preflight.py` →
`run_demo.py` → watch in the UI → `teardown.py`.
