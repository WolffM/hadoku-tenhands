#!/usr/bin/env bash
# provision.sh — bake toolchains + system deps for cktest-runner on claw-3.
#
# Idempotent. Runs as root (sudo). Re-running is safe — every step
# either checks-then-skips or uses idempotent install commands.
#
# Source of truth for the runner's required toolchains. New language /
# new test command first-token = PR to this script + re-run on claw-3:
#   ssh claw3-admin 'sudo bash /srv/tenhands/scripts/cktest-runner/provision.sh'
#
# Layout:
#   /srv/tenhands              — git clone, owned by cktest:cktest
#   /etc/cktest-runner/service.key — vault service key, mode 0600
#   /run/cktest-runner/env         — populated by fetch-bearer.sh at start
#   /etc/systemd/system/cktest-runner.service  — unit symlinked from repo

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "provision.sh: must be run as root (sudo)" >&2
  exit 1
fi

REPO_DIR="${REPO_DIR:-/srv/tenhands}"
RUNNER_DIR="${REPO_DIR}/scripts/cktest-runner"
SERVICE_USER="${SERVICE_USER:-cktest}"
SERVICE_GROUP="${SERVICE_GROUP:-cktest}"

echo "==> provision.sh starting (repo=${REPO_DIR}, user=${SERVICE_USER})"

# ── 1. Service user (idempotent)
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  echo "==> creating service user ${SERVICE_USER}"
  useradd --system --create-home --home-dir "/var/lib/${SERVICE_USER}" \
    --shell /usr/sbin/nologin "${SERVICE_USER}"
else
  echo "==> service user ${SERVICE_USER} already exists, skipping"
fi

# ── 2. Base toolchains (apt). Trixie has go 1.22+ in the default repos
#    which is fine — Go ≥ 1.21's GOTOOLCHAIN=auto will fetch newer
#    versions on demand per go.mod's `go N.NN` directive. apt rustc is
#    NOT installed here; rustup handles Rust below so each repo's
#    rust-toolchain.toml gets respected (and we can ship newer than
#    distro for things like bat@0.26 needing rustc 1.88).
echo "==> apt: base toolchains"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg \
  git build-essential make \
  python3 python3-pip python3-venv python3-flask python3-requests \
  golang

# ── 3. Node 20 + pnpm
if ! command -v node >/dev/null 2>&1 || ! node --version | grep -qE '^v(20|22|24)\.'; then
  echo "==> installing Node 20 from NodeSource"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
else
  echo "==> Node $(node --version) already installed, skipping"
fi
if ! command -v pnpm >/dev/null 2>&1; then
  echo "==> installing pnpm"
  npm install --global pnpm
else
  echo "==> pnpm $(pnpm --version) already installed, skipping"
fi

# ── 3b. Rust via rustup. Toolchain + cargo caches live under
#    /var/lib/cktest-{rustup,cargo} so they persist across systemd
#    restarts — PrivateTmp=true wipes /tmp on every restart, and a
#    fresh ~300MB toolchain download per restart isn't acceptable.
#
#    Why rustup instead of apt rustc: per-repo `rust-toolchain.toml`
#    pins the exact rustc version the project ships with (bat@0.26
#    needs 1.88, distro rustc lags by 6-12 months). rustup reads the
#    pin on every `cargo` invocation and auto-fetches if missing —
#    one-time download per version, cached forever afterward.
RUSTUP_HOME_DIR=/var/lib/cktest-rustup
CARGO_HOME_DIR=/var/lib/cktest-cargo
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0755 "${RUSTUP_HOME_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0755 "${CARGO_HOME_DIR}"

if [[ ! -x "${CARGO_HOME_DIR}/bin/rustup" ]]; then
  echo "==> installing rustup (RUSTUP_HOME=${RUSTUP_HOME_DIR}, CARGO_HOME=${CARGO_HOME_DIR})"
  sudo -u "${SERVICE_USER}" \
    RUSTUP_HOME="${RUSTUP_HOME_DIR}" \
    CARGO_HOME="${CARGO_HOME_DIR}" \
    bash -c 'curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path --default-toolchain stable --profile minimal'
else
  echo "==> rustup already installed at ${CARGO_HOME_DIR}/bin/rustup"
  sudo -u "${SERVICE_USER}" \
    RUSTUP_HOME="${RUSTUP_HOME_DIR}" \
    CARGO_HOME="${CARGO_HOME_DIR}" \
    "${CARGO_HOME_DIR}/bin/rustup" update stable
