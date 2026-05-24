"""Outcome snapshot activity — Phase 0 / M0.1.

Standalone classifier for "what happened to this dispatched PR upstream?"
The sibling `watch_upstream_pr_state` polls inside an active workflow's
post-submission loop; this one runs OUT of workflow (cron-driven) so
historical / terminal dispatches can be classified and the May 2026 23-pass
cohort baseline can be captured.

Inputs come from on-disk evidence + (when needed) one live GH poll per
open PR. Output goes to `outcomes/upstream_state.json` under the issue's
state root.

State classification (matches the success-metric buckets in the planning
doc):

- `merged` — upstream PR merged (terminal, on-disk evidence wins)
- `closed_unmerged` — upstream closed PR without merging (terminal)
- `open` — upstream PR open; 30d/90d staleness checkpoints carried alongside
- `not_submitted` — never reached `10-submitted/` (deferred at signoff,
  aborted, still in flight, etc.)
- `aborted_by_operator` — operator-aborted via inbox signal

"Maintainer engagement" — what resets the staleness clock — is the latest
timestamp on a non-bot comment or review against the PR. `pr.updated_at`
includes bot pushes and so isn't a reliable staleness signal on its own;
we filter via the existing `is_bot()` helper.
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _default_run_gh(args: list[str], stdin_data: str | None = None) -> dict:
    from services.github_api import run_gh_command  # type: ignore
    return run_gh_command(args, stdin_data=stdin_data)


def _default_is_bot(login: str) -> bool:
    from helpers.bot_filter import is_bot  # type: ignore
    return is_bot(login)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # GitHub returns trailing Z; fromisoformat handles that since 3.11
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _days_between(then: datetime | None, now: datetime) -> int | None:
    if then is None:
        return None
    return int((now - then).total_seconds() // 86400)


def _operator_aborted(evidence) -> bool:
    """Read transitions.jsonl tail; was the final transition an operator abort?"""
    if not evidence.exists("transitions.jsonl"):
        return False
    last = None
    for raw in evidence.read_text("transitions.jsonl").splitlines():
        if raw.strip():
            last = raw
    if not last:
        return False
    try:
        rec = _json.loads(last)
    except (ValueError, TypeError):
        return False
    if rec.get("to") != "aborted":
        return False
    reason = (rec.get("reason") or "").lower()
    return reason.startswith("operator aborted")


def classify_outcome(
    evidence,
    *,
    run_gh: Callable | None = None,
    is_bot: Callable[[str], bool] | None = None,
    now: datetime | None = None,
) -> dict:
    """Classify one issue's upstream outcome from evidence + (when needed) live poll.

    Reads terminal markers first — `11-merged/` and `11-closed_by_upstream/`
    are authoritative; no GH call needed for those. Falls back to one live
    `/pulls/{n}` + `/issues/{n}/comments` + `/pulls/{n}/reviews` poll when
    a `10-submitted/upstream_pr_url` exists but no terminal marker.

    Pure: writes nothing. Caller persists the dict via `write_outcome_snapshot`.
    """
    if run_gh is None:
        run_gh = _default_run_gh
    if is_bot is None:
        is_bot = _default_is_bot
    if now is None:
        now = _now_utc()

    out: dict[str, Any] = {
        "state": "unknown",
        "upstream_pr_url": None,
        "upstream_pr_number": None,
        "upstream_slug": None,
        "merged_at": None,
        "merge_sha": None,
        "merged_by": None,
        "closed_at": None,
        "closer": None,
        "last_maintainer_engagement_at": None,
        "days_since_submission": None,
        "days_since_last_engagement": None,
        "stale_30d_at_snapshot": False,
        "stale_90d_at_snapshot": False,
        "snapshot_at": now.isoformat(),
        "snapshot_source": "evidence",
        "errors": [],
    }

    # ── Terminal: merged (on-disk evidence is authoritative) ─────────────
    if evidence.exists("11-merged/merge_info.json"):
        info = evidence.read_json("11-merged/merge_info.json")
        if isinstance(info, dict):
            out["state"] = "merged"
            out["merged_at"] = info.get("merged_at") or None
            out["merge_sha"] = info.get("merge_sha") or None
            out["merged_by"] = info.get("merged_by") or None
            out["upstream_slug"] = info.get("upstream_slug")
            out["upstream_pr_number"] = info.get("pr_number")
            if out["upstream_slug"] and out["upstream_pr_number"]:
                out["upstream_pr_url"] = (
                    f"https://github.com/{out['upstream_slug']}/pull/"
                    f"{out['upstream_pr_number']}"
                )
            return out

    # ── Terminal: closed without merge ───────────────────────────────────
    if evidence.exists("11-closed_by_upstream/close_info.json"):
        info = evidence.read_json("11-closed_by_upstream/close_info.json")
        if isinstance(info, dict):
            out["state"] = "closed_unmerged"
            out["closed_at"] = info.get("closed_at") or None
            out["closer"] = info.get("closer") or None
            out["upstream_slug"] = info.get("upstream_slug")
            out["upstream_pr_number"] = info.get("pr_number")
            if out["upstream_slug"] and out["upstream_pr_number"]:
                out["upstream_pr_url"] = (
                    f"https://github.com/{out['upstream_slug']}/pull/"
                    f"{out['upstream_pr_number']}"
                )
            return out

    # ── Not submitted? ───────────────────────────────────────────────────
    if not evidence.exists("10-submitted/upstream_pr_url"):
        out["state"] = "aborted_by_operator" if _operator_aborted(evidence) else "not_submitted"
        return out

    # ── Open: live poll ──────────────────────────────────────────────────
    out["snapshot_source"] = "live_poll"
    pr_url = evidence.read_text("10-submitted/upstream_pr_url").strip()
    pr_number_text = evidence.read_text("10-submitted/upstream_pr_number", default="").strip()
    out["upstream_pr_url"] = pr_url

    upstream_slug, pr_number = _parse_pr_url(pr_url)
    if not upstream_slug or not pr_number:
        out["state"] = "unknown"
        out["errors"].append(f"could not parse upstream_pr_url: {pr_url!r}")
        return out
    out["upstream_slug"] = upstream_slug
    out["upstream_pr_number"] = pr_number
    # Prefer the explicit number file when present (it's the authoritative
    # source even when the URL parser succeeds), but fall back to URL.
    if pr_number_text:
        try:
            out["upstream_pr_number"] = int(pr_number_text)
        except ValueError:
            pass

    pr_fetch = run_gh([
        "api",
        f"repos/{upstream_slug}/pulls/{pr_number}",
        "--jq",
        '{state: .state, merged: .merged, merged_at: .merged_at, '
        'merge_commit_sha: .merge_commit_sha, closed_at: .closed_at, '
        'created_at: .created_at, updated_at: .updated_at, '
        'merged_by: (.merged_by.login // null), '
        'closer: (.user.login // null)}',
    ])
    if not pr_fetch.get("success"):
        out["state"] = "unknown"
        out["errors"].append(f"pr fetch: {pr_fetch.get('error', '')[:200]}")
        return out
    try:
        pr_data = _json.loads(pr_fetch.get("output", "") or "{}")
    except (ValueError, TypeError):
        out["state"] = "unknown"
        out["errors"].append("pr fetch: invalid JSON")
        return out

    # Did terminal happen since we last saw it?
    if pr_data.get("merged"):
        out["state"] = "merged"
        out["merged_at"] = pr_data.get("merged_at")
        out["merge_sha"] = pr_data.get("merge_commit_sha")
        out["merged_by"] = pr_data.get("merged_by")
        return out
    if (pr_data.get("state") or "").lower() == "closed":
        out["state"] = "closed_unmerged"
        out["closed_at"] = pr_data.get("closed_at")
        out["closer"] = pr_data.get("closer")
        return out

    # Open — capture engagement signal
    out["state"] = "open"
    submitted_at = _parse_iso(pr_data.get("created_at"))
    out["days_since_submission"] = _days_between(submitted_at, now)

    last_human = _latest_human_engagement(
        run_gh, upstream_slug, pr_number, is_bot, out["errors"],
    )
    # Fall back to PR updated_at if no comment/review activity (e.g. brand-new
    # PR with no engagement yet). Marked best-effort because `updated_at`
    # includes bot pushes.
    if last_human is None:
        last_human = _parse_iso(pr_data.get("updated_at"))
        if last_human is not None:
            out["errors"].append(
                "no non-bot comment/review activity found; using pr.updated_at "
                "(includes bot activity) as engagement fallback"
            )
    out["last_maintainer_engagement_at"] = (
        last_human.isoformat() if last_human else None
    )
    out["days_since_last_engagement"] = _days_between(last_human, now)
    if out["days_since_last_engagement"] is not None:
        out["stale_30d_at_snapshot"] = out["days_since_last_engagement"] >= 30
        out["stale_90d_at_snapshot"] = out["days_since_last_engagement"] >= 90

    return out


def _parse_pr_url(url: str) -> tuple[str | None, int | None]:
    """`https://github.com/owner/repo/pull/N` → ("owner/repo", N)."""
    if not url:
        return None, None
    parts = url.rstrip("/").split("/")
    if len(parts) < 5 or "github.com" not in parts[2]:
        return None, None
    try:
        owner, repo = parts[-4], parts[-3]
        number = int(parts[-1])
        return f"{owner}/{repo}", number
    except (ValueError, IndexError):
        return None, None


def _latest_human_engagement(
    run_gh, upstream_slug: str, pr_number: int, is_bot, errors: list,
) -> datetime | None:
    """Latest non-bot activity timestamp across PR comments + reviews.

    Two GH calls. Bot activity is filtered via the shared `is_bot()` helper
    so a Copilot push or a github-actions[bot] check doesn't reset the
    staleness clock. Returns None if no human activity is found OR if both
    fetches fail (the caller's fallback handles that)."""
    latest: datetime | None = None

    comments = run_gh([
        "api",
        f"repos/{upstream_slug}/issues/{pr_number}/comments?per_page=100",
        "--jq",
        '[.[] | {user: .user.login, at: .created_at}]',
    ])
    if comments.get("success"):
        try:
            items = _json.loads(comments.get("output", "") or "[]") or []
        except (ValueError, TypeError):
            items = []
        for c in items:
            if is_bot(c.get("user") or ""):
                continue
            at = _parse_iso(c.get("at"))
            if at and (latest is None or at > latest):
                latest = at
    else:
        errors.append(f"comments fetch: {comments.get('error', '')[:120]}")

    reviews = run_gh([
        "api",
        f"repos/{upstream_slug}/pulls/{pr_number}/reviews?per_page=100",
        "--jq",
        '[.[] | {user: .user.login, at: .submitted_at}]',
    ])
    if reviews.get("success"):
        try:
            items = _json.loads(reviews.get("output", "") or "[]") or []
        except (ValueError, TypeError):
            items = []
        for r in items:
            if is_bot(r.get("user") or ""):
                continue
            at = _parse_iso(r.get("at"))
            if at and (latest is None or at > latest):
                latest = at
    else:
        errors.append(f"reviews fetch: {reviews.get('error', '')[:120]}")

    return latest


def write_outcome_snapshot(evidence, snapshot: dict) -> None:
    """Persist the snapshot to `outcomes/upstream_state.json` under the
    issue's state root. Idempotent: overwrites prior snapshot in place."""
    evidence.write_json("outcomes/upstream_state.json", snapshot)


def snapshot_outcome(
    evidence,
    *,
    run_gh: Callable | None = None,
    is_bot: Callable[[str], bool] | None = None,
    now: datetime | None = None,
) -> dict:
    """Classify and persist in one call — the activity entry point."""
    snap = classify_outcome(evidence, run_gh=run_gh, is_bot=is_bot, now=now)
    write_outcome_snapshot(evidence, snap)
    return snap
