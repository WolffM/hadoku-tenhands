"""Deploy handover: this server's half of hadoku_site's socket mover.

In production the PM2 wrapper runs `backend/app.py` under the handover
supervisor (hadoku_site `services/pm2/lib/handover.py`), which binds
127.0.0.1:5024 ONCE and keeps it open across deploys. A connection made while
no generation is accepting waits in the socket's backlog instead of being
refused, so a deploy is a slow answer for a second or two, never a 502.

The contract, all of it here:

- ``HADOKU_LISTEN_FD``: serve this inherited listening socket; never bind one.
- ``HADOKU_READY_FD``: write one byte once accepting, then close it.
- SIGTERM: stop accepting, finish what is in flight, exit.

The supervisor runs tenhands WITHOUT overlap: it retires the serving
generation, waits for it to exit, and only then starts the next. The pipeline
loop (services/pipeline_loop.py) advances assignments from a thread with no
lock between processes, so two generations must never both run it.

Without the variables (``python app.py`` by hand, the debug reloader) app.py
runs Flask's own server exactly as before.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time

from werkzeug.serving import ThreadedWSGIServer

logger = logging.getLogger("tenhands.handover")

# How long a retiring generation lets the requests it took finish. GitHub
# calls behind a route are the slowest thing it answers.
DRAIN_MAX_SECS = 30.0


class HandoverServer(ThreadedWSGIServer):
    """Counts the requests in flight, so a retiring generation can wait for them.

    A connection is one request: werkzeug answers every response with
    ``Connection: close``, so no idle keep-alive connection (cloudflared keeps
    its own open) can hold a retiring generation to the drain limit.
    """

    # Connections wait here while generations swap; werkzeug's default is 128
    # already, stated so a change upstream cannot shrink it under us.
    request_queue_size = 128

    def __init__(self, *args, **kw) -> None:
        self._busy = 0
        self._busy_cv = threading.Condition()
        super().__init__(*args, **kw)

    def process_request_thread(self, request, client_address) -> None:
        with self._busy_cv:
            self._busy += 1
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._busy_cv:
                self._busy -= 1
                self._busy_cv.notify_all()

    def wait_idle(self, timeout: float) -> int:
        """Block until nothing is in flight or `timeout` passes; how many are left."""
        deadline = time.monotonic() + timeout
        with self._busy_cv:
            while self._busy:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._busy_cv.wait(left)
            return self._busy


def take_handover(env=os.environ) -> tuple[int, int | None] | None:
    """(listen fd, ready fd) when started by the supervisor, else None.

    Popped from `env`: the descriptors are this process's alone, and a
    subprocess tenhands starts (gh, git, an agent) must not inherit the claim.
    """
    listen = env.pop("HADOKU_LISTEN_FD", None)
    ready = env.pop("HADOKU_READY_FD", None)
    if not listen:
        return None
    return int(listen), int(ready) if ready else None


def serve_handed_over(app, listen_fd: int, ready_fd: int | None, on_retire=None) -> None:
    """Serve the inherited socket until SIGTERM, then retire: stop accepting,
    close this copy of the socket (the supervisor's stays open), finish what is
    in flight, and run `on_retire` (stopping background work) before returning."""
    server = HandoverServer("127.0.0.1", 0, app, fd=listen_fd)
    # werkzeug serves a dup of the descriptor; the original is not needed.
    os.close(listen_fd)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    accepting = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
    )
    accepting.start()
    if ready_fd is not None:
        os.write(ready_fd, b"R")
        os.close(ready_fd)
    logger.info("serving the handed-over socket (pid %d)", os.getpid())
    while not stop.wait(1.0):
        pass
    t0 = time.monotonic()
    server.shutdown()  # serve_forever's finally closes this copy of the socket
    accepting.join()
    left = server.wait_idle(DRAIN_MAX_SECS)
    if on_retire is not None:
        on_retire()
    logger.info(
        "retired in %.1fs%s",
        time.monotonic() - t0,
        f", cutting {left} request(s) still running" if left else "",
    )
