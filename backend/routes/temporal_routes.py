"""Crimson-kitty / Temporal pipeline HTTP routes — Phase 1D.4.

Operator inbox + dispatch surface for the crimson-kitty pipeline. Mounted
on the shared `bp` blueprint from `routes/__init__.py`.

Endpoints:

  GET  /api/temporal/health                      → cluster + worker status
  GET  /api/temporal/batches                     → list of all batches
  GET  /api/temporal/batch/<batch_id>            → per-batch summary
  GET  /api/temporal/issue/<batch_id>/<issue_id> → per-issue evidence + state
  GET  /api/temporal/inbox                       → all currently deferred issues
  POST /api/temporal/dispatch                    → start a batch via Temporal
  POST /api/temporal/issue/<workflow_id>/signal  → resolve a deferred workflow

Most reads work directly off the evidence store on disk so they don't
require the Temporal cluster to be reachable. The dispatch + signal
endpoints DO require the cluster.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from flask import jsonify, request

from . import bp


def _state_root() -> Path:
    """Read CRIMSON_STATE_ROOT at request time so tests can override it."""
    return Path(os.environ.get("CRIMSON_STATE_ROOT", "state"))


# ── helpers ───────────────────────────────────────────────────────────────


def _envelope(data: Any, status: int = 200, **meta):
    return jsonify({"success": True, "data": data, "_meta": meta}), status


def _error(message: str, status: int = 400, **extra):
    return jsonify({"success": False, "error": message, **extra}), status


def _read_json_safely(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_jsonl_safely(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _list_batches() -> list[dict]:
    root = _state_root()
    if not root.exists():
        return []
    batches = []
    for batch_dir in sorted(root.iterdir()):
        if not batch_dir.is_dir():
            continue
        issues = [d.name for d in batch_dir.iterdir() if d.is_dir()]
        batches.append({
            "batch_id": batch_dir.name,
            "issue_count": len(issues),
        })
    return batches


def _batch_dir(batch_id: str) -> Path:
    return _state_root() / batch_id


def _issue_dir(batch_id: str, issue_id: str) -> Path:
    return _state_root() / batch_id / issue_id


def _issue_summary(batch_id: str, issue_id: str) -> dict:
    """Read the issue's transitions log + current state from evidence."""
    d = _issue_dir(batch_id, issue_id)
    transitions = _read_jsonl_safely(d / "transitions.jsonl")
    gates = _read_jsonl_safely(d / "gates.jsonl")
    inbox = _read_json_safely(d / "awaiting" / "inbox_entry.json")

    current_state = transitions[-1]["to"] if transitions else "candidate"
    is_deferred = inbox is not None and not (d / "awaiting" / "resolved").exists()

    return {
        "batch_id": batch_id,
        "issue_id": issue_id,
        "current_state": current_state,
        "is_deferred": is_deferred,
        "deferred_at": inbox.get("state") if isinstance(inbox, dict) else None,
        "deferred_gate": inbox.get("gate") if isinstance(inbox, dict) else None,
        "transition_count": len(transitions),
        "gate_count": len(gates),
    }


# ── Routes ────────────────────────────────────────────────────────────────


@bp.route("/api/temporal/health", methods=["GET"])
def temporal_health():
    root = _state_root()
    return _envelope({
        "state_root": str(root),
        "state_root_exists": root.exists(),
        "batch_count": len(_list_batches()),
        "cluster_check": "skipped",
    })


@bp.route("/api/temporal/batches", methods=["GET"])
def temporal_batches():
    return _envelope({"batches": _list_batches()})


@bp.route("/api/temporal/batch/<batch_id>", methods=["GET"])
def temporal_batch(batch_id: str):
    d = _batch_dir(batch_id)
    if not d.exists():
        return _error(f"batch not found: {batch_id}", status=404)
    issues = [
        _issue_summary(batch_id, issue_dir.name)
        for issue_dir in sorted(d.iterdir()) if issue_dir.is_dir()
    ]
    return _envelope({
        "batch_id": batch_id,
        "issue_count": len(issues),
        "issues": issues,
    })


