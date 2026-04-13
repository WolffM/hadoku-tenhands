"""Temporal worker entry point.

This script runs as a separate pm2 service: `vibedispatch-temporal`.
It connects to the Temporal Cluster, registers all workflows and
activities, and processes tasks from the crimson-kitty task queue.

Run locally:
    python3 -m backend.temporal.worker

Run in production (pm2 managed by hadoku_site):
    pm2 start ecosystem.config.js --only vibedispatch-temporal

Not yet implemented. The actual worker spin-up depends on the Temporal
Python SDK being installed and a running Temporal Cluster, which are
Phase 1 deliverables.

Pseudocode of intended structure:

    from temporalio.client import Client
    from temporalio.worker import Worker

    from .config import load_config
    from .workflows.issue_workflow import IssueWorkflow
    from .workflows.batch_workflow import BatchWorkflow
    from .activities import all_activities  # importlib walk

    async def main():
        cfg = load_config()
        client = await Client.connect(cfg.host, namespace=cfg.namespace)
        worker = Worker(
            client,
            task_queue=cfg.task_queue,
            workflows=[IssueWorkflow, BatchWorkflow],
            activities=all_activities(),
        )
        await worker.run()
"""
