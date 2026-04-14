"""Inbox activities — Phase 1C.10.

When a judge gate returns Defer, the workflow needs to:
  1. Write an inbox entry into evidence so the operator UI can list it
  2. Fire a Discord alert so the operator notices
  3. (The actual await happens via a Temporal signal in the workflow,
     not here — these activities are purely the side effects.)

The operator resolves the defer via the inbox UI (Phase 2) which sends
a Temporal signal to the workflow. The activity that *receives* the
signal is part of the workflow itself, not this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _default_notify(message: str) -> None:
    from helpers.notifications import notify_inbox_queue  # type: ignore
    notify_inbox_queue(message)


def enqueue_for_human_review(
    state: str,
    gate_name: str,
    reason: str,
    score: float | None,
    upstream_slug: str,
    issue_number: int,
    evidence,
    *,
    notify=None,
) -> dict:
    """Write an inbox entry and fire a Discord alert.

    Writes:
      - awaiting/inbox_entry.json  (the operator UI lists from this)
      - awaiting/queued_at         (timestamp marker)
      - appends to events.jsonl
    """
    if notify is None:
        notify = _default_notify

    now = datetime.now(timezone.utc).isoformat()

    entry = {
        "state": state,
        "gate": gate_name,
        "reason": reason,
        "score": score,
        "upstream_slug": upstream_slug,
        "issue_number": issue_number,
        "queued_at": now,
    }
    evidence.write_json("awaiting/inbox_entry.json", entry)
    evidence.write_text("awaiting/queued_at", now)
    evidence.append_jsonl("events.jsonl", {"event": "inbox_enqueue", **entry})

    # Best-effort Discord notification — never fail the workflow on this.
    try:
        notify(
            f"[crimson-kitty] inbox: {upstream_slug}#{issue_number} deferred at "
            f"{state}/{gate_name} — {reason}"
        )
    except Exception:
        pass

    return {"ok": True, "queued_at": now}
