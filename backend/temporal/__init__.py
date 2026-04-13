"""crimson-kitty: Temporal-based contribution pipeline.

This package contains the third-generation contribution pipeline, built on
Temporal as the workflow engine. It coexists with the legacy oss_service
pipeline during the build phase.

Layout:
    workflows/   — Temporal workflow definitions (deterministic)
    activities/  — Side-effect activities (wrap existing helpers/services)
    gates/       — Registered gates that decide state transitions
    evidence/    — Evidence store: per-issue artifact directories
    agents/      — Agent adapter protocol + Copilot/Noop implementations
    sanitizer.py — Commit-rewriter pipeline (broadens oss_firewall)
    pr_body_builder.py — Renders structured PR body from evidence
    judge.py     — LLM judge wrapper for `judge`-kind gates
    config.py    — Temporal client config
    worker.py    — Entry point for the Temporal worker process

See docs/crimson-kitty/ for the full design.
"""
