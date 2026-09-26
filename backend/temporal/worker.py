"""Temporal worker entry point — Phase 1D.3.

Starts two workers in one process:

- **Main worker** polls `crimson-kitty-tq`. It owns the workflow
  definitions (IssueWorkflow, BatchWorkflow) and every non-Copilot
  activity (eligibility, fork, env, gates, review, submission, etc.).
  Unbounded concurrency — these activities are cheap.

- **Copilot worker** polls `crimson-kitty-copilot-tq` with
  `max_concurrent_activities=2`. It only handles the Copilot-bound
  activities (request_repro/fix/verify/remediation). The 2-slot cap
  mirrors the Copilot coding-agent per-user concurrent-session limit.

Why two queues, not a batch-level semaphore? An IssueWorkflow that
defers to human review sits in `workflow.wait_condition` — if we gated
at the batch level, that sitting child would hold a slot indefinitely
and starve the queued work. Task-queue concurrency is per-activity:
the deferred child isn't running any Copilot activity, so it holds
nothing.

Run as `python -m temporal.worker` from the backend directory. Pm2
manages this as `tenhands-temporal` on prod.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Mapping, Protocol

from temporalio.client import Client
from temporalio.worker import Worker

from .config import load_config
from .temporal_activities import COPILOT_ACTIVITIES, MAIN_ACTIVITIES
from .workflows import BatchWorkflow, IssueWorkflow

logger = logging.getLogger("crimson-kitty.worker")


async def run_worker() -> None:
    # Handlers FIRST, before anything that can block. `Client.connect` takes
    # ~1.4s against a healthy local cluster, and until 2026-09-26 the handlers
    # went on after it — so a stop signal arriving in that window hit no
    # handler of ours and no clean KeyboardInterrupt path either, and WEDGED
    # the process: 2 of 10 runs on the old code and 3 of 10 on the exit-code
    # fix sat for 45s with nothing logged until the harness killed them.
    #
    # pm2 hits this window whenever it restarts a worker that has only just
    # started — a deploy landing on the heels of a crash-restart, or two
    # deploys in quick succession — and after `kill_timeout` it escalates to
    # SIGKILL, which is not in GRACEFUL_SIGNALS and therefore pages.
    #
    # Nothing here needs the config or the client, so there is no reason for it
    # to have been later.
    shutdown = asyncio.Event()
    _install_shutdown_handlers(shutdown)

    cfg = load_config()
    logger.info(
        "connecting to temporal: host=%s namespace=%s main=%s copilot=%s(cap=%d)",
        cfg.host, cfg.namespace, cfg.task_queue,
        cfg.copilot_task_queue, cfg.copilot_concurrency,
    )

    # Race the connect against the shutdown, rather than connecting and then
    # asking whether we should have. Checking afterwards is not enough: the
    # Event is set the moment the signal lands, but nothing is awaiting it while
    # we sit inside `connect`, so we would still wait the connect out — ~1.4s
    # against a healthy local cluster, and unbounded against a sick one, while
    # pm2 escalates to SIGKILL after `kill_timeout`. A test with a deliberately
    # slow connect wedged on exactly that.
    connecting = asyncio.create_task(Client.connect(cfg.host,
                                                    namespace=cfg.namespace),
                                     name="connect")
    stopping = asyncio.create_task(shutdown.wait(), name="shutdown_requested")
    await asyncio.wait([connecting, stopping],
                       return_when=asyncio.FIRST_COMPLETED)
    if shutdown.is_set():
        # Cancelling a half-built client would matter if we carried on; we do
        # not. `_exit_without_finalizing` is about to take the process down, so
        # the only thing that matters is not blocking on the way there.
        connecting.cancel()
        await asyncio.gather(connecting, return_exceptions=True)
        logger.info("shutdown requested during startup — stopping before the "
                    "workers were registered")
        return
    await _cancel(stopping)
    client = connecting.result()

    main_worker = Worker(
        client,
        task_queue=cfg.task_queue,
        workflows=[IssueWorkflow, BatchWorkflow],
        activities=MAIN_ACTIVITIES,
    )

    copilot_worker = Worker(
        client,
        task_queue=cfg.copilot_task_queue,
        activities=COPILOT_ACTIVITIES,
        max_concurrent_activities=cfg.copilot_concurrency,
    )

    logger.info(
        "workers registered: main=%s (%d activities), copilot=%s (%d activities, cap=%d)",
        cfg.task_queue, len(MAIN_ACTIVITIES),
        cfg.copilot_task_queue, len(COPILOT_ACTIVITIES), cfg.copilot_concurrency,
    )

    if shutdown.is_set():
        logger.info("shutdown requested during startup — stopping before the "
                    "workers were started")
        return

    await supervise(
        {"main_worker": main_worker, "copilot_worker": copilot_worker},
        shutdown,
    )


class _Runnable(Protocol):
    async def run(self) -> None: ...
    async def shutdown(self) -> None: ...


#: The signals that mean "please stop" rather than "you are broken".
#: SIGINT is pm2's default kill signal; SIGTERM is what systemd, docker and a
#: plain `kill` send; the wrapper's `forwardSignals` relays all three below.
SHUTDOWN_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGQUIT)


def _install_shutdown_handlers(shutdown: asyncio.Event) -> None:
    """Turn a stop signal into an Event this process handles on purpose.

    **Why the default is not good enough.** Without this, a stop signal goes
    through `asyncio.run`'s generic machinery: its SIGINT handler cancels the
    main task, then its cleanup cancels every remaining task and spins the loop
    until they finish — racing Temporal's own cancellation of each worker. The
    outcome depended on timing, and all three outcomes were observed:

      prod, 2026-09-21 08:00Z   both workers logged "cancelled", and 4ms later
                                `RuntimeError: Event loop stopped before Future
                                completed` escaped `asyncio.run` → exit 1
      one SIGINT, locally       hung for 30s+ inside the cleanup
      two SIGINTs, locally      died BY the signal (-2)

    Only the first pages, but all three are the same bug: there was no
    shutdown path, only a crash path that shutdowns sometimes took. And SIGTERM
    had no handler at all, so it killed the process outright.

    `loop.add_signal_handler` replaces the disposition for this loop, so the
    signal never reaches `asyncio.run`'s handler or Python's
    `KeyboardInterrupt`. Repeat signals are harmless: setting a set Event is a
    no-op, which is what makes the double SIGINT a wrapper and pm2 can deliver
    between them a non-event.
    """
    loop = asyncio.get_running_loop()
    for sig in SHUTDOWN_SIGNALS:
        loop.add_signal_handler(sig, _request_shutdown, sig, shutdown)


def _request_shutdown(sig: signal.Signals, shutdown: asyncio.Event) -> None:
    """Record the request, then make every later stop signal a no-op.

    **A second stop signal is normal here, not an escalation.** pm2 signals the
    process group and the wrapper's `forwardSignals` relays to the child, so
    the ordinary restart delivers two. Left alone the second one can still kill
    us: once `supervise` returns, `asyncio.run` closes the loop, which resets
    these signals to their DEFAULT disposition, and the process then spends a
    few more milliseconds tearing down the interpreter. A signal landing in
    that window terminates it — measured as exit -2 on 100% of runs with the
    two signals 5ms apart locally, and 0% at 0ms or 50ms. The window is real
    and its width tracks machine speed, which is why it showed up on a CI
    runner at the 50ms the local box was fine with.

    `-2` does not page — hadoku_site's `GRACEFUL_SIGNALS` counts death by
    SIGINT as a clean stop — so this is about the contract rather than the
    alert: a stop signal must never produce a non-zero exit, and "it depends
    how fast your machine is" is not a contract.

    So: block first (one atomic syscall, so nothing is delivered while the
    disposition is being changed), then drop asyncio's handler and install
    SIG_IGN, which survives loop.close() precisely because asyncio no longer
    knows about these signals. Blocking alone would not do — it is per-thread,
    and temporalio's runtime threads were created before this point, so a
    signal could still be accepted there. SIG_IGN is process-wide and is the
    part that actually protects us.

    **SIGKILL remains the escape hatch**, unblockable by design, and it is what
    pm2 sends after `kill_timeout`. What this gives up is a second Ctrl-C
    force-quitting a hand-run worker; that is worth one process-wide guarantee
    about exit codes.
    """
    if shutdown.is_set():
        return
    logger.info("%s received — shutdown requested", signal.Signals(sig).name)
    shutdown.set()
    signal.pthread_sigmask(signal.SIG_BLOCK, set(SHUTDOWN_SIGNALS))
    loop = asyncio.get_running_loop()
    for other in SHUTDOWN_SIGNALS:
        try:
            loop.remove_signal_handler(other)
        except (ValueError, RuntimeError):  # never registered, or loop closing
            pass
        signal.signal(other, signal.SIG_IGN)


async def supervise(workers: Mapping[str, _Runnable],
                    shutdown: asyncio.Event) -> None:
    """Run every worker until one stops or a shutdown is requested.

    Two ways out, and telling them apart is the whole job:

    - **A shutdown was requested.** Each worker is shut down through Temporal's
      own graceful path (`Worker.shutdown()`, which makes `run()` return), and
      this RETURNS. That is a clean exit, and pm2 must see it as one — the
      wrapper pages on any non-zero code, and this used to leave with 1 on every
      routine restart: nightly key rotation, every deploy.

    - **A worker stopped on its own (B19).** `Worker.run()` can return silently
      on transient network trouble. `asyncio.gather` would then wait forever on
      the survivor while activities piled up with no poller on the other queue,
      so this RAISES and pm2 restarts the process. That behaviour is unchanged.

    The old version could not tell these apart: a worker that returned because
    it was ASKED to shut down looked exactly like one that died, so it raised
    `"a worker exited without raising"` either way. Checking the Event first is
    the fix. A signal that lands at the same moment a worker dies is treated as
    a shutdown, which is right — pm2 is about to restart us regardless.
    """
    tasks = {asyncio.create_task(w.run(), name=name): w
             for name, w in workers.items()}
    alive = asyncio.create_task(_alive_log_loop(), name="alive_log")
    stop = asyncio.create_task(shutdown.wait(), name="shutdown_requested")

    await asyncio.wait([*tasks, alive, stop],
                       return_when=asyncio.FIRST_COMPLETED)

    if shutdown.is_set():
        # Graceful: tell every worker, then wait for each `run()` to return.
        # Temporal's shutdown is idempotent, so a worker that already stopped
        # is fine to ask again.
        await asyncio.gather(*(w.shutdown() for w in tasks.values()),
                             return_exceptions=True)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        await _cancel(alive)
        for task, result in zip(tasks, results):
            if isinstance(result, BaseException) and not isinstance(
                    result, asyncio.CancelledError):
                # Worth a line, not a crash: the process is stopping anyway,
                # and turning this into a non-zero exit is the page this whole
                # change exists to stop.
                logger.warning("worker %s raised while shutting down: %r",
                               task.get_name(), result)
        logger.info("workers shut down cleanly")
        return

    # B19: something stopped without being asked.
    await _cancel(stop)
    finished = [t for t in tasks if t.done()]
    for task in finished:
        exc = task.exception()
        logger.error(
            "worker %s exited (exception=%s); triggering process restart",
            task.get_name(), type(exc).__name__ if exc else "None",
        )
    # Stop the survivors properly before raising, rather than leaving them for
    # `asyncio.run`'s cleanup to cancel — that cleanup racing Temporal's
    # cancellation is exactly what produced the RuntimeError above.
    await asyncio.gather(*(w.shutdown() for t, w in tasks.items()
                           if not t.done()), return_exceptions=True)
    await asyncio.gather(*tasks, return_exceptions=True)
    await _cancel(alive)
    for task in finished:
        exc = task.exception()
        if exc is not None:
            raise exc
    if alive.done() and not alive.cancelled() and alive.exception():
        raise alive.exception()
    raise RuntimeError("a worker exited without raising — pm2 restart needed")


async def _cancel(task: asyncio.Task) -> None:
    """Cancel a helper task and wait for it, so nothing is left pending for
    `asyncio.run`'s cleanup to find — "Task was destroyed but it is pending!"
    was the other half of the prod traceback."""
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _alive_log_loop() -> None:
    """Periodic heartbeat from the worker process itself, independent of
    activity-level heartbeats. Helps distinguish "worker dead/restarting"
    from "worker alive but activity stuck" — when investigating a timed-
    out activity, the absence/presence of this log around the failure
    time tells you which side broke."""
    started_at = asyncio.get_event_loop().time()
    while True:
        await asyncio.sleep(60)
        uptime_s = asyncio.get_event_loop().time() - started_at
        logger.info("worker alive: uptime_s=%.0f", uptime_s)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("worker interrupted")
        return 0
    except Exception as e:
        logger.exception("worker crashed: %s", e)
        return 1
    _exit_without_finalizing()
    return 0  # pragma: no cover — _exit_without_finalizing does not return


def _exit_without_finalizing() -> None:
    """Leave a CLEAN shutdown without running interpreter finalization.

    A blunt instrument, and the alternative is worse. After `supervise` returns,
    the two Temporal workers are stopped but the **Client's native runtime
    threads are still alive** — the Rust core and its gRPC stack — and
    temporalio exposes nothing to stop them: `Client`, `Runtime` and
    `ServiceClient` have no `close`, `shutdown` or `stop` of any kind in 1.27.2
    (checked, not assumed). They live until the process does.

    So finalization races them, and sometimes loses. Twice in production after
    the exit-code fix landed, both times AFTER "workers shut down cleanly":

        2026-09-22T17:49:15Z   SIGABRT
        2026-09-25T08:00:36Z   SIGABRT   (the nightly 08:00 key rotation)

        Fatal Python error: PyGILState_Release: thread state ... must be
        current when releasing
        Python runtime state: finalizing
        Extension modules: google._upb._message

    A native thread reached for the GIL while the interpreter was tearing down,
    and Python aborted. `SIGABRT` is not in hadoku_site's `GRACEFUL_SIGNALS`,
    so the page survived the fix that was supposed to stop it — the exit code
    was right and the process still died wrong.

    `os._exit` skips finalization entirely, which is exactly the part that is
    not safe here. It also skips `atexit` and buffered-output flushing, so both
    are done by hand first — the "workers shut down cleanly" line is the
    evidence the wrapper and the operator read, and losing it would trade a
    spurious page for a silent restart, which is worse.

    Deliberately ONLY on the clean path. A crash still returns through `main`
    with its traceback, its exit code and normal finalization, because there
    the diagnosis matters more than the manner of leaving.
    """
    logging.shutdown()  # flush and close every handler, atexit's job
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # pragma: no cover — a closed stream must not abort us
            pass
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
