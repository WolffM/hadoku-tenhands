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
from datetime import datetime, timedelta, timezone
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
    """List every batch with a cheap activity summary.

    `deferred_count` is the number of issues parked in the operator inbox
    (`awaiting/inbox_entry.json` present, no `resolved` marker). `active`
    is True when a batch has at least one such issue — the frontend uses
    it to split the Active vs Archive tabs without fetching every batch's
    detail. Inbox membership is the only cheap, disk-derived signal that's
    reliably "needs the operator" — running-vs-aborted can't be told apart
    from disk state alone, and the operator doesn't act on those anyway.
    """
    root = _state_root()
    if not root.exists():
        return []
    batches = []
    for batch_dir in sorted(root.iterdir()):
        if not batch_dir.is_dir():
            continue
        issue_dirs = [d for d in batch_dir.iterdir() if d.is_dir()]
        deferred = 0
        for d in issue_dirs:
            aw = d / "awaiting"
            if (aw / "inbox_entry.json").exists() and not (aw / "resolved").exists():
                deferred += 1
        batches.append({
            "batch_id": batch_dir.name,
            "issue_count": len(issue_dirs),
            "deferred_count": deferred,
            "active": deferred > 0,
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


@bp.route("/api/temporal/evidence/<batch_id>/<issue_id>/<path:filepath>", methods=["GET"])
def temporal_evidence(batch_id: str, issue_id: str, filepath: str):
    """Serve a raw evidence file from the issue's state directory.

    Example: GET /api/temporal/evidence/smoke-phase3-r5/WolffM__hadoku-scraper-2/04-reproduced/notes.md
    """
    import re
    # Validate path components to prevent directory traversal
    if ".." in filepath or not re.match(r"^[\w./-]+$", filepath):
        return _error("invalid filepath", status=400)

    d = _issue_dir(batch_id, issue_id)
    target = d / filepath
    if not target.exists() or not target.is_file():
        return _error(f"file not found: {filepath}", status=404)
    # Ensure the resolved path is still inside the issue directory
    try:
        target.resolve().relative_to(d.resolve())
    except ValueError:
        return _error("path traversal rejected", status=403)

    content = target.read_text(encoding="utf-8", errors="replace")
    return _envelope({"path": filepath, "content": content})


@bp.route("/api/temporal/evidence/<batch_id>/<issue_id>", methods=["GET"])
def temporal_evidence_list(batch_id: str, issue_id: str):
    """List all evidence files for an issue, grouped by stage directory."""
    d = _issue_dir(batch_id, issue_id)
    if not d.exists():
        return _error(f"issue not found: {batch_id}/{issue_id}", status=404)

    stages: dict = {}
    for child in sorted(d.iterdir()):
        if child.is_dir() and child.name[0:2].isdigit():
            files = [f.name for f in sorted(child.iterdir()) if f.is_file()]
            stages[child.name] = files
    return _envelope({"stages": stages})


@bp.route("/api/temporal/inbox/<batch_id>/<issue_id>/resolve", methods=["POST"])
def temporal_inbox_resolve(batch_id: str, issue_id: str):
    """Mark an inbox entry resolved (clears it from `/api/temporal/inbox`).

    Writes `<issue_dir>/awaiting/resolved` — the inbox-list query reads
    this marker and skips the entry. The workflow itself doesn't write
    this file on abort signals today (gap surfaced 2026-05-14 while
    cleaning up 19 stale entries), so this endpoint covers both the
    backfill-cleanup case and any future cases where the workflow exits
    without resolving its own inbox state.

    Idempotent: returns success even if the marker already exists or
    the inbox entry never existed.
    """
    d = _issue_dir(batch_id, issue_id)
    if not d.exists():
        return _error(f"issue not found: {batch_id}/{issue_id}", status=404)

    awaiting = d / "awaiting"
    awaiting.mkdir(parents=True, exist_ok=True)
    resolved = awaiting / "resolved"
    if not resolved.exists():
        resolved.write_text(
            datetime.now(timezone.utc).isoformat(),
            encoding="utf-8",
        )
    return _envelope({"batch_id": batch_id, "issue_id": issue_id, "resolved": True})


@bp.route("/api/temporal/inbox/resolve-all", methods=["POST"])
def temporal_inbox_resolve_all():
    """Bulk-resolve every currently-deferred inbox entry.

    Use sparingly — clears the operator queue wholesale. Returns the
    list of (batch_id, issue_id) tuples that were marked resolved.
    Useful for cleanup after a wave of stale entries (e.g. abandoned
    smoke-test batches whose workflows already exited via abort).
    """
    resolved_items = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for b in _list_batches():
        bd = _batch_dir(b["batch_id"])
        for issue_dir in sorted(bd.iterdir()):
            if not issue_dir.is_dir():
                continue
            inbox_file = issue_dir / "awaiting" / "inbox_entry.json"
            resolved_marker = issue_dir / "awaiting" / "resolved"
            if not inbox_file.exists() or resolved_marker.exists():
                continue
            resolved_marker.write_text(now_iso, encoding="utf-8")
            resolved_items.append(
                {"batch_id": b["batch_id"], "issue_id": issue_dir.name}
            )
    return _envelope({"resolved": resolved_items, "count": len(resolved_items)})


@bp.route("/api/temporal/inbox", methods=["GET"])
def temporal_inbox():
    """List all currently-deferred issues across every batch.

    Phase 5.4 — when gate=operator_signoff, attach `operator_pr_url`
    and `pr_body_excerpt` (first 500 chars of the rendered body) so
    the frontend signoff card can surface them inline. Other gate
    types (judge defers like relevance / submission_judge) get the
    bare inbox_entry.json fields unchanged so existing card UI keeps
    rendering as before.
    """
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
            if not isinstance(entry, dict):
                continue
            # Temporal workflow id is `{batch_id}-{issue_id}` per
            # batch_workflow.py:47. Surface it so the inbox UI can POST
            # /api/temporal/issue/<workflow_id>/signal without guessing.
            enriched = {
                "batch_id": b["batch_id"],
                "issue_id": issue_dir.name,
                "workflow_id": f"{b['batch_id']}-{issue_dir.name}",
                **entry,
            }
            if entry.get("gate") == "operator_signoff":
                pr_url_file = issue_dir / "09-submittable" / "operator_pr_url"
                if pr_url_file.exists():
                    try:
                        enriched["operator_pr_url"] = pr_url_file.read_text(
                            encoding="utf-8"
                        ).strip()
                    except OSError:
                        pass
                body_file = issue_dir / "09-submittable" / "pr_body.md"
                if body_file.exists():
                    try:
                        body = body_file.read_text(encoding="utf-8")
                    except OSError:
                        body = ""
                    enriched["pr_body_excerpt"] = body[:500]
                title_file = issue_dir / "09-submittable" / "pr_title.txt"
                if title_file.exists():
                    try:
                        enriched["pr_title"] = title_file.read_text(
                            encoding="utf-8"
                        ).strip()
                    except OSError:
                        pass
            items.append(enriched)
    return _envelope({"items": items, "count": len(items)})


@bp.route("/api/temporal/dispatch", methods=["POST"])
def temporal_dispatch():
    """Start a test batch via the Temporal cluster.

    Body: {batch_id, issues: [{upstream_slug, fork_slug?, issue_number, raw_brief?, branch_name?, base_branch?}, ...]}
    """
    body = request.get_json(silent=True) or {}
    batch_id = body.get("batch_id")
    issues_raw = body.get("issues")
    submit_to_upstream = bool(body.get("submit_to_upstream", False))
    if not batch_id or not isinstance(issues_raw, list) or not issues_raw:
        return _error("batch_id and non-empty issues[] required", status=400)

    try:
        result = asyncio.run(_dispatch_batch(batch_id, issues_raw, submit_to_upstream))
    except Exception as e:
        return _error(f"dispatch failed: {e}", status=502)

    return _envelope(result, status=202)


async def _dispatch_batch(
    batch_id: str, issues_raw: list[dict], submit_to_upstream: bool = False,
) -> dict:
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
            copilot_task_queue=cfg.copilot_task_queue,
            submit_to_upstream=submit_to_upstream,
        )
        for i in issues_raw
    ]
    handle = await client.start_workflow(
        BatchWorkflow.run,
        BatchInput(batch_id=batch_id, issues=issues),
        id=f"batch-{batch_id}",
        task_queue=cfg.task_queue,
        task_timeout=timedelta(seconds=60),
    )
    return {
        "batch_id": batch_id,
        "workflow_id": handle.id,
        "issue_count": len(issues),
        "copilot_task_queue": cfg.copilot_task_queue,
    }


