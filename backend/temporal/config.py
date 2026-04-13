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
    (No new GitHub PAT — pipeline reuses the existing gh user token plus
    SAML_ORG_TOKEN routing in services/github_api.py. See
    docs/crimson-kitty/cross-ref-isolation.md.)

Not yet implemented. Stub for design review.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TemporalConfig:
    host: str
    namespace: str
    task_queue: str


def load_config() -> TemporalConfig:
    return TemporalConfig(
        host=os.environ.get("TEMPORAL_HOST", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "crimson-kitty"),
        task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", "crimson-kitty-tq"),
    )
