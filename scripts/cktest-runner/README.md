# cktest-runner

Sandbox HTTP service that runs verification tests for the crimson-kitty
pipeline. Lives inside a dedicated `debian-cktest` WSL2 distro on the
production Windows host. Called over host-loopback by the worker's
`run_test_command` activity (see `backend/temporal/activities/test_runner.py`).

## Why this exists

The v4 batch (2026-04-30) confirmed Copilot won't run + capture test output
reliably even with explicit instructions — 100% adoption failure. We split
the verify phase: Copilot identifies the test command (one shell line,
committed to `05-fixed/test_command.txt`), this service runs it in a clean
sandbox and returns stdout+stderr+exit_code.

## API

```
GET  /health                                 → {ok, service}
POST /run                                    → {stdout, stderr, exit_code,
                                                duration_ms, language}
                                              | {error, ...} on input/runtime fail
     body: {fork_slug, branch, command}
```

Per-job flow:
1. Validate inputs (slug + branch shape, command first-token allowlist)
2. Shallow-clone the fork branch to `/tmp/cktest-{job_id}/`
3. Detect language by lockfile presence (pnpm-lock.yaml, go.mod, Cargo.toml,
   pyproject.toml, …)
4. Install deps (`pnpm install --frozen-lockfile`, `go mod download`, etc.)
5. Run the command with shell=True, capture stdout+stderr+timing
6. Return the response, cleanup tmp dir

## Setup (one-time, on the prod Windows host)

These steps run inside the `debian-cktest` WSL distro. The distro itself
is created by cloning `Debian` with `wsl --export Debian … && wsl --import
debian-cktest …`.

```bash
# 1. Base toolchains (idempotent)
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git curl ca-certificates build-essential \
  python3 python3-pip python3-venv python3-flask \
  golang rustc cargo

# 2. Node + pnpm
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs
npm install -g pnpm

# 3. gh CLI (for cloning + auth)
type -p gh || (
  apt-get install -y gpg
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
  chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list
  apt-get update
  apt-get install -y gh
)

# 4. Copy this directory into the cktest distro (one-time):
#    From the Windows host PowerShell:
#      Copy-Item -Recurse C:\Users\Hadoku\Documents\repos\vibedispatch\scripts\cktest-runner \
#                          \\wsl$\debian-cktest\opt\cktest-runner

# 5. Start the service (foreground for now; daemonize via pm2/systemd
#    once it's been validated end-to-end):
cd /opt/cktest-runner
python3 server.py
# → cktest-runner starting on 0.0.0.0:5500
```

## Verifying from the worker host

```powershell
# From any Windows shell — WSL2 forwards localhost across distros
curl http://localhost:5500/health
# → {"ok": true, "service": "cktest-runner"}

curl -X POST http://localhost:5500/run \
     -H "Content-Type: application/json" \
     -d '{"fork_slug":"WolffM/gofiber-fiber","branch":"crimson-kitty-4226","command":"go test ./middleware/logger/... -run TestBytesSent -v"}'
```

## Configuration env vars

| Var | Default | Meaning |
|---|---|---|
| `CKTEST_PORT` | `5500` | Bind port |
| `CKTEST_PER_JOB_TIMEOUT_S` | `300` | Hard cap on a single test run |

## Auth

None. The service binds to `0.0.0.0:5500` inside the cktest distro,
reachable only via WSL2 localhost forwarding from the same host. Don't
expose this on the public internet — the command allowlist gate is a
hygiene check, not a security boundary.

## Daemonization (followup)

Initial bring-up runs the server in the foreground (`python3 server.py`)
to make debugging easy. Once it's been validated end-to-end on a real
batch, wrap it in a pm2 service alongside the existing wrappers in
`hadoku_site/services/pm2/`. Suggested wrapper name: `cktest-runner`.

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
