"""Temporal client configuration.

Reads from environment variables. Defaults assume a self-hosted Temporal
Cluster running on the same host as tenhands (Docker Compose unit, see
docs/crimson-kitty/architecture.md and the Phase 1A.2 step in
docs/crimson-kitty/phase-1-plan.md).

Env vars:
    TEMPORAL_HOST              host:port of the Temporal frontend service
                               (default: localhost:7233)
    TEMPORAL_NAMESPACE         Temporal namespace
                               (default: crimson-kitty)
    TEMPORAL_TASK_QUEUE        task queue name for the main worker
                               (default: crimson-kitty-tq)
    TEMPORAL_COPILOT_QUEUE     task queue for Copilot-bound activities
                               (default: crimson-kitty-copilot-tq) —
                               capped at 2 concurrent activities so the
                               Copilot coding-agent per-user session
                               limit doesn't silently starve assignments
    TEMPORAL_COPILOT_CONCURRENCY  max concurrent activities on the
                               copilot queue (default: 2)

Auth: the pipeline reuses the existing `gh` user token plus the SAML-org
token routing in `services/github_api.py` for the GitHub side. The judge (`judge.py`)
leases a Claude OAuth token from crossposter (`claude_tokens.py`) at
subprocess-spawn time. See `validate_judge_credentials()` below for the precondition check.

See docs/crimson-kitty/cross-ref-isolation.md for the full token model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class MissingConfigError(RuntimeError):
    """Raised when a required environment variable is unset.

    Currently only `validate_judge_credentials()` raises this. The Temporal
    client config itself has no required fields — all defaults are sane for
    a same-host docker compose setup.
    """


@dataclass(frozen=True)
class TemporalConfig:
    host: str
    namespace: str
    task_queue: str
    copilot_task_queue: str
    copilot_concurrency: int


def load_config() -> TemporalConfig:
    """Load TemporalConfig from environment variables.

    All fields have safe defaults for the same-host docker compose deployment.
    """
    return TemporalConfig(
        host=os.environ.get("TEMPORAL_HOST", "localhost:7233"),
        namespace=os.environ.get("TEMPORAL_NAMESPACE", "crimson-kitty"),
        task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", "crimson-kitty-tq"),
        copilot_task_queue=os.environ.get(
            "TEMPORAL_COPILOT_QUEUE", "crimson-kitty-copilot-tq"
        ),
        copilot_concurrency=int(
            os.environ.get("TEMPORAL_COPILOT_CONCURRENCY", "2")
        ),
    )


def validate_judge_credentials() -> None:
    """Precondition check: the judge needs a way to lease a Claude token.

    tenhands holds no Claude token; it leases one from crossposter with its
    service key (see `claude_tokens.py`). Raises `MissingConfigError` with a
    remediation hint when the key is not set.
    """
    if not (os.environ.get("HADOKU_SERVICE_KEY") or "").strip():
        raise MissingConfigError(
            "HADOKU_SERVICE_KEY is not set, so no Claude token can be leased from "
            "crossposter. It is tenhands' service key, vault item KEY_SERVICE_TENHANDS."
        )
