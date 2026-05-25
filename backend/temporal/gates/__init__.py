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
from datetime import datetime, timezone
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

    Phase 0 / M0(c) — uniform gate-decision telemetry. Every gate result
    is mirrored to `gate_decisions/<gate_name>.json` under the issue's
    state root so funnel analysis ("which gate is filtering most issues,
    with what reasoning?") is a one-line read per gate instead of a
    walk across gates.jsonl + transitions.jsonl + ad-hoc judge files.
    `submission_judge.json` and other gate-specific richer files still
    persist alongside — this one is the uniform-shape index.
    """
    results: list[GateResult] = []
    for after, kind, name, fn in _registry:
        if after != state:
            continue
        try:
            res = fn(issue, evidence)
        except Exception as e:
            crashed = GateResult(
                name=name, verdict="defer", kind=kind,
                reason=f"system:gate_crashed: {type(e).__name__}: {e}",
            )
            results.append(crashed)
            _write_gate_decision(evidence, crashed)
            continue
        # Stamp the registered name + kind onto whatever the gate returned.
        result = GateResult(
            name=name,
            verdict=res.verdict,
            reason=res.reason,
            evidence_data=res.evidence_data,
            score=res.score,
            kind=kind,
        )
        results.append(result)
        _write_gate_decision(evidence, result)
    return results


def _write_gate_decision(evidence: Any, result: GateResult) -> None:
    """Persist a gate decision in uniform shape under
    `gate_decisions/<gate_name>.json`.

    Failures are swallowed — telemetry should never block a workflow.
    Evidence stores in tests may be substituted with stubs that lack
    `write_json`; in that case the decision just isn't mirrored and
    the gate result still propagates correctly via the return list."""
    write_json = getattr(evidence, "write_json", None)
    if write_json is None:
        return
    payload = {
        "name": result.name,
        "verdict": result.verdict,
        "kind": result.kind,
        "reason": result.reason,
        "score": result.score,
        "evidence_data": result.evidence_data,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        write_json(f"gate_decisions/{result.name}.json", payload)
    except Exception:
        # Telemetry must never block. Swallow so an evidence-store hiccup
        # doesn't take down the gate runner.
        pass


def registry_snapshot() -> list[tuple[str, GateKind, str]]:
    """Read-only view of every registered gate, for tests + retro reports."""
    return [(after, kind, name) for after, kind, name, _ in _registry]


def _clear_registry_for_tests() -> None:
    """Tests that import gate modules dynamically may need to reset state."""
    _registry.clear()
