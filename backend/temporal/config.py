"""Temporal client configuration.

Reads from environment variables. Defaults assume a self-hosted Temporal
Cluster running on the same host as vibedispatch (Docker Compose unit, see
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

Auth: the pipeline reuses the existing `gh` user token plus `SAML_ORG_TOKEN`
routing in `services/github_api.py` for GitHub side. The judge (`judge.py`)
reads `CLAUDE_CODE_OAUTH_TOKEN` from the environment at subprocess-spawn
time. See `validate_judge_credentials()` below for the precondition check.

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
    """Precondition check: the judge needs CLAUDE_CODE_OAUTH_TOKEN set.

    Called by `judge.py` at module import or first-call time. Raises
    `MissingConfigError` with a remediation hint if the token is unset.
    """
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
        raise MissingConfigError(
            "CLAUDE_CODE_OAUTH_TOKEN is not set. Generate one with "
            "`claude setup-token` (1-year OAuth token) and add it to .env. "
            "See docs/crimson-kitty/phase-1-plan.md step 0.10."
        )
