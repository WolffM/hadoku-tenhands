"""Smoke-test actionability_v1.md against 5 hand-picked historical issues.

Task #54 from the dispatch-readiness-overhaul plan. Goal: catch obvious
prompt failures (judge ignores comments, judge always returns same
verdict, judge fabricates evidence) before committing to the full
54-issue backfill.

Throwaway. Once Phase 1 / M1.3 ships and aggregator populates the
real signal summary in KV, the backfill driver reads from the aggregator
endpoint instead of fetching live here.

Usage: python3 scripts/smoke_actionability.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from temporal.judge import score, JudgeUnreachable, JudgeParseError  # noqa: E402


# SAML token for Microsoft org — fetched via vault since smoke test runs
# from the operator workstation, not the prod pm2 env.
def _fetch_msft_sso() -> str | None:
    """Fetch SAML_ORG_TOKEN from the vault using vibedispatch's service-tier key."""
    try:
        vkey = json.loads((REPO_ROOT / ".devvault.local.json").read_text())["key"]
        req = urllib.request.Request(
            "https://hadoku.me/mgmt/api/secrets/get/VIBEDISPATCH_SAML_ORG_TOKEN",
            headers={"X-User-Key": vkey, "User-Agent": "curl/8.5.0"},
        )
        body = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return body.get("value")
    except Exception as e:
        print(f"  ! could not fetch SAML_ORG_TOKEN: {e}", file=sys.stderr)
        return None


_MSFT_TOKEN = None


# 5 hand-picked smoke targets, with the operator's expected verdict noted
# so we can eyeball agreement.
SMOKE_TARGETS = [
    {
        "label": "keycloak#46523 (canary — operator aborted as scope_mismatch)",
        "upstream_slug": "keycloak/keycloak",
        "issue_number": 46523,
        "operator_decision": "abort_scope_mismatch",
        "expected_verdict": "fail",
    },
    {
        "label": "microsoft/pyright#11408 (operator aborted at judge defer)",
        "upstream_slug": "microsoft/pyright",
        "issue_number": 11408,
        "operator_decision": "abort_at_judge",
        "expected_verdict": "defer-or-fail",
    },
    {
        "label": "docker/compose#9026 (judge passed/deferred, never approved)",
        "upstream_slug": "docker/compose",
        "issue_number": 9026,
        "operator_decision": "deferred_indefinitely",
        "expected_verdict": "informative",
    },
    {
        "label": "obsidian-tasks-group/obsidian-tasks#1016 (issue may be fine; our diff was junk)",
        "upstream_slug": "obsidian-tasks-group/obsidian-tasks",
        "issue_number": 1016,
        "operator_decision": "internal_relevance_fail",
        "expected_verdict": "judge the issue not the diff",
    },
    {
        "label": "microsoft/monaco-editor#3336 (early-stage crash, not issue-quality)",
        "upstream_slug": "microsoft/monaco-editor",
        "issue_number": 3336,
        "operator_decision": "infra_crash",
        "expected_verdict": "judge the issue not the crash",
    },
]


