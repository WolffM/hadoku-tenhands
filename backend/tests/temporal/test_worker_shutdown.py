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


#: Gaps between a first and second stop signal, in seconds.
#:
#: The list is the point. The original test probed 0.05 only, passed locally,
#: and went red on a CI runner — because the window where a second signal could
#: still kill the process sat between asyncio closing the loop (which restores
#: the DEFAULT disposition) and the interpreter finishing teardown, so its
#: position tracks machine speed. Locally 0.005 failed on 12 of 12 runs while
#: 0 and 0.05 passed on 12 of 12; the runner's 0.05 was our 0.005.
#:
#: So a single delay cannot pin this on every machine, and picking a "safe" one
#: would be encoding the bug. These span before, during and after that window
#: on any plausible box.
_SECOND_SIGNAL_GAPS = (0.0, 0.001, 0.005, 0.02, 0.05, 0.2)


@pytest.mark.parametrize("sigs", [
    [signal.SIGINT],                   # pm2's default kill signal
    [signal.SIGTERM],                  # had no handler at all: died with -15
    [signal.SIGQUIT],                  # forwarded by the wrapper too
], ids=["SIGINT", "SIGTERM", "SIGQUIT"])
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


@pytest.mark.parametrize("gap", _SECOND_SIGNAL_GAPS)
def test_a_second_stop_signal_cannot_kill_us(gap):
    """pm2 signals the process group AND the wrapper relays, so an ordinary
    restart delivers two. The second must be a no-op whenever it lands."""
    p = _spawn()
    os.kill(p.pid, signal.SIGINT)
    time.sleep(gap)
    os.kill(p.pid, signal.SIGINT)
    try:
        out, _ = p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        raise AssertionError(f"did not exit after two SIGINTs {gap}s apart")
    # -2 is death BY SIGINT: it does not page, but it is still not a clean exit,
    # and "depends how fast your machine is" is not a contract.
    assert p.returncode == 0, f"gap={gap}s gave {p.returncode}\n{out}"
    assert "workers shut down cleanly" in out


@pytest.mark.parametrize("second", [signal.SIGTERM, signal.SIGQUIT, signal.SIGINT],
                         ids=lambda s: s.name)
def test_a_different_second_signal_is_also_a_no_op(second):
    """The handler drops ALL the shutdown signals on the first request, not just
    the one that arrived — the wrapper relays three and pm2 may send another."""
    p = _spawn()
    os.kill(p.pid, signal.SIGINT)
    time.sleep(0.005)
    os.kill(p.pid, second)
    try:
        out, _ = p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        raise AssertionError(f"did not exit after SIGINT then {second.name}")
    assert p.returncode == 0, out


def test_only_the_first_stop_signal_is_logged():
    """A burst is one shutdown, and should read as one in the log."""
    p = _spawn()
    for _ in range(8):
        os.kill(p.pid, signal.SIGINT)
        time.sleep(0.002)
    out, _ = p.communicate(timeout=10)
    assert p.returncode == 0, out
    assert out.count("shutdown requested") == 1, out


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


