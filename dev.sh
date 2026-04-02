#!/usr/bin/env bash
# dev.sh — kill stale processes, then launch backend + frontend in separate Windows Terminal tabs
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
WIN_REPO=$(wslpath -w "$REPO_DIR")

# Kill anything on port 5024 (backend) and 5184 (frontend)
for port in 5024 5184; do
  pid=$(lsof -ti tcp:$port 2>/dev/null || true)
  if [ -n "$pid" ]; then
    echo "Killing PID $pid on port $port"
    kill -9 $pid 2>/dev/null || true
  fi
done

sleep 0.5

WT=/mnt/c/Users/Hadoku/AppData/Local/Microsoft/WindowsApps/wt.exe

"$WT" \
  new-tab --title "backend" --startingDirectory "$WIN_REPO\\backend" -- wsl.exe -e bash -l -c "python3 app.py" \; \
  new-tab --title "frontend" --startingDirectory "$WIN_REPO\\frontend" -- wsl.exe -e bash -l -c "npm run dev -- --host"