def _gh(args: list[str], saml_org: bool = False) -> dict | list | None:
    """Run gh api and parse JSON. Returns None on failure.

    When `saml_org=True`, injects GH_TOKEN=SAML_ORG_TOKEN so SAML-required orgs
    (Microsoft) work. This mirrors vibedispatch's prod routing in
    services/github_api.py."""
    env = os.environ.copy()
    if saml_org:
        global _MSFT_TOKEN
        if _MSFT_TOKEN is None:
            _MSFT_TOKEN = _fetch_msft_sso()
        if _MSFT_TOKEN:
            env["GH_TOKEN"] = _MSFT_TOKEN

    r = subprocess.run(["gh", "api"] + args, capture_output=True, text=True, timeout=30, env=env)
    if r.returncode != 0:
        print(f"  ! gh {args[0]} failed: {r.stderr[:120]}", file=sys.stderr)
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _gh_paginated(endpoint: str, saml_org: bool = False, max_pages: int = 10) -> list:
    """Fetch a paginated GitHub list endpoint and concatenate all pages.

    Used for /comments and /timeline where issues can have > 100 entries
    and a single `?per_page=100` fetch silently truncates. Manually walks
    pages until a short response (< 100) or `max_pages` is hit. We could
    use `gh api --paginate` but its output format (concatenated JSON arrays
    separated by newlines) is awkward to parse — manual pagination keeps
    the response as a single Python list.

    Returns an empty list on first-page failure rather than None so callers
    don't need to special-case (truncation is bad but missing pagination
    headers is worse — fail loudly via the empty list)."""
    env = os.environ.copy()
    if saml_org:
        global _MSFT_TOKEN
        if _MSFT_TOKEN is None:
            _MSFT_TOKEN = _fetch_msft_sso()
        if _MSFT_TOKEN:
            env["GH_TOKEN"] = _MSFT_TOKEN

    per_page = 100
    base = endpoint
    sep = "&" if "?" in base else "?"
    out: list = []
    for page in range(1, max_pages + 1):
        url = f"{base}{sep}per_page={per_page}&page={page}"
        r = subprocess.run(
            ["gh", "api", url], capture_output=True, text=True, timeout=30, env=env,
        )
        if r.returncode != 0:
            print(f"  ! gh paginated page {page} failed: {r.stderr[:120]}", file=sys.stderr)
            break
        try:
            chunk = json.loads(r.stdout)
        except json.JSONDecodeError:
            break
        if not isinstance(chunk, list):
            break
        out.extend(chunk)
        if len(chunk) < per_page:
            break
    return out


def _author_is_maintainer(association: str) -> bool:
    """OWNER / MEMBER / COLLABORATOR / MAINTAINER → maintainer.
    CONTRIBUTOR / FIRST_TIME_CONTRIBUTOR / FIRST_TIMER / NONE → not."""
    return (association or "").upper() in {"OWNER", "MEMBER", "COLLABORATOR", "MAINTAINER"}


def _is_bot(login: str) -> bool:
    lower = (login or "").lower()
    return "[bot]" in lower or "copilot" in lower or lower in {
        "github-actions", "dependabot", "renovate", "codecov", "snyk-bot",
    }


