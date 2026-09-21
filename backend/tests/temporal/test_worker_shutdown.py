"""The worker's two ways out, and telling them apart.

Every routine restart of `tenhands-temporal` — the nightly key rotation, every
deploy — used to exit 1, and the wrapper pages on any non-zero code. So each
restart read as an outage: 2026-09-07, 09, 14, 15, 19 and 21 in the execution
log, reported by the hadoku-site session that watches it.

Two things were wrong, and these tests pin both:

  - there was no shutdown path, only a crash path that shutdowns sometimes
    took, so a stop signal raced `asyncio.run`'s cleanup against Temporal's own
    cancellation and the outcome depended on timing;
  - the B19 check could not tell a worker that returned because it was ASKED to
    stop from one that died, so it raised "a worker exited without raising"
    either way.

The real worker was verified against a live Temporal server on an isolated
queue — SIGINT, a double SIGINT, SIGTERM and SIGQUIT all exit 0 in under 10ms,
where before they exited 1, hung for 30s+, died with -2 and died with -15. CI
has no Temporal server, so these drive the same `supervise` and the same signal
handling with stand-in workers, including real OS signals in a subprocess —
because signals and `asyncio.run` are exactly the part that failed.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from temporal import worker as worker_mod
from temporal.worker import supervise

BACKEND = Path(__file__).resolve().parents[2]


class FakeWorker:
    """Behaves like `temporalio.worker.Worker` where it matters here:
    `run()` blocks until `shutdown()` is called, then returns."""

    def __init__(self, *, dies_after: float | None = None,
                 raises: BaseException | None = None) -> None:
        self._stop = asyncio.Event()
        self.dies_after = dies_after
        self.raises = raises
        self.shutdown_calls = 0

    async def run(self) -> None:
        if self.dies_after is not None:
            await asyncio.sleep(self.dies_after)
            if self.raises is not None:
                raise self.raises
            return  # B19: returned on its own, nobody asked
        await self._stop.wait()

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        self._stop.set()


def _run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=5))


# ── a requested shutdown is a clean return ────────────────────────────────


def test_a_requested_shutdown_returns_rather_than_raising():
    """The page. A stop signal must leave cleanly so pm2 sees exit 0."""
    a, b = FakeWorker(), FakeWorker()

    async def go():
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(0.05, stop.set)
        await supervise({"a": a, "b": b}, stop)

    _run(go())  # returns; does not raise


def test_both_workers_are_shut_down_through_temporals_own_path():
    """`Worker.shutdown()` — the graceful path that makes `run()` return — not
    task cancellation, which is what raced Temporal's cancellation in prod."""
    a, b = FakeWorker(), FakeWorker()

    async def go():
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(0.05, stop.set)
        await supervise({"a": a, "b": b}, stop)

    _run(go())
    assert a.shutdown_calls == 1 and b.shutdown_calls == 1


def test_nothing_is_left_pending_for_asyncio_runs_cleanup():
    """"Task was destroyed but it is pending!" was the other half of the prod
    traceback. After a clean shutdown the loop must have nothing left to
    cancel."""
    leftovers = []

    async def go():
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(0.05, stop.set)
        # Bounded: a regression that ignores the stop event would otherwise
        # hang the suite forever rather than fail it — which is exactly what
        # the first check of this file against the old worker did.
        await asyncio.wait_for(
            supervise({"a": FakeWorker(), "b": FakeWorker()}, stop), timeout=5)
        me = asyncio.current_task()
        leftovers.extend(t for t in asyncio.all_tasks() if t is not me)

    asyncio.run(go())
    assert leftovers == []


def test_a_worker_raising_during_shutdown_does_not_turn_into_a_crash():
    """The process is stopping anyway. Promoting this to a non-zero exit is the
    exact page this change exists to stop."""
    class Grumpy(FakeWorker):
        async def run(self):
            await self._stop.wait()
            raise RuntimeError("complained on the way out")

    async def go():
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(0.05, stop.set)
        await supervise({"a": Grumpy(), "b": FakeWorker()}, stop)

    _run(go())


# ── B19: a worker that stops on its own still restarts the process ────────


def test_a_worker_that_returns_unasked_still_raises():
    """B19, unchanged. `Worker.run()` can return silently on transient network
    trouble, and waiting on the survivor would leave one queue unpolled."""
    async def go():
        await supervise({"a": FakeWorker(dies_after=0.02), "b": FakeWorker()},
                        asyncio.Event())

    with pytest.raises(RuntimeError, match="exited without raising"):
        _run(go())


def test_a_worker_that_dies_with_an_error_raises_that_error():
    async def go():
        await supervise({"a": FakeWorker(dies_after=0.02,
                                         raises=ConnectionError("gone")),
                         "b": FakeWorker()}, asyncio.Event())

    with pytest.raises(ConnectionError, match="gone"):
        _run(go())


