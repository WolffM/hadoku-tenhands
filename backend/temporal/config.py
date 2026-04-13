"""Temporal client configuration.

Reads from environment variables. Defaults assume a self-hosted Temporal
Cluster running on the same host as vibedispatch (Docker Compose unit, see
docs/crimson-kitty/open-questions.md Q1).

Env vars:
    TEMPORAL_HOST              — host:port of the Temporal frontend service
                                 (default: localhost:7233)
    TEMPORAL_NAMESPACE         — Temporal namespace (default: crimson-kitty)
    TEMPORAL_TASK_QUEUE        — task queue for the worker
                                 (default: crimson-kitty-tq)
    TEMPORAL_QUARANTINE_PAT    — GitHub PAT scoped to WolffM-temporal org
    TEMPORAL_JUDGE_API_KEY     — Anthropic API key for judge gates
                                 (Q5 — TBD)

Not yet implemented. Stub for design review.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TemporalConfig:
    host: str
    namespace: str
    task_queue: str
    quarantine_pat: str | None
    judge_api_key: str | None


def load_config() -> TemporalConfig:
    return TemporalConfig(
        host=os.environ.get("TEMPORAL_HOST", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "crimson-kitty"),
        task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", "crimson-kitty-tq"),
        quarantine_pat=os.environ.get("TEMPORAL_QUARANTINE_PAT"),
        judge_api_key=os.environ.get("TEMPORAL_JUDGE_API_KEY"),
    )
