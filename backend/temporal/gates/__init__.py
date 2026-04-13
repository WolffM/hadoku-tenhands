"""Gate registry.

Gates are pure functions over the evidence store that decide pass / fail /
defer. They are the SINGLE place where validation logic lives. Replaces the
scattered `_sanitize_upstream_refs`, `is_bot`, dedup-guard, and ad-hoc `if`
checks from the old pipeline.

Each gate is registered with the state it runs after. The orchestrator
(IssueWorkflow) calls run_gates(state, evidence_dir) after every state
transition.

See docs/crimson-kitty/gates.md for the full registry and the
bug→gate mapping from the jade-hare retro.

Pseudocode:

    from dataclasses import dataclass
    from typing import Callable, Literal

    @dataclass
    class GateResult:
        name: str
        verdict: Literal["pass", "fail", "defer"]
        reason: str = ""
        evidence_data: dict | None = None
        score: float | None = None

    _registry: list[tuple[str, str, Callable]] = []

    def gate(after: str, kind: Literal["mechanical", "judge", "human"]):
        def decorator(fn):
            _registry.append((after, kind, fn))
            return fn
        return decorator

    def run_gates(state: str, evidence_dir: str) -> list[GateResult]:
        results = []
        for after, kind, fn in _registry:
            if after != state:
                continue
            results.append(fn(evidence_dir))
        return results

The actual gate implementations live in sibling modules:
    eligibility.py
    quarantine_isolation.py
    environment.py
    repro.py
    fix.py
    verify.py
    remediation.py
    submission.py
"""