def test_the_survivor_is_stopped_properly_before_raising():
    """Leaving it for `asyncio.run`'s cleanup to cancel is the race that
    produced the prod RuntimeError in the first place."""
    survivor = FakeWorker()

    async def go():
        await supervise({"a": FakeWorker(dies_after=0.02), "b": survivor},
                        asyncio.Event())

    with pytest.raises(RuntimeError):
        _run(go())
    assert survivor.shutdown_calls == 1


def test_the_old_code_could_not_tell_asked_from_died():
    """The distinction, stated directly: the same `run()` returning is a crash
    when nobody asked, and a clean exit when somebody did."""
    async def unasked():
        await supervise({"a": FakeWorker(dies_after=0.02)}, asyncio.Event())

    async def asked():
        stop = asyncio.Event()
        stop.set()
        await supervise({"a": FakeWorker(dies_after=0.02)}, stop)

    with pytest.raises(RuntimeError):
        _run(unasked())
    _run(asked())


# ── real signals, real asyncio.run, real exit codes ───────────────────────

#: A stand-in worker process: the production signal handlers and `supervise`,
#: the production `main()` exit-code mapping, and fake workers instead of a
#: Temporal client. Prints READY once the handlers are installed, so the test
#: signals a process that is genuinely listening.
_CHILD = textwrap.dedent("""
    import asyncio, sys
    sys.path.insert(0, {backend!r})
    from temporal import worker as w

    class Fake:
        def __init__(self): self._stop = asyncio.Event()
        async def run(self): await self._stop.wait()
        async def shutdown(self): self._stop.set()

    async def run_worker():
        stop = asyncio.Event()
        w._install_shutdown_handlers(stop)
        print("READY", flush=True)
        await w.supervise({{"main_worker": Fake(), "copilot_worker": Fake()}}, stop)

    w.run_worker = run_worker
    sys.exit(w.main())
""")


def _spawn():
    # `preexec_fn` resets SIGINT to default: a process started from a
    # non-interactive shell's `&` inherits SIGINT as IGNORED, and an ignored
    # signal survives exec. pm2 spawns its children with the default
    # disposition, so that is the shape worth testing. (Found the hard way: the
    # first version of this harness sent SIGINT to a process ignoring it.)
    p = subprocess.Popen(
        [sys.executable, "-c", _CHILD.format(backend=str(BACKEND))],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    deadline = time.time() + 10
    while time.time() < deadline:
        if (p.stdout.readline() or "").strip() == "READY":
            return p
    p.kill()
    raise AssertionError("child never became ready")


@pytest.mark.parametrize("sigs", [
    [signal.SIGINT],                   # pm2's default kill signal
    [signal.SIGINT, signal.SIGINT],    # pm2 signals the group AND the wrapper forwards
    [signal.SIGTERM],                  # had no handler at all: died with -15
    [signal.SIGQUIT],                  # forwarded by the wrapper too
], ids=["SIGINT", "double-SIGINT", "SIGTERM", "SIGQUIT"])
def test_a_stop_signal_exits_zero(sigs):
    """The wrapper pages on any non-zero exit code. Death BY a graceful signal
    is also accepted there, but exiting 0 on purpose is the shape that does not
    depend on how quickly a second signal arrives."""
    p = _spawn()
    for s in sigs:
        os.kill(p.pid, s)
        time.sleep(0.05)
    try:
        out, _ = p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        raise AssertionError(f"did not exit after {[s.name for s in sigs]}")
    assert p.returncode == 0, out
    assert "workers shut down cleanly" in out
    assert "Event loop stopped" not in out
    assert "Task was destroyed" not in out


def test_a_worker_dying_on_its_own_still_exits_non_zero():
    """B19 end to end: without a signal, a worker stopping is a crash and pm2
    must restart us. Exit 1 here is correct, and is the one case that should
    still page."""
    child = _CHILD.replace(
        "async def run(self): await self._stop.wait()",
        "async def run(self): await asyncio.sleep(0.1)")
    p = subprocess.run([sys.executable, "-c", child.format(backend=str(BACKEND))],
                       capture_output=True, text=True, timeout=10)
    assert p.returncode == 1
    assert "exited without raising" in p.stdout + p.stderr


def test_every_signal_the_wrapper_forwards_is_handled():
    """`forwardSignals()` in hadoku_site's pm2/utils.mjs relays SIGINT, SIGTERM
    and SIGQUIT to the child. One we do not handle kills the process outright,
    which is what SIGTERM used to do."""
    forwarded = {signal.SIGINT, signal.SIGTERM, signal.SIGQUIT}
    assert forwarded <= set(worker_mod.SHUTDOWN_SIGNALS)
