"""Pipeline retrospective — collect structured metrics for a pipeline run.

Module-level function that gathers per-stage metrics, session artifacts,
and timing data into a retrospective dict for persistence.
"""

import json
import logging
import time

try:
    from services.github_api import run_gh_command
    from services.oss_state import save_session_artifact
    from services.pipeline_session_analysis import (
        fetch_workflow_analysis,
        fetch_session_log,
        fetch_fork_diff,
    )
except ImportError:
    from github_api import run_gh_command
    from oss_state import save_session_artifact
    from pipeline_session_analysis import (
        fetch_workflow_analysis,
        fetch_session_log,
        fetch_fork_diff,
    )

logger = logging.getLogger(__name__)


def fetch_sa_details(run_id, fork_slug):
    """Fetch per-job conclusions and annotations for a SA workflow run.

    Called at retrospective write time so the data is captured once and
    persisted in retrospective-logs.json for later report rendering.

    Args:
        run_id: GitHub Actions workflow run ID.
        fork_slug: Fork repo slug (e.g. "user/some-repo").

    Returns:
        list of job dicts [{name, conclusion, annotations: [{path, line, level, message}]}],
        or empty list on failure.
    """
    if not run_id or not fork_slug:
        return []

    _jobs_result = run_gh_command([
        "api", f"repos/{fork_slug}/actions/runs/{run_id}/jobs",
        "--jq", ".jobs",
    ])
    try:
        jobs_data = json.loads(_jobs_result["output"]) if _jobs_result["success"] else None
    except (json.JSONDecodeError, KeyError, TypeError):
        jobs_data = None
    if not jobs_data or not isinstance(jobs_data, list):
        return []

    jobs = []
    for job in jobs_data:
        job_info = {
            "name": job.get("name", "unknown"),
            "conclusion": job.get("conclusion", "unknown"),
        }
        _ann_result = run_gh_command([
            "api", f"repos/{fork_slug}/check-runs/{job['id']}/annotations",
        ])
        try:
            annotations = json.loads(_ann_result["output"]) if _ann_result["success"] else None
        except (json.JSONDecodeError, KeyError, TypeError):
            annotations = None
        if annotations:
            findings = [
                {
                    "path": a.get("path", ""),
                    "line": a.get("start_line", 0),
                    "level": a.get("annotation_level", ""),
                    "message": a.get("message", ""),
                }
                for a in annotations
                if a.get("path", "") != ".github"
            ]
            job_info["annotations"] = findings
        else:
            job_info["annotations"] = []
        jobs.append(job_info)

    return jobs


def collect_retrospective(
    assignment,
    ctx,
    dispatchers,
    count_inline_comments_fn,
    fetch_workflow_analysis_fn=None,
):
    """Gather structured metrics for the pipeline run.

    Args:
        assignment: Assignment dict.
        ctx: Runtime context dict with my_user, etc.
        dispatchers: Dict of dispatcher instances keyed by stage name.
        count_inline_comments_fn: Callable(assignment, ctx) -> int.
        fetch_workflow_analysis_fn: Optional override for workflow analysis
            (used in tests via patch.object on the orchestrator class).
            Defaults to the module-level fetch_workflow_analysis.
    """
    if fetch_workflow_analysis_fn is None:
        fetch_workflow_analysis_fn = fetch_workflow_analysis

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    repo = assignment.get("repo", "")
    fork_issue = assignment.get("fork_issue_number", 0)
    pr_number = assignment.get("stage4_pr_number")

    retro = {
        "id": f"{repo}/{fork_issue}/{now}",
        "created_at": now,
        "origin_slug": assignment.get("origin_slug", ""),
        "repo": repo,
        "issue_number": assignment.get("issue_number"),
        "fork_issue_number": fork_issue,
    }

    # Pipeline configuration — what model/dispatcher/tools ran each stage
    retro["pipeline"] = {
        "swe_agent": type(dispatchers.get("swe", None)).__name__,
        "static_analysis": type(
            dispatchers.get("static_analysis", None)).__name__,
        "review_agent": type(dispatchers.get("review", None)).__name__,
        "remediation_agent": type(
            dispatchers.get("remediation", None)).__name__,
        "language": assignment.get("language"),
        "toolchain_profile": assignment.get("toolchain_profile"),
    }

    # SWE metrics
    swe_data = {"pr_number": pr_number,
                "pr_branch": assignment.get("stage4_pr_branch")}
    if pr_number and dispatchers.get("swe"):
        swe_results = dispatchers["swe"].collect_results(
            str(fork_issue), ctx)
        if swe_results.get("success"):
            swe_data.update(swe_results["outputs"])
    retro["swe"] = swe_data

    # SA metrics — fetch per-job details at write time so they're
    # persisted in retrospective-logs.json for report rendering
    sa_run_id = assignment.get("stage4_sa_run_id")
    fork_slug = f"{ctx.get('my_user', '')}/{repo}" if repo else None
    sa_jobs = fetch_sa_details(sa_run_id, fork_slug) if sa_run_id else []
    retro["static_analysis"] = {
        "run_id": sa_run_id,
        "conclusion": assignment.get("stage4_sa_conclusion"),
        "jobs": sa_jobs,
    }

    # Review metrics
    inline_count = count_inline_comments_fn(assignment, ctx)
    retro["review"] = {
        "inline_comment_count": inline_count,
        "actionable": inline_count > 0,
    }

    # Remediation metrics
    skipped = assignment.get("stage4d_skipped", True)
    retro["remediation"] = {"skipped": skipped}
    if not skipped and dispatchers.get("remediation"):
        remed_results = dispatchers["remediation"].collect_results(
            str(pr_number), ctx)
        if remed_results.get("success"):
            retro["remediation"].update(remed_results["outputs"])

    # Data quality — how complete was the aggregator data for this run?
    retro["data_quality"] = {
        "context_tier": assignment.get("context_tier"),
        "context_sources": assignment.get("context_sources", []),
        "dossier_completeness": assignment.get("dossier_completeness"),
        "aggregator_meta": assignment.get("aggregator_meta"),
    }

    # Copilot session workflow analysis
    my_user = ctx.get("my_user", "")
    retro["workflow"] = fetch_workflow_analysis_fn(my_user, repo, pr_number)

    # Session artifacts — persist full session log and fork diff for retrospective
    origin_slug = assignment.get("origin_slug", "")
    issue_number = assignment.get("issue_number")
    session_artifacts = {}
    if pr_number and my_user and repo and origin_slug and issue_number:
        session_log = fetch_session_log(my_user, repo, pr_number)
        if session_log:
            path = save_session_artifact(origin_slug, issue_number, "session.log", session_log)
            if path:
                session_artifacts["session_log"] = path

        fork_diff = fetch_fork_diff(my_user, repo, pr_number)
        if fork_diff:
            path = save_session_artifact(origin_slug, issue_number, "fork-diff.patch", fork_diff)
            if path:
                session_artifacts["fork_diff"] = path
    retro["session_artifacts"] = session_artifacts

    # Timing — per-stage timestamps from assignment record
    retro["timing"] = {
        "assigned_at": assignment.get("assigned_at"),
        "swe_done_at": assignment.get("stage4_swe_done_at"),
        "sa_done_at": assignment.get("stage4_sa_done_at"),
        "review_done_at": assignment.get("stage4_review_done_at"),
        "remediation_done_at": assignment.get("stage4d_done_at"),
        "completed_at": now,
    }

    return retro
