"""Actionability gate — Phase 3 advisory mode.

Runs the actionability_v1 rubric after the `eligible` state. The rubric
answers "will the maintainer merge a clean PR against this issue today?"
and is the first LLM-judge call in the pipeline before any agent dispatch.

**Mode**: defaults to `advisory` — always returns Pass regardless of the
rubric's verdict, but writes the structured judge output to
`gate_decisions/actionability.json` via the M0(c) telemetry path. This
lets us collect real production decisions during the advisory period
without risking false-fail blocks on what could be a mergeable issue.

Set `CRIMSON_ACTIONABILITY_MODE=enforce` to flip to a real gate that
returns Fail / Defer / Pass per the rubric's verdict. Don't flip until
the advisory-period corpus has enough cases to confirm calibration.

The gate fetches live data (comments, timeline, sub-issues) at gate-time
because the aggregator's brief is frozen at eligibility-time. When the
aggregator's `/recon/{slug}/dispatch-readiness/{id}` endpoint (Stream B
M2.3) ships, the gate can read those signals from there instead of
re-computing locally — the score formula already lives in aggregator
land. For now we mirror it locally so the gate works end-to-end.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from . import Defer, Fail, GateResult, IssueRef, Pass, gate

logger = logging.getLogger(__name__)


# ── mode ─────────────────────────────────────────────────────────────────


def _mode() -> str:
    """advisory | enforce. Default advisory — always Pass, judge runs for
    telemetry only. Flip to enforce once advisory-period calibration is
    confirmed via the M0(c) gate_decisions ledger."""
    return os.environ.get("CRIMSON_ACTIONABILITY_MODE", "advisory").lower()


# ── helpers (injectable for tests) ───────────────────────────────────────


def _default_run_gh(args: list[str], stdin_data: str | None = None) -> dict:
    """Reuse services.github_api so we get SAML-org routing + retries +
    timeout for free. Lazy import keeps the gate module pure for cheap
    tests that don't need the gh CLI."""
    from services.github_api import run_gh_command  # type: ignore
    return run_gh_command(args, stdin_data=stdin_data)


def _default_is_bot(login: str) -> bool:
    from helpers.bot_filter import is_bot  # type: ignore
    return is_bot(login)


def _default_judge_score(rubric_md: str, input_payload: str) -> Any:
    """Lazy-imported so tests can substitute a fake without importing
    the whole judge subprocess chain."""
    from ..judge import score
    return score(rubric_md, input_payload)


def _default_load_rubric() -> str:
    from pathlib import Path
    rubric_path = Path(__file__).resolve().parent.parent / "rubrics" / "actionability_v1.md"
    return rubric_path.read_text(encoding="utf-8")


# ── fetch + signal compute ───────────────────────────────────────────────


def _gh_paginated(run_gh, endpoint: str, max_pages: int = 5) -> list:
    """Walk pages until a short response or `max_pages`. Single-page fetch
    silently truncated facebook/react#17355 (131 comments) in the
    smoke-test — verdict flipped from pass to fail with the full thread."""
    per_page = 100
    sep = "&" if "?" in endpoint else "?"
    out: list = []
    for page in range(1, max_pages + 1):
        url = f"{endpoint}{sep}per_page={per_page}&page={page}"
        r = run_gh(["api", url])
        if not r.get("success"):
            break
        try:
            chunk = json.loads(r.get("output", "") or "[]")
        except (ValueError, TypeError):
            break
        if not isinstance(chunk, list):
            break
        out.extend(chunk)
        if len(chunk) < per_page:
            break
    return out


def _maintainer_assoc(association: str) -> bool:
    return (association or "").upper() in {"OWNER", "MEMBER", "COLLABORATOR", "MAINTAINER"}