def fetch_issue_data(slug: str, number: int) -> dict:
    """Pull everything the rubric needs in one place."""
    owner, repo = slug.split("/", 1)
    saml = owner.lower() == "microsoft"
    out: dict = {"slug": slug, "number": number, "errors": []}

    # Issue body + labels + assignees
    issue = _gh([f"repos/{slug}/issues/{number}"], saml_org=saml)
    if issue:
        out["title"] = issue.get("title", "")
        out["body"] = issue.get("body", "") or ""
        out["labels"] = [l.get("name", "") for l in (issue.get("labels") or []) if isinstance(l, dict)]
        out["updated_at"] = issue.get("updated_at")
        out["comment_count"] = issue.get("comments", 0)
    else:
        out["errors"].append("issue fetch failed")
        return out

    # Comments — paginated so we don't silently truncate on large threads
    # (facebook/react#17355 has 131 comments; per_page=100 single-fetch
    # missed the last 31 and shifted the rubric verdict).
    comments = _gh_paginated(f"repos/{slug}/issues/{number}/comments", saml_org=saml)
    out["comments"] = [
        {
            "author": c.get("user", {}).get("login", ""),
            "association": c.get("author_association", ""),
            "is_maintainer": _author_is_maintainer(c.get("author_association")),
            "is_bot": _is_bot(c.get("user", {}).get("login", "")),
            "at": c.get("created_at"),
            "body": (c.get("body") or "")[:2000],
        }
        for c in comments if isinstance(c, dict)
    ]

    # Timeline events (filter to recent 180d, exclude noise) — paginated
    timeline = _gh_paginated(f"repos/{slug}/issues/{number}/timeline", saml_org=saml)
    cutoff = datetime.now(timezone.utc) - timedelta(days=180)
    events = []
    for ev in timeline:
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
            rename = ev.get("rename") or {}
            detail = f"{rename.get('from','')} → {rename.get('to','')}"
        elif evt in {"labeled", "unlabeled"}:
            detail = (ev.get("label") or {}).get("name", "")
        events.append({"event": evt, "actor": actor, "at": at, "detail": detail})
    out["recent_timeline_events"] = events

    # Linked PRs (via timeline cross-references, GitHub native)
    out["linked_pr_urls"] = [
        (ev.get("source") or {}).get("issue", {}).get("html_url", "")
        for ev in timeline
        if isinstance(ev, dict) and ev.get("event") == "cross-referenced"
        and (ev.get("source") or {}).get("issue", {}).get("pull_request")
    ]
    out["linked_pr_urls"] = [u for u in out["linked_pr_urls"] if u]

    # Sub-issues (REST endpoint)
    subs = _gh([f"repos/{slug}/issues/{number}/sub_issues"], saml_org=saml) or []
    if isinstance(subs, list):
        out["sub_issues"] = {
            "count": len(subs),
            "open": sum(1 for s in subs if isinstance(s, dict) and s.get("state") == "open"),
            "closed": sum(1 for s in subs if isinstance(s, dict) and s.get("state") == "closed"),
        }
    else:
        # Some repos don't have the feature enabled; treat as 0
        out["sub_issues"] = {"count": 0, "open": 0, "closed": 0}

    # Commenter mix (non-bot human counts)
    non_bot = [c for c in out["comments"] if not c["is_bot"]]
    distinct_authors = {c["author"] for c in non_bot}
    distinct_maintainers = {c["author"] for c in non_bot if c["is_maintainer"]}
    out["commenter_mix"] = {
        "count": len(non_bot),
        "distinct": len(distinct_authors),
        "maintainers": len(distinct_maintainers),
    }

    return out


def compute_flags(data: dict) -> list[str]:
    """Mirror hadoku-aggregator's penalty-only readiness formula at the flag level.
    These are the exact strings pinned in the cross-repo contract."""
    flags = []
    if data.get("sub_issues", {}).get("count", 0) >= 5:
        flags.append("epic_shape")
    elif {l.lower() for l in data.get("labels", [])} & {"epic", "tracking", "umbrella"}:
        flags.append("epic_shape")

    if len(data.get("linked_pr_urls") or []) > 0:
        flags.append("active_linked_pr")

    events = data.get("recent_timeline_events") or []
    cutoff_30 = datetime.now(timezone.utc) - timedelta(days=30)
    cutoff_90 = datetime.now(timezone.utc) - timedelta(days=90)
    for ev in events:
        try:
            at = datetime.fromisoformat((ev["at"] or "").replace("Z", "+00:00"))
        except (ValueError, AttributeError, TypeError):
            continue
        if ev["event"] in {"assigned", "unassigned"} and at >= cutoff_30:
            if "team_reassignment_recent" not in flags:
                flags.append("team_reassignment_recent")
        if ev["event"] == "renamed" and at >= cutoff_90:
            if "title_changed_recent" not in flags:
                flags.append("title_changed_recent")

    if data.get("commenter_mix", {}).get("maintainers", 0) >= 3:
        flags.append("maintainer_debate")

    try:
        updated = datetime.fromisoformat((data.get("updated_at") or "").replace("Z", "+00:00"))
        if updated < datetime.now(timezone.utc) - timedelta(days=365) and data.get("comment_count", 0) > 0:
            flags.append("stale_discussion")
    except (ValueError, AttributeError, TypeError):
        pass

    return flags


