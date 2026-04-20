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
manages this as `vibedispatch-temporal` on prod.
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
    await asyncio.gather(main_worker.run(), copilot_worker.run())


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
