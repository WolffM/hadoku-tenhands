"""Gate registry — Phase 1C.

Gates are pure functions over the evidence store that decide pass / fail /
defer. They are the SINGLE place where validation logic lives. Replaces the
scattered `_sanitize_upstream_refs`, `is_bot`, dedup-guard, and ad-hoc `if`
checks from the legacy pipeline.

Each gate is registered with the state it runs after. The orchestrator
(IssueWorkflow) calls `run_gates(state, evidence)` after every state
transition.

See docs/crimson-kitty/gates.md for the full registry and the
bug→gate mapping from the jade-hare retro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

# ── Types ─────────────────────────────────────────────────────────────────

GateKind = Literal["mechanical", "judge", "human"]
Verdict = Literal["pass", "fail", "defer"]


@dataclass(frozen=True)
class GateResult:
    name: str
    verdict: Verdict
    reason: str = ""
    evidence_data: dict | None = None
    score: float | None = None
    kind: GateKind = "mechanical"

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"

    @property
    def failed(self) -> bool:
        return self.verdict == "fail"

    @property
    def deferred(self) -> bool:
        return self.verdict == "defer"


@dataclass(frozen=True)
class IssueRef:
    """Minimal issue handle passed to gates. Mirrors the AgentRef shape from
    temporal.agents but kept separate so gates don't depend on agents."""

    fork_slug: str
    upstream_slug: str
    upstream_number: int


# ── Helper constructors (gates use these to return verdicts) ──────────────


def Pass(reason: str = "", **kwargs: Any) -> GateResult:
    return GateResult(name="", verdict="pass", reason=reason, **kwargs)


def Fail(reason: str, **kwargs: Any) -> GateResult:
    return GateResult(name="", verdict="fail", reason=reason, **kwargs)


def Defer(reason: str, **kwargs: Any) -> GateResult:
    return GateResult(name="", verdict="defer", reason=reason, **kwargs)


# ── Registry ──────────────────────────────────────────────────────────────

_registry: list[tuple[str, GateKind, str, Callable[..., GateResult]]] = []


def gate(after: str, kind: GateKind = "mechanical"):
    """Decorator: register a gate function to run after a given state.

    The decorated function should accept `(issue, evidence)` and return a
    `GateResult`. The function name becomes the gate name in the result.
    """
    def decorator(fn: Callable[..., GateResult]) -> Callable[..., GateResult]:
        name = fn.__name__
        _registry.append((after, kind, name, fn))
        return fn
    return decorator


def run_gates(state: str, issue: IssueRef, evidence: Any) -> list[GateResult]:
    """Run every gate registered for `state` in declaration order.

    Each gate is called with `(issue, evidence)`. The gate's return value
    has its `name` and `kind` filled in from the registry before returning,
    and is appended to the result list.

    The orchestrator interprets the results: any `fail` aborts the
    workflow, any `defer` queues for the operator inbox.
    """
    results: list[GateResult] = []
    for after, kind, name, fn in _registry:
        if after != state:
            continue
        try:
            res = fn(issue, evidence)
        except Exception as e:
            results.append(GateResult(
                name=name, verdict="defer", kind=kind,
                reason=f"system:gate_crashed: {type(e).__name__}: {e}",
            ))
            continue
        # Stamp the registered name + kind onto whatever the gate returned.
        results.append(GateResult(
            name=name,
            verdict=res.verdict,
            reason=res.reason,
            evidence_data=res.evidence_data,
            score=res.score,
            kind=kind,
        ))
    return results


def registry_snapshot() -> list[tuple[str, GateKind, str]]:
    """Read-only view of every registered gate, for tests + retro reports."""
    return [(after, kind, name) for after, kind, name, _ in _registry]


def _clear_registry_for_tests() -> None:
    """Tests that import gate modules dynamically may need to reset state."""
    _registry.clear()