def test_the_clean_path_never_runs_interpreter_finalization():
    """The second production pager, and the reason it needs its own test.

    `supervise` returning does NOT mean the process is safe to finalize: the
    Temporal Client's native runtime threads are still alive, and temporalio
    1.27.2 offers no way to stop them (no `close`/`shutdown`/`stop` on Client,
    Runtime or ServiceClient — checked). Finalization then races them, and
    twice in production it lost, AFTER "workers shut down cleanly":

        2026-09-22T17:49:15Z   SIGABRT
        2026-09-25T08:00:36Z   SIGABRT  (the nightly 08:00 key rotation)

    `PyGILState_Release: thread state ... must be current when releasing`, with
    `Extension modules: google._upb._message`. SIGABRT is not in
    hadoku_site's GRACEFUL_SIGNALS, so the page outlived the exit-code fix.

    This test does not need Temporal: it pins the MECHANISM, that a clean
    shutdown leaves via `os._exit` rather than by returning through the
    interpreter. A sentinel `atexit` handler is the probe — `os._exit` skips
    atexit by definition, so the handler running at all means finalization ran,
    which is the unsafe path. (The abort itself is timing-dependent, so
    asserting on its absence would be a flaky test for a real bug; asserting on
    the mechanism is deterministic.)
    """
    child = _CHILD.replace(
        'print("READY", flush=True)',
        'import atexit\n'
        '    atexit.register(lambda: print("FINALIZED", flush=True))\n'
        '    print("READY", flush=True)')
    p = subprocess.Popen(
        [sys.executable, "-c", child.format(backend=str(BACKEND))],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    deadline = time.time() + 10
    while time.time() < deadline:
        if (p.stdout.readline() or "").strip() == "READY":
            break
    os.kill(p.pid, signal.SIGINT)
    out, _ = p.communicate(timeout=10)
    assert p.returncode == 0, out
    assert "workers shut down cleanly" in out, out
    assert "FINALIZED" not in out, (
        "the clean path ran interpreter finalization, which races Temporal's "
        "native threads and aborted production twice\n" + out)


def test_the_log_survives_the_hard_exit():
    """`os._exit` skips the flushing that `atexit` would normally do, and the
    shutdown line is the evidence the wrapper and the operator read. Trading a
    spurious page for a silent restart would be the worse bug."""
    p = _spawn()
    os.kill(p.pid, signal.SIGINT)
    out, _ = p.communicate(timeout=10)
    assert "SIGINT received — shutdown requested" in out, out
    assert "workers shut down cleanly" in out, out


def test_a_crash_still_returns_through_main_with_its_traceback():
    """`os._exit` is ONLY for the clean path. A crash keeps normal handling —
    exit code, traceback, finalization — because there the diagnosis matters
    more than the manner of leaving."""
    child = _CHILD.replace(
        "async def run(self): await self._stop.wait()",
        "async def run(self): raise RuntimeError('boom-in-a-worker')")
    r = subprocess.run([sys.executable, "-c", child.format(backend=str(BACKEND))],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 1
    assert "boom-in-a-worker" in r.stdout + r.stderr
    assert "Traceback" in r.stdout + r.stderr


#: A child running the REAL `run_worker`, with only the Temporal client
#: replaced by something slow. That keeps the ordering under test — handlers
#: before the connect — while needing no cluster.
_SLOW_CONNECT_CHILD = textwrap.dedent("""
    import asyncio, sys
    sys.path.insert(0, {backend!r})
    from temporal import worker as w

    class SlowClient:
        @staticmethod
        async def connect(*a, **k):
            print("CONNECTING", flush=True)
            await asyncio.sleep(30)          # the window we used to lose in
            print("CONNECTED", flush=True)
            return object()

    w.Client = SlowClient
    w.load_config = lambda: type("C", (), dict(
        host="127.0.0.1:7233", namespace="ns", task_queue="tq",
        copilot_task_queue="ctq", copilot_concurrency=2))()
    sys.exit(w.main())
""")


def test_a_signal_during_startup_is_handled_not_dropped():
    """The third bug, and it predates both of the others.

    `Client.connect` takes ~1.4s against a healthy local cluster, and the
    handlers used to go on AFTER it. A stop signal in that window reached no
    handler of ours and no clean KeyboardInterrupt path either, and the process
    WEDGED — measured at 2 of 10 runs on the old code and 3 of 10 on the
    exit-code fix, each sitting 45s with nothing logged until killed. 12 of 12
    clean once the handlers moved to the top of `run_worker`.

    pm2 reaches this window whenever it restarts a worker that only just
    started — a deploy on the heels of a crash-restart, two deploys in quick
    succession — and escalates to SIGKILL after `kill_timeout`, which is not in
    GRACEFUL_SIGNALS and therefore pages.
    """
    p = subprocess.Popen(
        [sys.executable, "-c", _SLOW_CONNECT_CHILD.format(backend=str(BACKEND))],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    deadline = time.time() + 10
    while time.time() < deadline:
        if (p.stdout.readline() or "").strip() == "CONNECTING":
            break
    else:  # pragma: no cover
        p.kill()
        raise AssertionError("child never reached the connect")
    os.kill(p.pid, signal.SIGINT)
    try:
        out, _ = p.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()
        raise AssertionError("wedged on a signal during startup")
    assert p.returncode == 0, out
    assert "shutdown requested" in out, out
    # And it must not have waited out the connect before noticing.
    assert "CONNECTED" not in out, (
        "the signal was only noticed after connecting; pm2 would have "
        "SIGKILLed us first\n" + out)


def test_every_signal_the_wrapper_forwards_is_handled():
    """`forwardSignals()` in hadoku_site's pm2/utils.mjs relays SIGINT, SIGTERM
    and SIGQUIT to the child. One we do not handle kills the process outright,
    which is what SIGTERM used to do."""
    forwarded = {signal.SIGINT, signal.SIGTERM, signal.SIGQUIT}
    assert forwarded <= set(worker_mod.SHUTDOWN_SIGNALS)
