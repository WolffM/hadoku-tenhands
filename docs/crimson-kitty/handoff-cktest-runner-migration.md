# cktest-runner laptop migration — brief for hadoku_site agent

**From:** vibedispatch (crimson-kitty pipeline)
**Date:** 2026-05-03
**Context:** main Windows host pm2 fleet is hitting memory pressure;
migrating heavy workloads to a 3-laptop Debian-trixie pool. cktest-runner
is the first migration candidate.

## What cktest-runner is

A Flask service in `scripts/cktest-runner/server.py` that:
1. Receives `POST /run {fork_slug, branch, command}` from the worker
2. Shallow-clones the fork branch, detects language, installs deps
3. Runs the command, captures stdout+stderr+timing
4. Returns JSON

Called by the `run_test_command` activity (`backend/temporal/activities/test_runner.py`)
over HTTP. The activity reads `TEST_RUNNER_URL` from env to know where to call.

Already brought up once-by-hand on a `debian-cktest` WSL distro on the
main Windows host (this turn). Toolchains installed: git, python3+flask,
go, cargo, rustc. Still pending: node + pnpm + gh CLI install, then
launch the server.

## Why this is a clean first migration

- **Self-contained:** no shared state, no DB, no auth tokens, no cookies
- **Stateless:** in-flight tmp dirs only, all under `/tmp`
- **Trivial swap surface:** caller reads `TEST_RUNNER_URL` from env;
  changing hosts is one wrapper-config edit + a deploy
- **No upstream dependency on it:** if the runner is down, the worker's
  `run_test_command` activity gracefully no-ops and verification falls
  back to text-only

## Resource request

### Per-job characteristics

| Workload | Peak RAM | Peak disk | Wall time |
|---|---|---|---|
| `go test` typical | ~1 GB | ~2 GB | 30s–2 min |
| `pytest` typical | ~1.5 GB | ~3 GB | 30s–3 min |
| `pnpm install + vitest` | 4–6 GB | 5–10 GB | 1–5 min |
| `cargo test` medium | ~3 GB | ~5 GB | 1–4 min |
| Big monorepo (Next.js / Vite) | 8–10 GB | 15+ GB | 3–8 min |

### Aggregate sizing (NEW constraint, surfaced 2026-05-03)

Expect to accumulate **20–50 cloned repos before cleanup catches up** —
high-concurrency batches, debugging holds keeping tmp dirs around, or
cleanup lag during incidents. So multipliers compound:

| Resource | Minimum | Recommended |
|---|---|---|
| RAM | 16 GB (single concurrent job) | 32 GB (2–3 concurrent + headroom) |
| Disk | 200 GB free | 500 GB+ free |
| Disk type | HDD tolerable | SSD strongly preferred — `pnpm install` / `cargo build` are small-file-IO heavy |
| CPU | 4 cores | 8+ cores (helps `go test -p 8`, `cargo test --jobs N`) |
| Network | 100 Mbps stable | gigabit if available |

### Suggested host mapping for the 3-laptop pool

- **Strongest (32+ GB, 500+ GB SSD):** cktest-runner. It's where the
  actual resource pressure lives.
- **Medium (16 GB):** warm spare for cktest, or home for a followup
  migration like scraper.
- **Weakest (8 GB):** mgmt-api warm replica, standby, or off.

Routing only the heaviest workload to the strongest box matches actual
crimson-kitty batch behavior — most batches dispatch 5–10 issues that
go through verify roughly serially under the Copilot concurrency cap.
One-job-at-a-time on one well-spec'd box covers ~95% of cases.

## Asks from hadoku_site

1. **Cross-host pm2 management story.**
   - Do laptops run their own pm2 daemon, or does main PC's pm2 reach
     across hosts (pm2's deploy-via-ssh, or SSH-from-mgmt-api)?
   - How do laptops get new code when vibedispatch publishes?
     `packages_updated` currently triggers redeploy on the main host
     only. cktest-runner code lives at `scripts/cktest-runner/` —
     does it need to be in a separate publishable artifact, or is
     a per-laptop git pull from main enough?

2. **Connectivity / addressing.**
   - Laptops on home LAN: direct IP works if we don't move the runner.
   - Host-agnostic addressing (laptop reboots, gets new DHCP IP,
     runner Just Works): which layer handles it? Tailscale magic-DNS,
     mDNS, a mgmt-api proxy, something else?
   - This decides what `TEST_RUNNER_URL` will look like.

3. **Auth model for cross-host calls.**
   cktest-runner has no auth today (binds localhost-only inside WSL2).
   If it's reachable on a LAN IP / Tailnet, want to add a Bearer-header
   check? My take: vault key + Bearer is cheap defense in depth.
   Alternative: trust the network boundary (Tailscale ACLs, LAN-only).

4. **Daemonization pattern.**
   Initial bring-up is `python3 server.py` foreground. Should each
   laptop have its own pm2 wrapper (analog to `vibedispatch-wrapper.mjs`
   but for cktest-runner)? Or use systemd on the laptops? pm2 fits
   your existing patterns + lets the vault-fetch shim inject the
   new auth key.

5. **Concurrency / preemption model.**
   If we hit a 32 GB RAM ceiling on a busy batch, pick:
   - Per-job concurrency limit on the runner side (in-process semaphore)
   - Multi-runner round-robin (worker picks least-loaded of N runners)
   - Job queueing inside the runner (in-memory queue + 503 when full)
   I'll implement whichever pattern you pick.

6. **Toolchain drift.**
   cktest-runner allowlist:
   `pytest python python3 py.test go go.exe npm pnpm yarn npx cargo rustc make bash sh`.
   If a future batch needs Java/Maven, Ruby/Bundler, etc., who owns
   adding the toolchain — bake all upfront, lazy-install per job,
   versioned distro snapshots?

## What I own on the vibedispatch side

Happy to ship in 1–2 commits:

- Service auth (add Bearer check, ~15 LOC)
- Job queueing / 503 backpressure (`asyncio.Semaphore`, ~30 LOC)
- Multi-runner round-robin or sticky-by-fork-slug
  (`TEST_RUNNER_URLS=url1,url2`, ~50 LOC)
- Tighter tmp-dir cleanup (already in `finally`; could add periodic
  background reaper for orphans)
- Multiple workers per host (asyncio.Pool concurrency)

Not adjusting on:
- Where the service runs (your call)
- How it's deployed (your patterns)
- DNS / IP / connectivity (your call)

## Concrete next-step request

Once you've decided routing / auth / concurrency, send back:

1. DNS name or IP that vibedispatch should put in `TEST_RUNNER_URL`
   (vault key name if it's a secret; plain env var if not)
2. Auth shape (Bearer + vault-key name, or no auth)
3. Concurrency pattern (single, queue, multi-runner)

I'll wire the worker side to match in one commit.

## Useful artifacts already shipped

- `scripts/cktest-runner/server.py` — the service
- `scripts/cktest-runner/requirements.txt` — flask only
- `scripts/cktest-runner/README.md` — full setup procedure including
  toolchain installs, copy-into-distro instructions, validation curl
- `backend/temporal/activities/test_runner.py` — the worker-side
  caller; reads `TEST_RUNNER_URL` env, POSTs to `/run`, persists
  output to `06-verified/test_output.txt`
- `backend/tests/temporal/test_test_runner.py` — 10 tests covering
  the activity's behavior

The service has been imported into the `debian-cktest` WSL distro on
the main Windows host as a starting point; once you tell me which
laptop to put it on instead, I can rsync the service over and tear
down the WSL distro.
