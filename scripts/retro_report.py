#!/usr/bin/env python3
"""Retrospective report for tenhands pipeline.

Reads from the same API endpoints as the UI:
  GET /tenhands/api/oss/retro/batches
  GET /tenhands/api/oss/retro/batch/<batch_id>

Usage:
  python3 scripts/retro_report.py --pr owner/repo#N [--batch BATCH] [--full]
  python3 scripts/retro_report.py --batch jade-hare [--full]

Options:
  --pr owner/repo#N    Single issue report (find across batches)
  --batch BATCH        Batch report, or scope --pr lookup to a specific batch
  --full               Show full context brief and upstream PR body (default: truncated)
  --port PORT          Backend port (default: 5024, or TENHANDS_PORT env var)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

import requests

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_PORT = os.environ.get("TENHANDS_PORT", "5024")
URL_PREFIX = "/tenhands"

# Import bot filter from backend helpers
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
try:
    from helpers.bot_filter import BOT_LOGINS as _BOT_LOGINS, is_bot as _is_bot
except ImportError:
    # Fallback if running outside the repo structure
    _BOT_LOGINS = set()
    def _is_bot(login: str) -> bool:
        return not login or login.lower().endswith("[bot]")

TRUNCATE_BODY = 500  # chars shown in non-full mode


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(base_url: str, path: str) -> dict:
    url = f"{base_url}{URL_PREFIX}/api/oss{path}"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        print(f"ERROR: could not reach backend at {url}\n  {exc}", file=sys.stderr)
        sys.exit(1)


def fetch_batches(base_url: str) -> list:
    data = _get(base_url, "/retro/batches")
    return data.get("batches", [])


def fetch_batch_detail(base_url: str, batch_id: str) -> dict:
    return _get(base_url, f"/retro/batch/{batch_id}")


# ── GitHub helpers ───────────────────────────────────────────────────────────

def fetch_pr_commits(origin_slug: str, pr_number: int) -> list:
    """Fetch commits for an upstream PR via gh CLI.

    Returns list of {sha, date, author, message} dicts, sorted by date asc.
    Returns [] silently if gh CLI is unavailable or the call fails.
    """
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{origin_slug}/pulls/{pr_number}/commits",
             "--jq", '[.[] | {sha: .sha[:7], date: .commit.author.date, author: (.author.login // .commit.author.name), message: (.commit.message | split("\n")[0])}]'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        return []


# ── Bot filter ────────────────────────────────────────────────────────────────

def _human_comments(comments: list) -> list:
    return [c for c in comments if not _is_bot(c.get("author", ""))]


# ── Formatting helpers ────────────────────────────────────────────────────────

W = 80  # terminal width


def _hr(label: str = "") -> str:
    if label:
        fill = W - len(label) - 5
        return f"── {label} {'─' * max(fill, 2)}"
    return "─" * W


def _header(label: str) -> str:
    fill = W - len(label) - 6
    return f"━━━ {label} {'━' * max(fill, 2)}"


def _fmt_ts(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, AttributeError):
        return ts


def _delta(ts1: str | None, ts2: str | None) -> str:
    """Human-readable delta between two ISO timestamps."""
    if not ts1 or not ts2:
        return ""
    try:
        def _parse(ts):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        diff = abs((_parse(ts2) - _parse(ts1)).total_seconds())
        if diff < 60:
            return f"+{int(diff)}s"
        if diff < 3600:
            return f"+{int(diff/60)}m"
        h = int(diff / 3600)
        m = int((diff % 3600) / 60)
        return f"+{h}h {m}m" if m else f"+{h}h"
    except (ValueError, AttributeError):
        return ""


def _truncate(text: str | None, limit: int = TRUNCATE_BODY) -> tuple[str, bool]:
    """Return (text, was_truncated)."""
    if not text:
        return "", False
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip() + " …", True


def _extract_rule(msg: str) -> str:
    """Extract the rule code from a SA annotation message.

    Messages typically look like:
      "path/to/file.py:119:5: F601 Dictionary key literal ..."
      "path/to/file.js:42: prefer-const Use const ..."
    The first space-separated token AFTER the path:line:col: prefix is the rule.
    """
    if not msg:
        return "?"
    # Strip leading "path:line:col:" or "path:line:" prefix(es).
    rest = msg
    while ":" in rest.split(" ", 1)[0]:
        head, _, tail = rest.partition(": ")
        if not tail:
            break
        rest = tail
    return rest.split()[0] if rest else "?"


def _stage_label(assignment: dict, upstream_pr: dict | None) -> str:
    if upstream_pr:
        state = upstream_pr.get("state", "")
        if state == "merged":
            return "upstream-merged"
        if state == "closed":
            return "upstream-closed"
        return "upstream-open"
    if assignment.get("stage4_pr_number"):
        return "fork-pr"
    return "dispatched"


# ── Single-PR report ──────────────────────────────────────────────────────────

def print_pr_report(issue: dict, full: bool = False) -> None:
    assignment = issue.get("assignment", {})
    upstream_pr = issue.get("upstream_pr")
    retro = issue.get("retro", {})

    origin_slug = assignment.get("origin_slug", "?")
    issue_num = assignment.get("issue_number", "?")
    batch_id = assignment.get("batch_id", "?")

    # Human comments
    raw = retro.get("raw_comments", {})
    fork_humans = _human_comments(raw.get("fork_pr", []))
    upstream_humans = _human_comments(raw.get("upstream_pr", []))
    total_humans = len(fork_humans) + len(upstream_humans)

    # SA annotations — nested under retro.static_analysis.jobs[].annotations
    sa = retro.get("static_analysis", {})
    all_annotations = []
    for job in sa.get("jobs", []):
        all_annotations.extend(job.get("annotations", []))

    # Context tier
    dq = retro.get("data_quality", {})
    tier = dq.get("context_tier")
    tier_label = f"tier-{tier}" if tier else "unknown"

    # Stage
    stage = _stage_label(assignment, upstream_pr)

    print()
    print(_header(f"{origin_slug}#{issue_num}  ·  {batch_id}"))
    print()
    human_badge = f"💬 {total_humans} human comment{'s' if total_humans != 1 else ''}"
    sa_badge = f"SA: {len(all_annotations)} annotation{'s' if len(all_annotations) != 1 else ''}"
    print(f"  Stage:    {stage:<22}  Context:  {tier_label}")
    print(f"  {human_badge:<28}  {sa_badge}")

    # ── Timeline ──────────────────────────────────────────────────────────────
    timing = retro.get("timing", {})
    t_assigned    = timing.get("assigned_at")
    t_swe         = timing.get("swe_done_at")
    t_sa          = timing.get("sa_done_at")
    t_review      = timing.get("review_done_at")
    t_remediation = timing.get("remediation_done_at")
    t_completed   = timing.get("completed_at")
    t_submitted   = (upstream_pr or {}).get("submitted_at")

    # Fetch post-submission commits from GitHub
    post_commits = []
    if upstream_pr and t_submitted:
        pr_num = upstream_pr.get("pr_number")
        all_commits = fetch_pr_commits(origin_slug, pr_num)
        post_commits = [c for c in all_commits if c["date"] > t_submitted]

    if any([t_assigned, t_swe, t_sa]):
        print()
        print(_hr("Timeline"))
        steps = [
            ("assigned",    t_assigned,    None),
            ("swe-done",    t_swe,         t_assigned),
            ("sa-done",     t_sa,          t_swe),
            ("review-done", t_review,      t_sa),
            ("remediation", t_remediation, t_review),
            ("submitted",   t_submitted,   t_remediation or t_completed),
        ]
        prev_ts = t_submitted or t_completed
        for label, ts, prev in steps:
            if not ts:
                continue
            delta = _delta(prev, ts) if prev else ""
            delta_str = f"  ({delta})" if delta else ""
            print(f"  {label:<14}  {_fmt_ts(ts)}{delta_str}")

        for commit in post_commits:
            delta = _delta(prev_ts, commit["date"]) if prev_ts else ""
            delta_str = f"  ({delta})" if delta else ""
            author = commit.get("author", "")
            msg = commit.get("message", "")[:60]
            sha = commit.get("sha", "")
            author_str = f" @{author}" if author else ""
            print(f"  {'commit':<14}  {_fmt_ts(commit['date'])}{delta_str}")
            print(f"  {'':14}  {sha}  \"{msg}\"{author_str}")
            prev_ts = commit["date"]

    # ── Upstream PR ───────────────────────────────────────────────────────────
    print()
    print(_hr("Upstream PR"))
    if upstream_pr:
        pr_num = upstream_pr.get("pr_number")
        state = upstream_pr.get("state", "?")
        pr_url = upstream_pr.get("pr_url", "")
        merged_at = upstream_pr.get("merged_at")
        line = f"  #{pr_num} ({state})"
        if merged_at:
            line += f"  merged {_fmt_ts(merged_at)}"
        if pr_url:
            line += f"  {pr_url}"
        print(line)
    elif assignment.get("stage4_pr_number"):
        print(f"  fork PR #{assignment['stage4_pr_number']} only — not yet submitted upstream")
    else:
        print("  no PR yet")

    # ── Human Comments ────────────────────────────────────────────────────────
    print()
    print(_hr("Human Comments"))
    if not total_humans:
        print("  (none)")
    else:
        for thread_label, comments in [("fork PR", fork_humans), ("upstream PR", upstream_humans)]:
            if not comments:
                continue
            print(f"  ── {thread_label} ──")
            for c in comments:
                author = c.get("author", "?")
                body = c.get("body", "").strip()
                ts = _fmt_ts(c.get("created_at"))
                comment_type = c.get("comment_type", "")
                prefix = ""
                if comment_type == "inline":
                    path = c.get("path", "")
                    line_no = c.get("line", "")
                    prefix = f"  [{path}:{line_no}]" if path else "  [inline]"
                print(f"  @{author}  ·  {ts}{prefix}")
                if full:
                    for line in body.splitlines():
                        print(f"    {line}")
                else:
                    preview = body[:200].replace("\n", " ")
                    if len(body) > 200:
                        preview += " …"
                    print(f"    {preview}")
                print()

    # ── Cross-Reference Leaks ─────────────────────────────────────────────────
    mentions = retro.get("upstream_issue_mentions") or []
    if mentions:
        print(_hr("Cross-Reference Leaks"))
        for m in mentions:
            actor = m.get("actor", "?")
            ts = _fmt_ts(m.get("created_at"))[:10]
            src_url = m.get("source_url", "?")
            src_title = m.get("source_title", "")
            src_type = m.get("source_type", "?")
            print(f"  ✗ by @{actor} on {ts} via {src_type}")
            print(f"    {src_url}")
            if src_title:
                print(f"    title: \"{src_title[:90]}\"")
        print()

    # ── SA Findings ───────────────────────────────────────────────────────────
    print(_hr("SA Findings"))
    job_lines = []
    for job in sa.get("jobs", []):
        name = job.get("name", "?")
        conclusion = job.get("conclusion", "?")
        ann_count = len(job.get("annotations", []))
        job_lines.append(f"  {name}: {conclusion}" + (f"  ({ann_count} findings)" if ann_count else ""))
    if job_lines:
        for line in job_lines:
            print(line)
    if not all_annotations:
        if not job_lines:
            print("  (no SA jobs)")
    else:
        print()
        for ann in all_annotations:
            level = (ann.get("level") or ann.get("annotation_level") or "note").upper()
            path = ann.get("path", "")
            line_no = ann.get("line") or ann.get("start_line") or ann.get("end_line") or ""
            msg = ann.get("message", "").replace("\n", " ")
            rule = _extract_rule(msg)
            loc = f"{path}:{line_no}" if line_no else path
            print(f"  {level:<8}  {rule:<14}  {loc:<40}  {msg[:80]}")
    print()

    # ── Copilot Workflow ──────────────────────────────────────────────────────
    workflow = retro.get("workflow", {})
    if workflow:
        print(_hr("Copilot Workflow"))
        flags = []
        for key in ("reproduced", "verified", "code_review", "self_corrected", "tool_installed", "codeql"):
            val = workflow.get(key)
            if val is not None:
                icon = "✓" if val else "✗"
                flags.append(f"{key}: {icon}")
        step_count = workflow.get("step_count")
        if step_count is not None:
            flags.insert(0, f"steps: {step_count}")
        print("  " + "   ".join(flags))
        print()

    # ── Upstream PR Body ──────────────────────────────────────────────────────
    pr_body = retro.get("upstream_pr_body")
    if pr_body:
        print(_hr("Upstream PR Body"))
        text, truncated = _truncate(pr_body) if not full else (pr_body, False)
        for line in text.splitlines():
            print(f"  {line}")
        if truncated:
            print("  [use --full to see complete body]")
        print()

    # ── Context Brief ─────────────────────────────────────────────────────────
    context = retro.get("context_issue_body")
    if context:
        print(_hr("Context Brief"))
        text, truncated = _truncate(context, 800) if not full else (context, False)
        for line in text.splitlines():
            print(f"  {line}")
        if truncated:
            print("  [use --full to see complete brief]")
        print()


# ── Batch report ──────────────────────────────────────────────────────────────

def print_batch_report(data: dict, full: bool = False) -> None:
    batch = data.get("batch", {})
    issues = data.get("issues", [])

    batch_id = batch.get("batch_id", "?")
    created_at = batch.get("created_at", "")
    note = batch.get("note", "")

    # Funnel counts
    total = len(issues)
    fork_prs = sum(1 for i in issues if i.get("assignment", {}).get("stage4_pr_number"))
    upstream_total = sum(1 for i in issues if i.get("upstream_pr"))
    upstream_merged = sum(1 for i in issues if (i.get("upstream_pr") or {}).get("state") == "merged")
    upstream_closed = sum(1 for i in issues if (i.get("upstream_pr") or {}).get("state") == "closed")
    upstream_open = sum(1 for i in issues if (i.get("upstream_pr") or {}).get("state") == "open")

    date_str = created_at[:10] if created_at else "?"
    print()
    print(_header(f"{batch_id}  ·  {date_str}"))
    if note:
        print(f"  {note}")
    print()
    print(f"  Dispatched: {total}  |  Fork PRs: {fork_prs}  |  Upstream PRs: {upstream_total}")
    print(f"  Merged: {upstream_merged}  |  Open: {upstream_open}  |  Closed: {upstream_closed}")

    # ── Human Feedback Digest ─────────────────────────────────────────────────
    print()
    print(_hr("Human Feedback Digest"))

    # Group comments by repo slug
    comments_by_slug: dict[str, list] = {}
    for issue in issues:
        assignment = issue.get("assignment", {})
        slug = assignment.get("origin_slug", "?")
        retro = issue.get("retro", {})
        raw = retro.get("raw_comments", {})
        all_comments = (
            _human_comments(raw.get("fork_pr", []))
            + _human_comments(raw.get("upstream_pr", []))
        )
        if all_comments:
            comments_by_slug.setdefault(slug, []).extend(all_comments)

    if not comments_by_slug:
        print("  (no human comments recorded)")
    else:
        # Sort by comment count desc
        for slug, comments in sorted(comments_by_slug.items(), key=lambda x: -len(x[1])):
            print(f"\n  {slug} ({len(comments)} comment{'s' if len(comments) != 1 else ''})")
            for c in comments:
                author = c.get("author", "?")
                ts = _fmt_ts(c.get("created_at"))[:10]  # date only
                body = c.get("body", "").strip().replace("\n", " ")
                preview, _ = _truncate(body, 120) if not full else (body, False)
                comment_type = c.get("comment_type", "")
                suffix = ""
                if comment_type == "inline":
                    path = c.get("path", "")
                    line_no = c.get("line", "")
                    suffix = f" [{path}:{line_no}]" if path else " [inline]"
                print(f"    @{author}  ·  {ts}{suffix}")
                print(f"    \"{preview}\"")

    # ── Cross-Reference Leaks ─────────────────────────────────────────────────
    print()
    print(_hr("Cross-Reference Leaks"))
    leaks = []
    for issue in issues:
        a = issue.get("assignment", {})
        mentions = issue.get("retro", {}).get("upstream_issue_mentions") or []
        for m in mentions:
            leaks.append((a.get("origin_slug", "?"), a.get("issue_number", "?"), m))
    if not leaks:
        print("  (none detected)")
    else:
        print(f"  {len(leaks)} leak(s) across {len({(s,n) for s,n,_ in leaks})} upstream issue(s)")
        print()
        for slug, num, m in leaks:
            actor = m.get("actor", "?")
            ts = _fmt_ts(m.get("created_at"))[:10]
            src_url = m.get("source_url", "?")
            src_title = m.get("source_title", "")
            src_type = m.get("source_type", "?")
            print(f"  ✗ {slug}#{num}")
            print(f"      by @{actor} on {ts} via {src_type}")
            print(f"      {src_url}")
            if src_title:
                title_preview = src_title[:90] + (" …" if len(src_title) > 90 else "")
                print(f"      title: \"{title_preview}\"")
            print()

    # ── SA Patterns ───────────────────────────────────────────────────────────
    print()
    print(_hr("SA Patterns"))

    # Job-level: count distinct issues where each (tool, conclusion) appeared.
    job_outcomes: dict[tuple[str, str], int] = {}
    issues_with_sa = 0
    issues_without_sa = 0

    # Rule-level: count individual annotations and remember severity.
    rule_counts: dict[str, int] = {}
    rule_levels: dict[str, str] = {}

    for issue in issues:
        retro = issue.get("retro", {})
        sa = retro.get("static_analysis", {})
        jobs = sa.get("jobs", [])
        if jobs:
            issues_with_sa += 1
        else:
            issues_without_sa += 1
        for job in jobs:
            tool = job.get("name", "?")
            conclusion = job.get("conclusion", "?")
            job_outcomes[(tool, conclusion)] = job_outcomes.get((tool, conclusion), 0) + 1
            for ann in job.get("annotations", []):
                msg = ann.get("message", "")
                level = (ann.get("level") or ann.get("annotation_level") or "note").upper()
                rule = _extract_rule(msg)
                rule_counts[rule] = rule_counts.get(rule, 0) + 1
                # Keep most severe level seen for this rule.
                if level == "FAILURE" or rule not in rule_levels:
                    rule_levels[rule] = level

    print(f"  SA coverage: {issues_with_sa} issues with SA, {issues_without_sa} without")
    print()

    if not job_outcomes:
        print("  (no SA jobs)")
    else:
        print("  Job conclusions (issue count):")
        for (tool, conclusion), count in sorted(job_outcomes.items(), key=lambda x: (-x[1], x[0])):
            marker = "✗" if conclusion == "failure" else ("✓" if conclusion == "success" else "·")
            print(f"    {marker} {tool}: {conclusion:<10}  ×{count}")

    if rule_counts:
        print()
        print("  Top rule codes (annotation count):")
        for rule, count in sorted(rule_counts.items(), key=lambda x: -x[1])[:15]:
            level = rule_levels.get(rule, "")
            print(f"    {rule:<20}  ×{count:<4}  {level}")

    # ── Per-issue Summary ─────────────────────────────────────────────────────
    print()
    print(_hr("Per-issue Summary"))
    print()

    for issue in issues:
        assignment = issue.get("assignment", {})
        upstream_pr = issue.get("upstream_pr")
        retro = issue.get("retro", {})

        slug = assignment.get("origin_slug", "?")
        issue_num = assignment.get("issue_number", "?")
        ref = f"{slug}#{issue_num}"

        raw = retro.get("raw_comments", {})
        human_count = len(_human_comments(raw.get("fork_pr", []))) + len(_human_comments(raw.get("upstream_pr", [])))
        comment_badge = f"💬 {human_count}" if human_count else "   "

        dq = retro.get("data_quality", {})
        tier = dq.get("context_tier")
        tier_label = f"tier-{tier}" if tier else "   —  "

        stage = _stage_label(assignment, upstream_pr)
        if stage == "upstream-merged":
            icon = "✓✓"
        elif stage == "upstream-open":
            icon = "✓ "
        elif stage == "upstream-closed":
            icon = "✗ "
        elif stage == "fork-pr":
            icon = "~ "
        else:
            icon = "· "

        if upstream_pr:
            pr_num = upstream_pr.get("pr_number", "?")
            state = upstream_pr.get("state", "?")
            pr_info = f"→  PR#{pr_num} ({state})"
        elif assignment.get("stage4_pr_number"):
            pr_info = f"→  fork PR#{assignment['stage4_pr_number']}"
        else:
            pr_info = "→  no PR"

        print(f"  {icon}  {ref:<42}  {pr_info:<26}  {comment_badge:<8}  {tier_label}")

    print()


# ── Search helpers ────────────────────────────────────────────────────────────

def find_issue(base_url: str, origin_slug: str, issue_number: int, batch_hint: str | None) -> tuple[dict, str] | None:
    """Search batches for an issue. Returns (issue_data, batch_id) or None."""
    batches = fetch_batches(base_url)
    if not batches:
        print("No batches found.", file=sys.stderr)
        return None

    # If batch_hint given, search that one first
    if batch_hint:
        ordered = [b for b in batches if b["batch_id"] == batch_hint]
        ordered += [b for b in batches if b["batch_id"] != batch_hint]
    else:
        ordered = batches  # most recent first (server order)

    for batch_summary in ordered:
        batch_id = batch_summary["batch_id"]
        detail = fetch_batch_detail(base_url, batch_id)
        for issue in detail.get("issues", []):
            a = issue.get("assignment", {})
            if a.get("origin_slug") == origin_slug and a.get("issue_number") == issue_number:
                return issue, batch_id

    return None


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Retrospective report for tenhands pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--pr", metavar="owner/repo#N",
                        help="Single issue report (e.g. microsoft/markitdown#183)")
    parser.add_argument("--batch", metavar="BATCH",
                        help="Batch report (e.g. jade-hare), or scope --pr lookup")
    parser.add_argument("--full", action="store_true",
                        help="Show full context brief and upstream PR body")
    parser.add_argument("--port", default=DEFAULT_PORT,
                        help=f"Backend port (default: {DEFAULT_PORT})")
    args = parser.parse_args()

    if not args.pr and not args.batch:
        parser.print_help()
        sys.exit(1)

    base_url = f"http://localhost:{args.port}"

    if args.pr and not args.batch:
        # Single PR report — search all batches
        m = re.match(r"^([^#]+)#(\d+)$", args.pr)
        if not m:
            print(f"ERROR: --pr must be in format owner/repo#N (got: {args.pr!r})", file=sys.stderr)
            sys.exit(1)
        origin_slug = m.group(1)
        issue_number = int(m.group(2))

        result = find_issue(base_url, origin_slug, issue_number, None)
        if not result:
            print(f"Issue {origin_slug}#{issue_number} not found in any batch.", file=sys.stderr)
            sys.exit(1)
        issue, batch_id = result
        print_pr_report(issue, full=args.full)

    elif args.pr and args.batch:
        # PR report, scoped to a specific batch
        m = re.match(r"^([^#]+)#(\d+)$", args.pr)
        if not m:
            print(f"ERROR: --pr must be in format owner/repo#N (got: {args.pr!r})", file=sys.stderr)
            sys.exit(1)
        origin_slug = m.group(1)
        issue_number = int(m.group(2))

        result = find_issue(base_url, origin_slug, issue_number, args.batch)
        if not result:
            print(f"Issue {origin_slug}#{issue_number} not found in batch '{args.batch}'.", file=sys.stderr)
            sys.exit(1)
        issue, _ = result
        print_pr_report(issue, full=args.full)

    else:
        # Batch report
        detail = fetch_batch_detail(base_url, args.batch)
        if not detail.get("success"):
            error = detail.get("error", "unknown error")
            print(f"ERROR: {error}", file=sys.stderr)
            sys.exit(1)
        print_batch_report(detail, full=args.full)


if __name__ == "__main__":
    main()
