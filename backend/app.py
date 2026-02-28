"""
VibeDispatch - API Backend for GitHub Repository Management

This Flask app serves as the API backend for the VibeDispatch React frontend.
All page rendering has been moved to the React microfrontend.
"""

import os
import signal
import socket
import subprocess
import sys
import time

from flask import Flask, request, jsonify


def _port_in_use(port: int) -> bool:
    """Check if a port is currently in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _kill_port(port: int) -> None:
    """Kill any process currently listening on the given port (Windows + Unix).

    Uses os.kill() first (works for same-user processes without elevation),
    then falls back to taskkill/kill -9.  Retries up to 3 times.
    Raises SystemExit if the port cannot be freed.
    """
    if not _port_in_use(port):
        return  # port is free

    print(f"[startup] Port {port} is in use — killing existing process...")

    def _kill_once_win() -> int:
        killed = set()
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL,
            )
            for line in out.splitlines():
                if f":{port} " in line and "LISTENING" in line.upper():
                    parts = line.split()
                    pid_str = parts[-1] if parts else ""
                    if not pid_str or not pid_str.isdigit() or pid_str in killed:
                        continue
                    pid_num = int(pid_str)
                    # Try os.kill first (same-user, no elevation needed)
                    try:
                        os.kill(pid_num, signal.SIGTERM)
                        print(f"[startup] Killed PID {pid_str} via SIGTERM")
                        killed.add(pid_str)
                        continue
                    except (PermissionError, OSError):
                        pass
                    # Fall back to taskkill
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", pid_str],
                            capture_output=True, text=True, check=True,
                        )
                        print(f"[startup] Killed PID {pid_str} via taskkill")
                        killed.add(pid_str)
                    except (subprocess.CalledProcessError, OSError) as e:
                        stderr = getattr(e, "stderr", "") or ""
                        print(f"[startup] WARNING: Failed to kill PID {pid_str}: {stderr.strip()}")
        except subprocess.CalledProcessError:
            pass
        return len(killed)

    def _kill_once_unix() -> int:
        count = 0
        try:
            out = subprocess.check_output(
                ["lsof", "-ti", f":{port}"], text=True, stderr=subprocess.DEVNULL,
            )
            for pid_str in out.strip().splitlines():
                pid_str = pid_str.strip()
                if not pid_str or not pid_str.isdigit():
                    continue
                try:
                    os.kill(int(pid_str), signal.SIGKILL)
                    print(f"[startup] Killed PID {pid_str}")
                    count += 1
                except (PermissionError, ProcessLookupError):
                    pass
        except subprocess.CalledProcessError:
            pass
        return count

    kill_fn = _kill_once_win if sys.platform == "win32" else _kill_once_unix

    for attempt in range(3):
        kill_fn()
        time.sleep(0.5)
        if not _port_in_use(port):
            if attempt > 0:
                print(f"[startup] Port {port} cleared after {attempt + 1} passes")
            return
        print(f"[startup] Port {port} still busy, retrying ({attempt + 1}/3)...")

    # All attempts failed
    print(f"\n[startup] ERROR: Port {port} is STILL in use after 3 kill attempts.")
    print(f"[startup] Another process owns it and cannot be killed (access denied?).")
    print(f"[startup] Fix: close the other terminal running the backend, or run:")
    if sys.platform == "win32":
        print(f"[startup]   taskkill /F /PID <pid>  (as Administrator)")
    else:
        print(f"[startup]   sudo kill -9 <pid>")
    print(f"[startup] Or use a different port:  PORT=5001 python app.py")
    sys.exit(1)

# Import the blueprint with all routes registered
try:
    from .routes import bp
except ImportError:
    from routes import bp

# URL prefix for deployment behind edge-router at hadoku.me/dispatch/*
# Set URL_PREFIX="" for local development without prefix
URL_PREFIX = os.environ.get("URL_PREFIX", "/dispatch")

app = Flask(__name__)


# ============ CORS Support ============
@app.after_request
def add_cors_headers(response):
    """Add CORS headers for development with React frontend."""
    # In production, the React app is served from the same origin
    # In development, React runs on localhost:5173
    origin = request.headers.get('Origin', '')
    if origin in ['http://localhost:5175', 'http://127.0.0.1:5175', 'http://localhost:5173', 'http://localhost:5174', 'http://localhost:5176', 'http://127.0.0.1:5176']:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-User-Key'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response


@app.route('/')
def api_root():
    """API info endpoint."""
    return jsonify({"message": "VibeDispatch API", "docs": "/api/"})


# Register blueprint with URL prefix
app.register_blueprint(bp, url_prefix=URL_PREFIX)


if __name__ == "__main__":
    # Use environment variable to control debug mode (defaults to False for security)
    # Set FLASK_ENV=development to enable debug mode in local development
    debug_mode = os.environ.get("FLASK_ENV") == "development"
    port = int(os.environ.get("PORT", 5000))
    _kill_port(port)
    app.run(debug=debug_mode, port=port)
