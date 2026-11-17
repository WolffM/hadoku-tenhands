"""The server's half of the deploy handover (backend/handover.py, app.py).

hadoku_site's handover supervisor binds 127.0.0.1:5024 once and passes the
socket to each generation of `backend/app.py`, one at a time: it retires the
serving generation, waits for it to exit, then starts the next (the pipeline
loop must never run twice). The test plays that supervisor with real
processes, retiring the first generation while a request is half sent to it and
a poller is hitting the port. Nothing may be refused, and the half-sent request
must still be answered by the generation that took it.
"""

from __future__ import annotations

import http.client
import os
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


from handover import take_handover

REPO = Path(__file__).resolve().parent.parent.parent
APP = REPO / "backend" / "app.py"
# Public, and answered from memory: /health asks gh who it is.
PATH = "/tenhands/automation/presets"


class Generation:
    def __init__(self, sock: socket.socket, log: Path, gen: str):
        r, w = os.pipe()
        env = {k: v for k, v in os.environ.items() if not k.startswith("HADOKU_")}
        env.update(
            HADOKU_LISTEN_FD=str(sock.fileno()),
            HADOKU_READY_FD=str(w),
            PIPELINE_LOOP_ENABLED="false",
            PYTHONUNBUFFERED="1",
        )
        self.log = log
        # A file, not a pipe: a pipe nobody drains blocks the child once full.
        with open(log, "w") as out:
            self.proc = subprocess.Popen(
                [sys.executable, str(APP)],
                cwd=REPO,
                pass_fds=(sock.fileno(), w),
                stdout=out,
                stderr=subprocess.STDOUT,
                env=env,
            )
        os.close(w)
        try:
            ready = select.select([r], [], [], 60)[0] and os.read(r, 1) == b"R"
        finally:
            os.close(r)
        assert ready, f"gen {gen} never reported ready: {self.lines()}"

    def lines(self) -> list[str]:
        return self.log.read_text().splitlines()


class Poller:
    """A new connection per request, every 20 ms, recording every failure."""

    def __init__(self, port: int):
        self.port = port
        self.errors: list[str] = []
        self.count = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=30)

    def _run(self) -> None:
        while not self._stop.wait(0.02):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
            try:
                conn.request("GET", PATH)
                resp = conn.getresponse()
                resp.read()
                if resp.status == 200:
                    self.count += 1
                else:
                    self.errors.append(f"HTTP {resp.status}")
            except Exception as e:  # noqa: BLE001 — every failure is recorded and asserted on
                self.errors.append(repr(e))
            finally:
                conn.close()


def test_take_handover_pops_the_contract():
    assert take_handover({}) is None
    env = {"HADOKU_LISTEN_FD": "3", "HADOKU_READY_FD": "4", "OTHER": "x"}
    assert take_handover(env) == (3, 4)
    assert env == {"OTHER": "x"}


def test_a_sequential_swap_refuses_nothing_and_finishes_what_it_took(tmp_path):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.set_inheritable(True)
    port = sock.getsockname()[1]
    first = Generation(sock, tmp_path / "gen1.log", "1")
    second = None
    try:
        # A request gen 1 has accepted and is still reading: the request line
        # is in, the headers are not.
        half = socket.create_connection(("127.0.0.1", port))
        half.sendall(f"GET {PATH} HTTP/1.1\r\nHost: x\r\n".encode())
        time.sleep(0.3)
        with Poller(port) as poller:
            time.sleep(0.3)
            first.proc.send_signal(signal.SIGTERM)
            termed = time.monotonic()
            time.sleep(0.2)
            half.sendall(b"\r\n")
            answer = b""
            while chunk := half.recv(65536):
                answer += chunk
            half.close()
            assert first.proc.wait(timeout=40) == 0, first.lines()
            # Nothing it took was left open: the swap waits on this exit, so a
            # connection held to the drain limit would be 30 s of every caller
            # waiting.
            assert time.monotonic() - termed < 10, first.lines()
            second = Generation(sock, tmp_path / "gen2.log", "2")
            time.sleep(0.5)
        assert answer.startswith(b"HTTP/1.1 200"), answer[:200]
        assert poller.errors == [], poller.errors
        assert poller.count > 10
        assert any("serving the handed-over socket" in line for line in second.lines())
        assert any("retired in" in line for line in first.lines()), first.lines()
    finally:
        for gen in (first, second):
            if gen is not None and gen.proc.poll() is None:
                gen.proc.kill()
                gen.proc.wait()
        sock.close()