@bp.route("/api/temporal/issue/<batch_id>/<issue_id>", methods=["GET"])
def temporal_issue(batch_id: str, issue_id: str):
    d = _issue_dir(batch_id, issue_id)
    if not d.exists():
        return _error(f"issue not found: {batch_id}/{issue_id}", status=404)

    summary = _issue_summary(batch_id, issue_id)
    summary["transitions"] = _read_jsonl_safely(d / "transitions.jsonl")
    summary["gates"] = _read_jsonl_safely(d / "gates.jsonl")
    summary["events"] = _read_jsonl_safely(d / "events.jsonl")[-50:]
    return _envelope(summary)


@bp.route("/api/temporal/inbox", methods=["GET"])
def temporal_inbox():
    """List all currently-deferred issues across every batch."""
    items = []
    for b in _list_batches():
        bd = _batch_dir(b["batch_id"])
        for issue_dir in sorted(bd.iterdir()):
            if not issue_dir.is_dir():
                continue
            inbox_file = issue_dir / "awaiting" / "inbox_entry.json"
            resolved = issue_dir / "awaiting" / "resolved"
            if not inbox_file.exists() or resolved.exists():
                continue
            entry = _read_json_safely(inbox_file)
            if isinstance(entry, dict):
                items.append({
                    "batch_id": b["batch_id"],
                    "issue_id": issue_dir.name,
                    **entry,
                })
    return _envelope({"items": items, "count": len(items)})


@bp.route("/api/temporal/dispatch", methods=["POST"])
def temporal_dispatch():
    """Start a test batch via the Temporal cluster.

    Body: {batch_id, issues: [{upstream_slug, fork_slug?, issue_number, raw_brief?, branch_name?, base_branch?}, ...]}
    """
    body = request.get_json(silent=True) or {}
    batch_id = body.get("batch_id")
    issues_raw = body.get("issues")
    if not batch_id or not isinstance(issues_raw, list) or not issues_raw:
        return _error("batch_id and non-empty issues[] required", status=400)

    try:
        result = asyncio.run(_dispatch_batch(batch_id, issues_raw))
    except Exception as e:
        return _error(f"dispatch failed: {e}", status=502)

    return _envelope(result, status=202)


async def _dispatch_batch(batch_id: str, issues_raw: list[dict]) -> dict:
    """Connect to Temporal and start the BatchWorkflow."""
    from temporalio.client import Client

    from temporal.config import load_config
    from temporal.workflows import BatchInput, BatchWorkflow, IssueInput

    cfg = load_config()
    client = await Client.connect(cfg.host, namespace=cfg.namespace)

    issues = [
        IssueInput(
            upstream_slug=i["upstream_slug"],
            fork_slug=i.get("fork_slug") or _derive_fork(i["upstream_slug"]),
            issue_number=int(i["issue_number"]),
            state_root=str(
                _state_root() / batch_id /
                f"{i['upstream_slug'].replace('/', '__')}-{i['issue_number']}"
            ),
            raw_brief_text=i.get("raw_brief", ""),
            branch_name=i.get("branch_name") or f"crimson-kitty-{i['issue_number']}",
            base_branch=i.get("base_branch", "main"),
        )
        for i in issues_raw
    ]
    handle = await client.start_workflow(
        BatchWorkflow.run,
        BatchInput(batch_id=batch_id, issues=issues),
        id=f"batch-{batch_id}",
        task_queue=cfg.task_queue,
    )
    return {"batch_id": batch_id, "workflow_id": handle.id, "issue_count": len(issues)}


def _derive_fork(upstream_slug: str, owner: str = "WolffM") -> str:
    return f"{owner}/{upstream_slug.split('/', 1)[1]}"


@bp.route("/api/temporal/issue/<workflow_id>/signal", methods=["POST"])
def temporal_signal(workflow_id: str):
    """Send a `submit_human_decision` signal to a deferred IssueWorkflow.

    Body: {decision: "approve" | "abort" | "retry"}
    """
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("approve", "abort", "retry"):
        return _error("decision must be one of approve|abort|retry", status=400)

    try:
        asyncio.run(_send_signal(workflow_id, decision))
    except Exception as e:
        return _error(f"signal failed: {e}", status=502)

    return _envelope({"workflow_id": workflow_id, "decision": decision})


async def _send_signal(workflow_id: str, decision: str) -> None:
    from temporalio.client import Client

    from temporal.config import load_config

    cfg = load_config()
    client = await Client.connect(cfg.host, namespace=cfg.namespace)
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal("submit_human_decision", decision)
