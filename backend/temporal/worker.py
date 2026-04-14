"""Temporal worker entry point — Phase 1D.3.

Connects to the configured Temporal cluster, registers IssueWorkflow +
BatchWorkflow + every activity, and starts polling the task queue.

Run as `python -m temporal.worker` from the backend directory. Pm2
manages this as `vibedispatch-temporal` on prod (entry deferred to
Phase 1D in ecosystem.config.cjs).
"""

from __future__ import annotations

import asyncio
import logging
import sys

from temporalio.client import Client
from temporalio.worker import Worker

from .config import load_config
from .temporal_activities import ALL_ACTIVITIES
from .workflows import BatchWorkflow, IssueWorkflow

logger = logging.getLogger("crimson-kitty.worker")


async def run_worker() -> None:
    cfg = load_config()
    logger.info(
        "connecting to temporal: host=%s namespace=%s queue=%s",
        cfg.host, cfg.namespace, cfg.task_queue,
    )

    client = await Client.connect(cfg.host, namespace=cfg.namespace)

    worker = Worker(
        client,
        task_queue=cfg.task_queue,
        workflows=[IssueWorkflow, BatchWorkflow],
        activities=ALL_ACTIVITIES,
    )

    logger.info(
        "worker registered: %d workflows, %d activities — polling %s",
        2, len(ALL_ACTIVITIES), cfg.task_queue,
    )
    await worker.run()


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
