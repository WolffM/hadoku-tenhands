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
import sys

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

    # B19: if EITHER worker exits (Worker.run() can return silently on
    # transient network issues), crash the whole process so pm2 restarts
    # us. Previously `asyncio.gather` would happily wait forever for
    # the surviving worker while activities piled up with no poller on
    # the other queue. Using FIRST_COMPLETED + raising surfaces the
    # issue fast.
    main_task = asyncio.create_task(main_worker.run(), name="main_worker")
    copilot_task = asyncio.create_task(copilot_worker.run(), name="copilot_worker")
    alive_task = asyncio.create_task(_alive_log_loop(), name="alive_log")
    done, pending = await asyncio.wait(
        [main_task, copilot_task, alive_task], return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception()
        logger.error(
            "worker %s exited (exception=%s); triggering process restart",
            task.get_name(), type(exc).__name__ if exc else "None",
        )
        if exc is not None:
            raise exc
    raise RuntimeError("a worker exited without raising — pm2 restart needed")


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
