# cktest-runner

Sandbox HTTP service that runs verification tests for the crimson-kitty
pipeline. Lives on `claw-3` (claw fleet, Debian Trixie) as a systemd
service. The tenhands worker (running on the Linux host)
reaches it over Tailscale at `http://claw-3:5500` from the
`run_test_command` activity (see `backend/temporal/activities/test_runner.py`).

Authoritative migration plan: `hadoku_site/docs/operations/cktest-runner-migration.md`
+ `hadoku_site/docs/planning/claw-fleet-migration.md` (Phase 0).

## Why this exists

The v4 batch (2026-04-30) confirmed Copilot won't run + capture test output
reliably even with explicit instructions — 100% adoption failure. We split
the verify phase: Copilot identifies the test command (one shell line,
committed to `05-fixed/test_command.txt`), this service runs it in a clean
sandbox and returns stdout+stderr+exit_code.

## API

```
GET  /health                                 → {ok, service}
                                              (unauth — monitoring probe)
POST /run                                    → {stdout, stderr, exit_code,
                                                duration_ms, language}
                                              | {error, ...} on input/runtime fail
     headers: Authorization: Bearer <CKTEST_RUNNER_BEARER>
     body: {fork_slug, branch, command}
```

Status codes:

- `200` — runner accepted + executed (body indicates success/error)
- `400` — input validation fail (slug shape, branch shape, allowlist)
- `401` — missing/mismatched bearer (also returned if the server has no
  bearer configured — fail closed)
- `503` — semaphore busy; response carries `Retry-After: 60`. Worker
  retries with exponential backoff (1 → 2 → 4 → 8s).

Per-job flow:

1. Validate bearer header
2. Acquire concurrency semaphore (non-blocking) — 503 if busy
3. Validate inputs (slug + branch shape, command first-token allowlist)
4. Shallow-clone the fork branch to `/tmp/cktest-{job_id}/`
5. Detect language by lockfile presence (pnpm-lock.yaml, go.mod,
   Cargo.toml, pyproject.toml, …)
6. Install deps (`pnpm install --frozen-lockfile`, `go mod download`, etc.)
7. Run the command with `shell=True`, capture stdout+stderr+timing
8. Cleanup tmp dir, release semaphore

## Deployment to claw-3

The bring-up flow is **rsync the repo → run `provision.sh` → start the
unit**. There's no per-host config drift — every claw-resident artifact
is in this directory + `/etc/cktest-runner/service.key`.

### One-time, from the main host

```bash
# 1. Push the repo to claw-3 (Tailscale-reachable as `claw-3`)
ssh claw3-admin 'sudo install -d -o $USER -g $USER /srv/tenhands'
rsync -avz --delete --exclude='.git' --exclude='node_modules' \
  ~/repos/tenhands/ \
  claw3-admin:/srv/tenhands/

# OR — if the repo's already cloned on claw-3, just:
ssh claw3-admin 'cd /srv/tenhands && git pull'
```

### One-time, on claw-3 (as admin user)

```bash
# 2. Bake toolchains, create service user, install systemd unit (idempotent)
sudo bash /srv/tenhands/scripts/cktest-runner/provision.sh

# 3. (Operator) drop the per-host vault service key.
#    Generated on the main host with:
#      python hadoku_site/scripts/administration.py key-generate \
#        --tier service --name claws-cktest-fetcher \
#        --repo ../tenhands
#    ACL-scoped (broker side) to just CKTEST_RUNNER_BEARER.
sudo install -m 0600 -o cktest -g cktest \
  /tmp/claws-cktest-fetcher.uuid /etc/cktest-runner/service.key

# 4. Start the service (fetch-bearer.sh runs ExecStartPre, populates
#    /run/cktest-runner/env from the vault, then server.py boots)
sudo systemctl enable --now cktest-runner

# 5. Watch it come up
sudo journalctl -u cktest-runner -f --since '1 min ago'
```

### Updating after a code change

After committing changes to `scripts/cktest-runner/` and pushing to main:

```bash
ssh claw3-admin 'cd /srv/tenhands && git pull && sudo systemctl restart cktest-runner'
```

If the change touches `cktest-runner.service` itself:

```bash
ssh claw3-admin 'cd /srv/tenhands && git pull && \
  sudo systemctl daemon-reload && sudo systemctl restart cktest-runner'
```

(Future v2: hadoku_site mgmt-api fans the `packages_updated` webhook out
to a small claw-3 deploy hook that does the above automatically. v1 is
manual ssh — see migration brief.)

## Phase 0 checkpoints

These come from `hadoku_site/docs/planning/claw-fleet-migration.md`:

- **0.1** — `curl -H "Authorization: Bearer $K" http://claw-3:5500/health` from
  the main host returns `{"ok":true,"service":"cktest-runner"}`.