def _fetch_issue_signals(upstream_slug: str, issue_number: int, *, run_gh, is_bot) -> dict:
    """One-stop fetch for the rubric's payload + signal flags."""
    out: dict = {"errors": []}

    # Comments — paginated
    raw_comments = _gh_paginated(run_gh, f"repos/{upstream_slug}/issues/{issue_number}/comments")
    comments = []
    for c in raw_comments:
        if not isinstance(c, dict):
            continue
        login = (c.get("user") or {}).get("login", "")
        comments.append({
            "author": login,
            "association": c.get("author_association", ""),
            "is_maintainer": _maintainer_assoc(c.get("author_association")),
            "is_bot": is_bot(login),
            "at": c.get("created_at"),
            "body": (c.get("body") or "")[:2000],
        })
    out["comments"] = comments

    # Timeline — paginated, filtered to 180d
    raw_timeline = _gh_paginated(run_gh, f"repos/{upstream_slug}/issues/{issue_number}/timeline")
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    events = []
    for ev in raw_timeline:
        if not isinstance(ev, dict):
            continue
        evt = ev.get("event", "")
        if evt not in {"renamed", "labeled", "unlabeled", "assigned", "unassigned",
                       "milestoned", "demilestoned", "cross-referenced", "transferred"}:
            continue
        at = ev.get("created_at")
        try:
            at_dt = datetime.fromisoformat((at or "").replace("Z", "+00:00"))
            if at_dt < cutoff:
                continue
        except (ValueError, AttributeError):
            continue
        actor = (ev.get("actor") or {}).get("login", "")
        detail = ""
        if evt == "renamed":
            rn = ev.get("rename") or {}
            detail = f"{rn.get('from','')} → {rn.get('to','')}"
        elif evt in {"labeled", "unlabeled"}:
            detail = (ev.get("label") or {}).get("name", "")
        events.append({"event": evt, "actor": actor, "at": at, "detail": detail})
    out["recent_timeline_events"] = events

    # Linked PRs — via timeline cross-references with .pull_request set
    out["linked_pr_urls"] = [
        (ev.get("source") or {}).get("issue", {}).get("html_url", "")
        for ev in raw_timeline
        if isinstance(ev, dict) and ev.get("event") == "cross-referenced"
        and (ev.get("source") or {}).get("issue", {}).get("pull_request")
    ]
    out["linked_pr_urls"] = [u for u in out["linked_pr_urls"] if u]

    # Sub-issues
    subs_call = run_gh(["api", f"repos/{upstream_slug}/issues/{issue_number}/sub_issues"])
    if subs_call.get("success"):
        try:
            subs = json.loads(subs_call["output"]) or []
        except (ValueError, TypeError):
            subs = []
        out["sub_issues"] = {
            "count": len(subs),
            "open": sum(1 for s in subs if isinstance(s, dict) and s.get("state") == "open"),
            "closed": sum(1 for s in subs if isinstance(s, dict) and s.get("state") == "closed"),
        }
    else:
        out["sub_issues"] = {"count": 0, "open": 0, "closed": 0}

    non_bot = [c for c in comments if not c["is_bot"]]
    out["commenter_mix"] = {
        "count": len(non_bot),
        "distinct": len({c["author"] for c in non_bot}),
        "maintainers": len({c["author"] for c in non_bot if c["is_maintainer"]}),
    }
    return out


def _compute_flags(data: dict, brief_issue: dict) -> list[str]:
    """Mirror hadoku-aggregator's penalty-only formula at the flag level.
    Strings must match exactly — they're the cross-repo contract."""
    flags = []
    labels_lower = {l.lower() for l in (brief_issue.get("labels") or []) if isinstance(l, str)}
    if data["sub_issues"]["count"] >= 5 or labels_lower & {"epic", "tracking", "umbrella"}:
        flags.append("epic_shape")
    if len(data.get("linked_pr_urls") or []) > 0:
        flags.append("active_linked_pr")
    cutoff_30 = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_90 = datetime.now(timezone.utc) - timedelta(days=90)
    for ev in data.get("recent_timeline_events") or []:
        try:
            at = datetime.fromisoformat((ev["at"] or "").replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError):
            continue
        if ev["event"] in {"team_reassigned", "assigned", "unassigned"} and at >= cutoff_30:
            if "team_reassignment_recent" not in flags:
                flags.append("team_reassignment_recent")
        if ev["event"] in {"renamed", "title_changed"} and at >= cutoff_90:
            if "title_changed_recent" not in flags:
                flags.append("title_changed_recent")
    if data["commenter_mix"]["maintainers"] >= 3:
        flags.append("maintainer_debate")
    try:
        updated = datetime.fromisoformat((brief_issue.get("updatedAt") or "").replace("Z", "+00:00"))
        comment_count = brief_issue.get("commentCount", 0) or len(data.get("comments", []))
        if updated < datetime.now(timezone.utc) - timedelta(days=365) and comment_count > 0:
            flags.append("stale_discussion")
    except (ValueError, AttributeError, TypeError):
        pass
    return flags


def _build_payload(brief_issue: dict, data: dict, flags: list[str]) -> str:
    """Compose the markdown payload the rubric reads."""
    parts = [
        "## Issue body",
        "",
        f"**title**: {brief_issue.get('title', '')}",
        "",
        f"**labels**: {brief_issue.get('labels', [])}",
        "",
        f"**updated_at**: {brief_issue.get('updatedAt')}",
        "",
        "**body** (raw, may contain markdown):",
        "",
        "```",
        (brief_issue.get("body") or "")[:4000],
        "```",
        "",
        "## Comment thread (chronological)",
        "",
    ]
    if not data.get("comments"):
        parts.append("_(no comments)_")
    else:
        for c in data["comments"]:
            kind = "[BOT]" if c["is_bot"] else ("[MAINTAINER]" if c["is_maintainer"] else "[user]")
            parts.append(f"### {c['author']} {kind} — {c['at']} (assoc: {c['association']})")
            parts.append("")
            parts.append(c["body"][:800])
            parts.append("")
    parts.extend([
        "",
        "## Signal summary",
        "",
        "```json",
        json.dumps({
            "subIssues": data["sub_issues"],
            "recentTimelineEvents": data["recent_timeline_events"],
            "commenterMix": data["commenter_mix"],
            "linkedPrUrls": data["linked_pr_urls"],
            "labels": brief_issue.get("labels", []),
            "flags": flags,
        }, indent=2),
        "```",
    ])
    return "\n".join(parts)


