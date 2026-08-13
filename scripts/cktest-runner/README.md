# cktest-runner

A small sandbox HTTP service that runs verification tests for the crimson-kitty
pipeline on an **isolated host**, separate from the machine that holds tokens.
The tenhands worker reaches it from the `run_test_command` activity (see
`backend/temporal/activities/test_runner.py`).

## Why this exists

A 2026-04-30 batch confirmed the coding agent won't reliably run *and* capture
test output even with explicit instructions. So the verify phase is split: the
agent identifies the test command (one shell line, committed to
`05-fixed/test_command.txt`), and this service runs it in a clean sandbox and
returns stdout + stderr + exit_code. Running agent-authored commands on a
dedicated, credential-free host — behind a bearer token and a command allowlist
— keeps arbitrary shell away from anything sensitive.

## API

```
GET  /health                                 → {ok, service}   (unauth — probe)
POST /run                                    → {stdout, stderr, exit_code,
                                                duration_ms, language}
                                              | {error, ...} on input/runtime fail
     headers: Authorization: Bearer <CKTEST_RUNNER_BEARER>
     body: {fork_slug, branch, command}
```

Status codes:

- `200` — runner accepted + executed (body indicates success/error)
- `400` — input validation fail (slug shape, branch shape, allowlist)
- `401` — missing/mismatched bearer (also if the server has no bearer
  configured — fail closed)
- `503` — semaphore busy; response carries `Retry-After`. The worker retries
  with exponential backoff.

Per-job flow:

1. Validate bearer header
2. Acquire concurrency semaphore (non-blocking) — 503 if busy
3. Validate inputs (slug + branch shape, command first-token allowlist)
4. Shallow-clone the fork branch to a temp dir
5. Detect language by lockfile presence (pnpm-lock.yaml, go.mod, Cargo.toml,
   pyproject.toml, …)
6. Install deps (`pnpm install --frozen-lockfile`, `go mod download`, etc.)
7. Run the command, capture stdout + stderr + timing
8. Cleanup temp dir, release semaphore

## Deployment

The service is packaged as a systemd unit and runs on a dedicated sandbox host.
Bring-up is: sync the repo → run `provision.sh` (bakes toolchains, creates the
service user, installs the unit) → drop a per-host vault service key scoped to
just `CKTEST_RUNNER_BEARER` → `systemctl enable --now cktest-runner`. The unit's
`ExecStartPre` hook (`fetch-bearer.sh`) pulls the bearer from the vault at start;
if the vault is sealed or the key is rejected, the unit refuses to start — no
fallback to a stale local file.

## Local testing (no auth infrastructure)

```bash
cd scripts/cktest-runner
pip install -r requirements.txt
CKTEST_RUNNER_BEARER=local-dev-secret python3 server.py
# → cktest-runner starting on 0.0.0.0:5500 (max_concurrent=1)

# In another shell:
curl http://localhost:5500/health
curl -X POST http://localhost:5500/run \
  -H "Authorization: Bearer local-dev-secret" \
  -H "Content-Type: application/json" \
  -d '{"fork_slug":"owner/repo","branch":"crimson-kitty-1234","command":"pytest -q"}'
```

The server refuses to start without `CKTEST_RUNNER_BEARER` — that's the
fail-closed contract that makes `fetch-bearer.sh` failures visible.

## Configuration env vars

| Var                        | Default                          | Meaning                                                           |
| -------------------------- | -------------------------------- | ----------------------------------------------------------------- |
| `CKTEST_RUNNER_BEARER`     | _(unset → refuses to start)_     | Shared secret for `Authorization: Bearer …` on `/run`             |
| `CKTEST_PORT`              | `5500`                           | Bind port                                                         |
| `CKTEST_MAX_CONCURRENT`    | `1`                              | Semaphore capacity; sized for the sandbox host's RAM ceiling      |
| `CKTEST_RETRY_AFTER_S`     | `60`                             | `Retry-After` header value when 503'ing                           |
| `CKTEST_PER_JOB_TIMEOUT_S` | `300`                            | Hard cap on a single test run                                     |
| `CKTEST_SERVICE_KEY_PATH`  | `/etc/cktest-runner/service.key` | (`fetch-bearer.sh`) where the per-host vault key lives            |
| `CKTEST_ENV_OUT`           | `/run/cktest-runner/env`         | (`fetch-bearer.sh`) where to write the bearer for systemd to load |

## Auth model

- `/health` is unauth'd (monitoring probe convention).
- `/run` requires `Authorization: Bearer <CKTEST_RUNNER_BEARER>`, constant-time
  compared against the env var. Mismatch / missing header / no bearer
  configured → `401`.
- The bearer comes from the vault via the `ExecStartPre` hook; no fallback to a
  stale file.
- Network ACL is the first defense layer; the bearer is defense-in-depth; the
  command allowlist below is the third (defense against an agent committing
  `rm -rf /` to `test_command.txt`).

## Concurrency model

`threading.Semaphore(CKTEST_MAX_CONCURRENT)` (default 1). The worker retries a
503 with exponential backoff before falling back to text-only verify — see
`run_test_command`. Default of 1 because a big-monorepo job can use 8–10 GB, so
concurrent runs on a memory-constrained sandbox are OOM-risky. Lift the limit if
batches start hitting the 503 path frequently (and re-evaluate the host).

## Daily test allowlist

Commands whose first token is in this set get to run; everything else is
rejected with HTTP 400:

```
pytest python python3 py.test
go go.exe
npm pnpm yarn npx
cargo rustc
make
bash sh
```

The allowlist is intentionally narrow — a typo'd command from the agent fails
loudly here rather than executing arbitrary shell on the sandbox host.

## Files in this directory

| File                    | Purpose                                                                                     |
| ----------------------- | ------------------------------------------------------------------------------------------- |
| `server.py`             | Flask service (Bearer + Semaphore + 503)                                                     |
| `requirements.txt`      | `flask>=3.0,<4`                                                                              |
| `cktest-runner.service` | systemd unit (dedicated service user, ExecStartPre=fetch-bearer.sh, Restart, hardening flags) |
| `fetch-bearer.sh`       | Pre-start hook — curls the vault broker with the per-host service key, writes the env file   |
| `provision.sh`          | One-time bake: apt deps, Node + pnpm, gh CLI, service user, unit install                     |
