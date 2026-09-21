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
    cfg = load_config()
    logger.info(
        "connecting to temporal: host=%s namespace=%s main=%s copilot=%s(cap=%d)",
        cfg.host, cfg.namespace, cfg.task_queue,
        cfg.copilot_task_queue, cfg.copilot_concurrency,
    )

    client = await Client.connect(cfg.host, namespace=cfg.namespace)

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

    shutdown = asyncio.Event()
    _install_shutdown_handlers(shutdown)
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
    if not shutdown.is_set():
        logger.info("%s received — shutdown requested", signal.Signals(sig).name)
    shutdown.set()


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
