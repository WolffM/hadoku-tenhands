"""
Retrospective routes — batch tracking, log display, and issue reports.

Endpoints for retrospective data: batch summaries, full batch details,
PR commit history, and HTML issue reports.
"""

import json
import logging
import re
import time

from flask import jsonify, make_response, request

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..services import get_authenticated_user, OSSService, run_gh_command
    from ..services.oss_state import get_session_artifact
except ImportError:
    from services import get_authenticated_user, OSSService, run_gh_command
    from services.oss_state import get_session_artifact

_RETRO_CACHE_TTL = 30  # seconds — fast enough for dev, stale-safe for tests

_retro_batches_cache: dict = {}  # key "batches" → (timestamp, response_dict)
_retro_batch_cache: dict = {}    # batch_id → (timestamp, response_dict)


def _went_upstream(pr: dict) -> bool:
    """True if this record is an actual pull request on the upstream repo.

    `merged-in-fork-only` records share the shape of a submission — a state,
    a `submitted_at`, a `merged_at` — but carry no PR number and no URL,
    because the work landed in our fork and was never offered upstream.
    Counting one as an upstream PR overstates the funnel and puts a dead link
    on the card.
    """
    return bool(pr.get("pr_number")) and bool(pr.get("pr_url"))


def _pick_upstream_pr(submitted_prs: list[dict], origin_slug: str,
                      issue_number) -> dict | None:
    """The upstream PR to show for one issue, out of every record it has.

    An issue can accumulate several records: a PR that was closed and a
    second attempt, or a real PR plus a later fork-only bookkeeping entry.
    Two rules, both learned from `state/` rather than guessed:

    1. **A real upstream PR beats a fork-only record.** markitdown#183 has
       PR #1619 (open) *and* a later `merged-in-fork-only` row; showing the
       latter hid a live upstream PR behind "no upstream PR".
    2. **Newest by `submitted_at`, not by file order.** These records are not
       appended chronologically — PowerToys#22315 has the newer open #46315
       at index 1 and the older closed #46124 at index 26 — so picking the
       last match in list order showed a stale, closed PR as the outcome.
    """
    mine = [p for p in submitted_prs
            if p.get("origin_slug") == origin_slug
            and p.get("issue_number") == issue_number]
    if not mine:
        return None
    # `submitted_at` is an ISO 8601 UTC string, so lexical ordering is
    # chronological; a missing one sorts last rather than crashing.
    return sorted(
        mine,
        key=lambda p: (_went_upstream(p), p.get("submitted_at") or ""),
        reverse=True,
    )[0]


@bp.route("/api/oss/retrospective-logs", methods=["GET"])
def api_oss_retrospective_logs():
    """Get all retrospective log entries for pipeline report display.

    Returns raw retrospective data (snake_case) matching the structure
    used by pipeline-report.html and gen_report.py.
    """
    my_user = get_authenticated_user()
    svc = OSSService()
    logs = svc.get_retrospective_logs()
    return jsonify({"success": True, "logs": logs, "owner": my_user})