def _derive_fork(upstream_slug: str, owner: str = "WolffM") -> str:
    """Build a collision-free fork repo name.

    B23: using only the upstream repo-name portion (e.g. `core`) collides
    across owners (`vuejs/core` and `home-assistant/core` would both map
    to `WolffM/core`). Prefix with the owner so the mapping is total:
    `vuejs/core` → `WolffM/vuejs-core`, `home-assistant/core` →
    `WolffM/home-assistant-core`.

    GitHub repo names allow letters, digits, `.`, `_`, `-` — owners and
    repo names already conform, so joining with `-` is safe. Slashes get
    replaced to keep it a valid repo name.
    """
    up_owner, up_repo = upstream_slug.split("/", 1)
    combined = f"{up_owner}-{up_repo}".replace("/", "-")
    return f"{owner}/{combined}"


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


@bp.route("/api/temporal/judge/canary", methods=["POST"])
def temporal_judge_canary():
    """Diagnostic: invoke the judge's canary and report reachability.

    Answers 'is the claude CLI wired up correctly on this host?' without
    requiring a full workflow run. Returns success=true with reachable=true
    when the canary succeeds, or success=true with reachable=false + the
    exception class + message when it doesn't.
    """
    from temporal import judge as J

    claude_bin = os.environ.get("CRIMSON_CLAUDE_BIN", "claude")
    token_set = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))

    try:
        J._canary_or_raise()
        return _envelope({
            "reachable": True,
            "claude_bin": claude_bin,
            "oauth_token_set": token_set,
        })
    except J.JudgeError as e:
        return _envelope({
            "reachable": False,
            "claude_bin": claude_bin,
            "oauth_token_set": token_set,
            "error_class": type(e).__name__,
            "error_message": str(e)[:500],
        })
    except Exception as e:
        return _envelope({
            "reachable": False,
            "claude_bin": claude_bin,
            "oauth_token_set": token_set,
            "error_class": type(e).__name__,
            "error_message": str(e)[:500],
        })