fi

# If a distro-packaged rustc/cargo is still on PATH, remove the apt
# package so rustup's shims are unambiguous. Idempotent (returns 0
# even if not installed).
apt-get remove --purge -y rustc cargo 2>/dev/null || true

# ── 4. gh CLI (used by some clone paths; cktest-runner currently goes
#    through anonymous HTTPS but having gh available is cheap insurance)
if ! command -v gh >/dev/null 2>&1; then
  echo "==> installing gh CLI"
  install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | tee /usr/share/keyrings/githubcli-archive-keyring.gpg > /dev/null
  chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list
  apt-get update
  apt-get install -y gh
else
  echo "==> gh $(gh --version | head -1) already installed, skipping"
fi

# ── 5. Repo clone (idempotent — only clones if not present)
if [[ ! -d "${REPO_DIR}/.git" ]]; then
  echo "==> cloning tenhands into ${REPO_DIR}"
  install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0755 "${REPO_DIR}"
  sudo -u "${SERVICE_USER}" git clone --depth 50 \
    https://github.com/WolffM/tenhands.git "${REPO_DIR}"
else
  echo "==> ${REPO_DIR} already a git checkout, skipping clone"
fi

# Ensure the working tree is owned by the service user so `git pull`
# from the post-deploy hook (or manual ssh) works without sudo.
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${REPO_DIR}"

# ── 6. Service-key directory (operator drops the actual key file in here
#    out-of-band; we just guarantee the dir exists with the right perms)
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 /etc/cktest-runner
if [[ ! -f /etc/cktest-runner/service.key ]]; then
  echo "==> NOTE: /etc/cktest-runner/service.key missing"
  echo "    operator must populate it (mode 0600, owner cktest:cktest)"
  echo "    before \`systemctl start cktest-runner\` will succeed."
fi

# ── 7. Install the systemd unit. Symlink from the repo so a code change
#    that updates the unit file doesn't need a copy step — `systemctl
#    daemon-reload && systemctl restart` after `git pull` is enough.
UNIT_SRC="${RUNNER_DIR}/cktest-runner.service"
UNIT_DST=/etc/systemd/system/cktest-runner.service
if [[ ! -L "${UNIT_DST}" || "$(readlink -f "${UNIT_DST}")" != "${UNIT_SRC}" ]]; then
  echo "==> linking systemd unit ${UNIT_DST} → ${UNIT_SRC}"
  ln -sfn "${UNIT_SRC}" "${UNIT_DST}"
fi

chmod +x "${RUNNER_DIR}/fetch-bearer.sh"

systemctl daemon-reload

# ── 8. Disk-pressure alarm (lightweight). Phase 0.4 wants <50 GB free
#    to alarm; we wire a oneshot timer that journals when free space
#    drops. Operator can hook this into monitoring-api later.
cat > /etc/systemd/system/cktest-disk-watch.service <<'UNIT'
[Unit]
Description=cktest-runner disk-free watcher (warns <50 GB, pages <20 GB)

[Service]
Type=oneshot
ExecStart=/bin/bash -c '\
  free_gb=$(df -BG --output=avail / | tail -1 | tr -dc "0-9"); \
  if [[ $free_gb -lt 20 ]]; then \
    logger -t cktest-disk-watch -p user.crit "PAGE: only ${free_gb}G free on /"; \
  elif [[ $free_gb -lt 50 ]]; then \
    logger -t cktest-disk-watch -p user.warning "WARN: only ${free_gb}G free on /"; \
  fi'
UNIT

cat > /etc/systemd/system/cktest-disk-watch.timer <<'UNIT'
[Unit]
Description=cktest-runner disk-free watcher (every 15 min)

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable --now cktest-disk-watch.timer

echo "==> provision.sh complete."
echo "    Next steps:"
echo "      1. (Operator) drop service key at /etc/cktest-runner/service.key"
echo "         chmod 0600 /etc/cktest-runner/service.key"
echo "         chown cktest:cktest /etc/cktest-runner/service.key"
echo "      2. systemctl enable --now cktest-runner"
echo "      3. journalctl -u cktest-runner -f --since '1 min ago'"
echo "      4. From main host: curl -H \"Authorization: Bearer \$K\" http://claw-3:5500/health"