@bp.route("/api/oss/retro/batches", methods=["GET"])
def api_oss_retro_batches():
    """List all batches with funnel summary counts.

    Returns { success, owner, batches: [BatchSummary] }.
    Response is cached for 30 s to avoid repeated file reads during serial E2E runs.
    """
    cached = _retro_batches_cache.get("batches")
    if cached and (time.time() - cached[0]) < _RETRO_CACHE_TTL:
        return jsonify(cached[1])

    my_user = get_authenticated_user()
    svc = OSSService()
    batches_raw = svc.get_batches()
    submitted_prs = svc.get_submitted_prs()
    assignments = svc.get_assigned_issues()

    summaries = []
    for batch in batches_raw:
        batch_id = batch.get("batch_id")
        issue_refs = batch.get("issues", [])
        issue_count = len(issue_refs)

        # Build set of origin_slug#issue_number refs in this batch.
        # For pre-tracking batches with no assignments, fall back to batch.issues list.
        batch_assignments = [
            a for a in assignments if a.get("batch_id") == batch_id
        ]
        if batch_assignments:
            batch_slugs_issues = {
                (a.get("origin_slug"), a.get("issue_number"))
                for a in batch_assignments
            }
        else:
            batch_slugs_issues = set()
            for ref in issue_refs:
                m = re.match(r"^(.+)#(\d+)$", ref)
                if m:
                    batch_slugs_issues.add((m.group(1), int(m.group(2))))

        # Count upstream PRs for issues in this batch. Fork-only records are
        # excluded on purpose: the funnel stage is "Upstream PRs", and work
        # that never left our fork did not reach it. Counting them made
        # jade-hare read 30 upstream PRs whose outcomes only ever summed to 28.
        batch_prs = [
            p for p in submitted_prs
            if (p.get("origin_slug"), p.get("issue_number")) in batch_slugs_issues
            and _went_upstream(p)
        ]

        summaries.append({
            "batch_id": batch_id,
            "created_at": batch.get("created_at"),
            "note": batch.get("note", ""),
            "issue_count": issue_count,
            "upstream_pr_count": len(batch_prs),
            "upstream_merged": sum(1 for p in batch_prs if p.get("state") == "merged"),
            "upstream_closed": sum(1 for p in batch_prs if p.get("state") == "closed"),
            "upstream_open": sum(1 for p in batch_prs if p.get("state") == "open"),
            "has_fork_pr": sum(1 for a in batch_assignments if a.get("stage4_pr_number")),
        })

    result = {"success": True, "owner": my_user, "batches": summaries}
    _retro_batches_cache["batches"] = (time.time(), result)
    return jsonify(result)


@bp.route("/api/oss/retro/batch/<batch_id>", methods=["GET"])
def api_oss_retro_batch(batch_id):
    """Full batch detail: assignments + submitted PRs + retro logs.

    Returns { success, owner, batch, issues: [BatchIssue] }.
    Response is cached for 30 s (avoids hammering file I/O during serial E2E runs).
    """
    cached = _retro_batch_cache.get(batch_id)
    if cached and (time.time() - cached[0]) < _RETRO_CACHE_TTL:
        return jsonify(cached[1])

    my_user = get_authenticated_user()
    svc = OSSService()

    batch = svc.get_batch(batch_id)
    if not batch:
        return jsonify({"success": False, "error": f"Batch '{batch_id}' not found"})

    assignments = svc.get_assigned_issues()
    submitted_prs = svc.get_submitted_prs()
    retro_logs = svc.get_retrospective_logs()

    batch_assignments = [a for a in assignments if a.get("batch_id") == batch_id]

    # For pre-tracking batches with no assignments, build stub entries from batch.issues list.
    # Format: "owner/repo#N"
    if not batch_assignments:
        for ref in batch.get("issues", []):
            m = re.match(r"^(.+)#(\d+)$", ref)
            if not m:
                continue
            batch_assignments.append({
                "origin_slug": m.group(1),
                "issue_number": int(m.group(2)),
                "batch_id": batch_id,
                "pre_tracking": True,
            })

    issues = []
    for assignment in batch_assignments:
        origin_slug = assignment.get("origin_slug")
        issue_number = assignment.get("issue_number")

        upstream_pr = _pick_upstream_pr(submitted_prs, origin_slug, issue_number)

        # Find most recent retro log for this issue
        retro = next(
            (r for r in reversed(retro_logs)
             if r.get("origin_slug") == origin_slug
             and r.get("issue_number") == issue_number),
            {}
        )

        # Enrich retro with session artifacts (comments, PR body, context)
        retro = dict(retro)  # copy so we don't mutate the original

        # PR comments — upstream first, fall back to fork PR comments
        upstream_comments_json = get_session_artifact(origin_slug, issue_number, "upstream-pr-comments.json")
        fork_comments_json = get_session_artifact(origin_slug, issue_number, "fork-pr-comments.json")
        try:
            upstream_comments = json.loads(upstream_comments_json) if upstream_comments_json else []
        except (ValueError, TypeError):
            upstream_comments = []
        try:
            fork_comments = json.loads(fork_comments_json) if fork_comments_json else []
        except (ValueError, TypeError):
            fork_comments = []
        if upstream_comments or fork_comments:
            retro["raw_comments"] = {"upstream_pr": upstream_comments, "fork_pr": fork_comments}

        # Upstream PR body
        upstream_pr_body = get_session_artifact(origin_slug, issue_number, "upstream-pr-body.md")
        if upstream_pr_body:
            retro["upstream_pr_body"] = upstream_pr_body

        # Context issue body (fork issue)
        context_body = get_session_artifact(origin_slug, issue_number, "context.md")
        if context_body:
            retro["context_issue_body"] = context_body

        # Copilot workflow analysis (pre-computed by batch scrape)
        workflow_json = get_session_artifact(origin_slug, issue_number, "workflow.json")
        if workflow_json:
            try:
                retro["workflow"] = json.loads(workflow_json)
            except (ValueError, TypeError):
                pass

        # Cross-reference leaks — fork PRs that triggered mentions on the upstream issue
        mentions_json = get_session_artifact(origin_slug, issue_number, "upstream-issue-mentions.json")
        if mentions_json:
            try:
                retro["upstream_issue_mentions"] = json.loads(mentions_json)
            except (ValueError, TypeError):
                pass

        issues.append({
            "assignment": assignment,
            "upstream_pr": upstream_pr,
            "retro": retro,
        })

    result = {
        "success": True,
        "owner": my_user,
        "batch": batch,
        "issues": issues,
    }
    _retro_batch_cache[batch_id] = (time.time(), result)
    return jsonify(result)


