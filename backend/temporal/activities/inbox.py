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

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Default points at the production mount of vibedispatch under hadoku_site's
# edge-router. Override via INBOX_UI_BASE_URL for staging/local testing.
_DEFAULT_UI_BASE = "https://hadoku.me/dispatch/"


def _default_notify(message: str, url: str | None = None, pr_url: str | None = None) -> None:
    from helpers.notifications import notify_inbox_queue  # type: ignore
    notify_inbox_queue(message, url=url, pr_url=pr_url)


def _build_inbox_url(batch_id: str, issue_id: str) -> str:
    """Compose a deep link that lands the operator on the inbox view with
    the deferred issue pre-selected. The UI parses `view/batch/issue` from
    the query string on mount.
    """
    base = os.environ.get("INBOX_UI_BASE_URL", _DEFAULT_UI_BASE).rstrip("/")
    return f"{base}/?view=temporal&batch={batch_id}&issue={issue_id}"


def _discover_pr_url(evidence) -> str | None:
    """Return the best PR URL available at defer time, or None.

    Preference order:
      1. 09-submittable/operator_pr_url — sanitized preview PR on the fork
         (written by `prepare_for_submission`, the typical operator_signoff
         attachment).
      2. {stage}/agent_result.json:pr_url — the raw agent PR on the fork
         (present from `fixed` state onward, used when defer fires earlier
         in the pipeline like relevance gate). Walks newest stage first.
    """
    txt = evidence.read_text("09-submittable/operator_pr_url", default="").strip()
    if txt:
        return txt
    for stage in ("08-remediated", "06-verified", "05-fixed", "04-reproduced"):
        rel = f"{stage}/agent_result.json"
        if not evidence.exists(rel):
            continue
        try:
            data = evidence.read_json(rel)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("pr_url"):
            return data["pr_url"]
    return None


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

    # The evidence root layout is `state/{batch_id}/{issue_id}` so we can
    # recover both ids from the path. Tested via for_issue() in store.py.
    issue_id = evidence.root.name
    batch_id = evidence.root.parent.name
    inbox_url = _build_inbox_url(batch_id, issue_id)
    pr_url = _discover_pr_url(evidence)

    # Best-effort Discord notification — never fail the workflow on this,
    # but DO log the failure. A silent pass here masked a missing
    # `notify_inbox_queue` symbol for ~the entire Phase 5 lifetime
    # (no Discord posts fired for any defer/signoff event).
    try:
        notify(
            f"[crimson-kitty] inbox: {upstream_slug}#{issue_number} deferred at "
            f"{state}/{gate_name} — {reason}",
            url=inbox_url,
            pr_url=pr_url,
        )
    except Exception as e:
        logger.warning(
            "inbox notify failed for %s#%s at %s/%s: %s",
            upstream_slug, issue_number, state, gate_name, e,
            exc_info=True,
        )

    return {"ok": True, "queued_at": now}