def build_payload(data: dict, flags: list[str]) -> str:
    """Compose the markdown payload the rubric consumes."""
    parts = [
        "## Issue body",
        "",
        f"**title**: {data.get('title','')}",
        "",
        f"**labels**: {data.get('labels', [])}",
        "",
        f"**updated_at**: {data.get('updated_at')}",
        "",
        f"**body** (raw, may contain markdown):",
        "",
        "```",
        (data.get("body", "") or "")[:4000],
        "```",
        "",
        "## Comment thread (chronological)",
        "",
    ]
    if not data.get("comments"):
        parts.append("_(no comments)_")
    else:
        # Show ALL comments now that fetch is paginated. Per-body truncated
        # to 800 chars so large threads (131-comment facebook/react#17355)
        # stay well inside the Sonnet context window. Previously this was
        # capped at 40 comments × 1500 chars — when combined with the 100-
        # comment fetch cap, a 131-comment issue lost both ends of its
        # thread (31 missed in fetch + only first 40 in payload).
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
        f"```json",
        json.dumps({
            "subIssues": data.get("sub_issues", {}),
            "recentTimelineEvents": data.get("recent_timeline_events", []),
            "commenterMix": data.get("commenter_mix", {}),
            "linkedPrUrls": data.get("linked_pr_urls", []),
            "labels": data.get("labels", []),
            "flags": flags,
        }, indent=2),
        "```",
    ])
    return "\n".join(parts)


def main() -> int:
    rubric_path = REPO_ROOT / "backend" / "temporal" / "rubrics" / "actionability_v1.md"
    rubric = rubric_path.read_text(encoding="utf-8")

    # Optional --only filter for re-running specific issues after a fix
    only_filter = None
    if len(sys.argv) > 1 and sys.argv[1] == "--only":
        only_filter = sys.argv[2:]

    results = []
    targets = SMOKE_TARGETS
    if only_filter:
        targets = [t for t in SMOKE_TARGETS if t["upstream_slug"] in only_filter]
        print(f"Running only {[t['upstream_slug'] for t in targets]}")
    for target in targets:
        label = target["label"]
        print()
        print("=" * 78)
        print(f"  {label}")
        print("=" * 78)

        data = fetch_issue_data(target["upstream_slug"], target["issue_number"])
        if data.get("errors"):
            print(f"  ERRORS: {data['errors']}")
            results.append({**target, "verdict": "fetch_error", "errors": data["errors"]})
            continue

        flags = compute_flags(data)
        payload = build_payload(data, flags)
        print(f"  fetched: {len(data.get('comments', []))} comments, "
              f"{data.get('sub_issues', {}).get('count', 0)} sub-issues, "
              f"{len(data.get('recent_timeline_events', []))} recent timeline events, "
              f"flags={flags}")
        print(f"  payload size: {len(payload)} chars")

        try:
            result = score(rubric, payload)
            print(f"  → verdict: {result.verdict}  score: {result.score:.2f}")
            print(f"    reasoning: {result.reasoning[:200]}")
            evidence = result.raw.get("evidence", []) if isinstance(result.raw, dict) else []
            print(f"    evidence entries: {len(evidence)}")
            for e in evidence[:5]:
                sev = e.get("severity", "?")
                direction = e.get("direction", "?")
                sig = e.get("signal", "?")
                print(f"      - [{sev}/{direction}] {sig}: {(e.get('quote') or '')[:80]}")
            results.append({
                **target,
                "verdict": result.verdict,
                "score": result.score,
                "reasoning": result.reasoning,
                "evidence_count": len(evidence),
                "flags_computed": flags,
            })
        except JudgeUnreachable as e:
            print(f"  ! JudgeUnreachable: {e}")
            results.append({**target, "verdict": "judge_unreachable", "error": str(e)})
        except JudgeParseError as e:
            print(f"  ! JudgeParseError: {e}")
            results.append({**target, "verdict": "parse_error", "error": str(e)})

    # Final summary
    print()
    print("=" * 78)
    print("  SMOKE-TEST SUMMARY")
    print("=" * 78)
    for r in results:
        v = r.get("verdict", "?")
        s = r.get("score", "?")
        expected = r.get("expected_verdict", "?")
        print(f"  {v:8s}  score={s if isinstance(s, str) else f'{s:.2f}'}  expected={expected}  ← {r['label'][:55]}")

    out_path = REPO_ROOT / "smoke_actionability_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nFull results saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