# ── gate ─────────────────────────────────────────────────────────────────


# Thresholds — picked from the 54-issue backfill + positive-class probe.
# Pass at 0.80 (was 0.70 in the rubric draft) drops disagree_pass from
# 3/54 → 1/54. Defer-band stays at 0.40-0.80. Fail < 0.40.
_PASS_THRESHOLD = 0.80
_FAIL_THRESHOLD = 0.40


@gate(after="eligible", kind="judge")
def actionability(
    issue: IssueRef,
    evidence,
    *,
    run_gh=None,
    is_bot=None,
    judge_score=None,
    load_rubric=None,
) -> GateResult:
    """Judge whether this issue is ready for an upstream PR right now.

    Advisory mode: always returns Pass with the verdict stuffed into
    `evidence_data`. M0(c) telemetry catches the verdict via the uniform
    `gate_decisions/<name>.json` write.

    Enforce mode: returns Pass / Defer / Fail per the rubric's verdict.

    Soft-fail on missing inputs: in advisory mode, if anything goes wrong
    (no brief, judge unreachable, gh fetch failure), return Pass with the
    error in evidence_data. Telemetry captures the misfire; the dispatch
    continues unchanged. In enforce mode, propagate via Defer so the
    operator can intervene.
    """
    run_gh = run_gh or _default_run_gh
    is_bot = is_bot or _default_is_bot
    judge_score = judge_score or _default_judge_score
    load_rubric = load_rubric or _default_load_rubric
    mode = _mode()

    if not evidence.exists("01-eligible/issue_brief.json"):
        return _soft_fail(mode, "actionability:no_brief", "issue_brief.json missing")

    brief = evidence.read_json("01-eligible/issue_brief.json")
    brief_issue = brief.get("issue", {}) if isinstance(brief, dict) else {}
    if not brief_issue:
        return _soft_fail(mode, "actionability:empty_brief", "issue_brief has no issue field")

    # Fetch live signals + comments
    try:
        data = _fetch_issue_signals(
            issue.upstream_slug, issue.upstream_number,
            run_gh=run_gh, is_bot=is_bot,
        )
    except Exception as e:  # noqa: BLE001 — telemetry > correctness here
        return _soft_fail(mode, "actionability:fetch_error", f"signals fetch raised {type(e).__name__}: {e}")

    flags = _compute_flags(data, brief_issue)
    payload = _build_payload(brief_issue, data, flags)

    try:
        rubric = load_rubric()
        result = judge_score(rubric, payload)
    except Exception as e:  # noqa: BLE001
        return _soft_fail(mode, "actionability:judge_error", f"judge raised {type(e).__name__}: {e}")

    verdict_data: dict = {
        "rubric_verdict": getattr(result, "verdict", None),
        "rubric_score": getattr(result, "score", None),
        "rubric_reasoning": getattr(result, "reasoning", ""),
        "rubric_evidence": (result.raw.get("evidence", []) if isinstance(getattr(result, "raw", None), dict) else []),
        "computed_flags": flags,
        "signal_summary": {
            "sub_issues_count": data["sub_issues"]["count"],
            "linked_pr_count": len(data["linked_pr_urls"]),
            "maintainer_count": data["commenter_mix"]["maintainers"],
            "comment_count": data["commenter_mix"]["count"],
        },
        "mode": mode,
    }

    if mode == "advisory":
        # Always Pass; verdict captured in evidence_data for telemetry.
        return Pass(
            reason=f"advisory: rubric said {verdict_data['rubric_verdict']} ({verdict_data['rubric_score']})",
            evidence_data=verdict_data,
            score=verdict_data["rubric_score"],
        )

    # Enforce mode — map rubric verdict to gate result.
    rubric_score = verdict_data["rubric_score"] or 0.0
    if rubric_score >= _PASS_THRESHOLD:
        return Pass(
            reason=f"rubric_pass: {verdict_data['rubric_reasoning'][:200]}",
            evidence_data=verdict_data, score=rubric_score,
        )
    if rubric_score < _FAIL_THRESHOLD:
        return Fail(
            f"actionability rubric failed at {rubric_score:.2f}: {verdict_data['rubric_reasoning'][:200]}",
            evidence_data=verdict_data, score=rubric_score,
        )
    return Defer(
        f"actionability borderline at {rubric_score:.2f}: {verdict_data['rubric_reasoning'][:200]}",
        evidence_data=verdict_data, score=rubric_score,
    )


def _soft_fail(mode: str, error_key: str, message: str) -> GateResult:
    """Don't block a dispatch on telemetry-layer breakage."""
    data = {"error": error_key, "message": message}
    if mode == "advisory":
        return Pass(reason=f"advisory:{error_key}", evidence_data=data)
    return Defer(f"{error_key}: {message}", evidence_data=data)