- **0.2** — issue 2 concurrent `POST /run` calls; the second returns
  `503` with `Retry-After: 60`.
- **0.3** — first crimson-kitty batch end-to-end with
  `TEST_RUNNER_URL=http://claw-3:5500`; worker logs show
  `run_test_command` activities completing with captured stdout/stderr.
- **0.4** — `ssh root@claw3 'free -h'` shows >2 GB free during the
  batch's heaviest verify (big-monorepo case).
- **0.5** — one full week of green batches; decommission the legacy
  local cktest sandbox on the main host.

## Local testing (laptop, no auth)

For local sanity checks of the server logic without a real vault, set the
bearer manually:

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
  -d '{"fork_slug":"WolffM/gofiber-fiber","branch":"crimson-kitty-4226","command":"go test ./middleware/logger/... -run TestBytesSent -v"}'
```

The server refuses to start without `CKTEST_RUNNER_BEARER` set — that's
the fail-closed contract that makes `fetch-bearer.sh` failures visible.

## Configuration env vars

| Var                        | Default                                                       | Meaning                                                            |
| -------------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------ |
| `CKTEST_RUNNER_BEARER`     | _(unset → refuses to start)_                                  | Shared secret for `Authorization: Bearer …` on `/run`              |
| `CKTEST_PORT`              | `5500`                                                        | Bind port                                                          |
| `CKTEST_MAX_CONCURRENT`    | `1`                                                           | Semaphore capacity. Sized for claw-3's 16 GB RAM ceiling           |
| `CKTEST_RETRY_AFTER_S`     | `60`                                                          | `Retry-After` header value when 503'ing                            |
| `CKTEST_PER_JOB_TIMEOUT_S` | `300`                                                         | Hard cap on a single test run                                      |
| `CKTEST_SERVICE_KEY_PATH`  | `/etc/cktest-runner/service.key`                              | (`fetch-bearer.sh`) where the per-host vault key lives             |
| `CKTEST_VAULT_BROKER_URL`  | `https://hadoku.me/mgmt/api/secrets/get/CKTEST_RUNNER_BEARER` | (`fetch-bearer.sh`) vault endpoint                                 |
| `CKTEST_ENV_OUT`           | `/run/cktest-runner/env`                                      | (`fetch-bearer.sh`) where to write the bearer for systemd to load  |

## Auth model

- `/health` is unauth'd (monitoring probe convention).
- `/run` requires `Authorization: Bearer <CKTEST_RUNNER_BEARER>`.
  Constant-time compare against the env var. Mismatch / missing
  header / no bearer configured → `401 unauthorized`.
- The bearer comes from the hadoku_site vault. systemd's
  `ExecStartPre=fetch-bearer.sh` runs at unit start, curls the broker
  with the per-host service key, and writes
  `/run/cktest-runner/env`. If the vault is sealed, the broker is
  unreachable, or the service key is rejected, the unit refuses to
  start — no fallback to a stale local file.
- The Tailscale ACL boundary is the first defense layer; bearer is
  defense-in-depth. The command-allowlist downstream is the third
  hygiene gate (defense against an agent committing `rm -rf /` to
  `test_command.txt`).

## Concurrency model

`threading.Semaphore(CKTEST_MAX_CONCURRENT)` (default 1). The worker
retries 503 with exponential backoff (1 → 2 → 4 → 8s, ~15s total)
before falling back to text-only verify — see
`backend/temporal/activities/test_runner.py`'s `run_test_command`.

Why 1 by default: claw-3's 16 GB RAM ceiling + Ollama co-tenancy makes
>1 concurrent big-monorepo job (8–10 GB each) genuinely OOM-risky. If
batches start landing in the 503 path frequently, lift the limit (and
re-evaluate the host).

## Daily test allowlist

Commands whose first token is in this set get to run; everything else
is rejected with HTTP 400:

```
pytest python python3 py.test
go go.exe
npm pnpm yarn npx
cargo rustc
make
bash sh
```

Add more as needed when batches start including new languages. The
allowlist is intentionally narrow — a typo'd command from the agent
fails loudly here rather than executing arbitrary shell on the
sandbox host.

## Files in this directory

| File                    | Purpose                                                                                    |
| ----------------------- | ------------------------------------------------------------------------------------------ |
| `server.py`             | Flask service (Bearer + Semaphore + 503)                                                   |
| `requirements.txt`      | `flask>=3.0,<4`                                                                            |
| `cktest-runner.service` | systemd unit (User=cktest, ExecStartPre=fetch-bearer.sh, Restart=always, hardening flags)  |
| `fetch-bearer.sh`       | Pre-start hook — curls vault broker with `/etc/cktest-runner/service.key`, writes env file |
| `provision.sh`          | One-time bake: apt deps, Node 20 + pnpm, gh CLI, service user, repo clone, unit symlink    |