@bp.route("/api/oss/retro/pr-commits/<path:origin_slug>/<int:pr_number>", methods=["GET"])
def api_oss_retro_pr_commits(origin_slug, pr_number):
    """Fetch post-submission commits for an upstream PR.

    Returns { success, commits: [{sha, date, author, message}] } sorted by date asc.
    Only returns commits pushed after the PR was created (i.e. follow-up fix commits).
    """
    submitted_after = request.args.get("submitted_after", "")

    result = run_gh_command([
        "api",
        f"repos/{origin_slug}/pulls/{pr_number}/commits",
        "--jq",
        '[.[] | {sha: .sha[:7], date: .commit.author.date, '
        'author: (.author.login // .commit.author.name), '
        'message: (.commit.message | split("\\n")[0])}]',
    ], timeout=15)

    if not result["success"]:
        logger.warning("Failed to fetch PR commits for %s#%d: %s", origin_slug, pr_number, result.get("error"))
        return jsonify({"success": True, "commits": []})

    try:
        commits = json.loads(result["output"])
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse PR commits for %s#%d: %s", origin_slug, pr_number, exc)
        return jsonify({"success": True, "commits": []})

    if submitted_after:
        commits = [c for c in commits if c["date"] > submitted_after]
    return jsonify({"success": True, "commits": commits})


@bp.route("/api/oss/issue-report/<repo>/<int:issue_number>", methods=["GET"])
def api_oss_issue_report(repo, issue_number):
    """Generate a self-contained pipeline report HTML for a single issue.

    Returns Content-Type: text/html suitable for embedding in an iframe.
    """
    try:
        from ..helpers.report_generator import generate_issue_report_html
    except ImportError:
        from helpers.report_generator import generate_issue_report_html

    svc = OSSService()
    try:
        html = generate_issue_report_html(svc, repo, issue_number)
    except Exception as exc:
        logger.exception("Failed to generate issue report for %s#%d", repo, issue_number)
        return jsonify({"success": False, "error": str(exc)}), 500

    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response
