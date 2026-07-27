"""
hadoku-task-automation status + PR review.

The pipeline ends at "pull request open" and hands off to GitHub. That is a
reasonable boundary for a machine and a bad one for a human: the last step of
every task on every board is the one step with no UI here. These two routes
close it.

    GET  /api/taskauto/status   every board, its lanes, and its open PRs
    POST /api/taskauto/merge    merge one taskauto PR

**Repos are discovered, never listed.** A board carries its own `repo`, and
`run_taskauto.py` drives whatever is shared with the service key — so a
hardcoded repo list here would go stale the first time a board is added, and
would go stale silently. Everything below keys off `board.repo`.

**Nothing here merges by itself.** The merge route is a button a person
presses; it takes an explicit repo and number and does exactly one PR. The
whole point of the `pr` mode the pipeline runs in is that a human decides.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from flask import jsonify, request

from . import bp

logger = logging.getLogger(__name__)

try:
    from ..services import run_gh_command
    from ..services.task_board import TaskBoardClient, TaskBoardError
    from ..extensions import limiter
except ImportError:
    from services import run_gh_command
    from services.task_board import TaskBoardClient, TaskBoardError
    from extensions import limiter

#: Branch prefix the pipeline pushes. Anything else in the repo is a human's.
BRANCH_PREFIX = "taskauto/"

#: Lanes in board order, so the UI doesn't have to know the vocabulary. The
#: inbox is a lane the board never names — a task with no tag is in it.
LANE_ORDER = ["(inbox)", "planning", "plan-review", "replan", "approved",
              "working", "landing", "landed", "stalled"]


def _prs_for(repo: str) -> list[dict]:
    """Open pipeline PRs on one repo. A failure is empty, not an exception —
    one unreachable repo must not blank the whole page."""
    res = run_gh_command([
        "pr", "list", "--repo", repo, "--state", "open", "--limit", "50",
        "--json", "number,title,url,headRefName,additions,deletions,"
                  "changedFiles,mergeStateStatus,isDraft,statusCheckRollup,updatedAt",
    ], timeout=25)
    if not res.get("success"):
        logger.warning("taskauto: pr list failed for %s: %s",
                       repo, res.get("error", "")[:200])
        return []
    import json as _json
    try:
        prs = _json.loads(res.get("output") or "[]")
    except ValueError:
        return []

    out = []
    for pr in prs:
        if not str(pr.get("headRefName", "")).startswith(BRANCH_PREFIX):
            continue
        checks = [c.get("conclusion") or c.get("status") or ""
                  for c in (pr.get("statusCheckRollup") or [])]
        # A PR with no checks configured is not the same as one whose checks
        # failed, and a reviewer needs to tell those apart at a glance.
        if not checks:
            verdict = "none"
        elif any(c in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED")
                 for c in checks):
            verdict = "failing"
        elif any(c in ("IN_PROGRESS", "QUEUED", "PENDING", "") for c in checks):
            verdict = "pending"
        else:
            verdict = "passing"
        out.append({
            "repo": repo,
            "number": pr.get("number"),
            "title": pr.get("title") or "",
            "url": pr.get("url") or "",
            "branch": pr.get("headRefName") or "",
            # The branch carries the task id the pipeline minted it from, so
            # the UI can put the plan next to the diff — the one thing GitHub
            # structurally cannot show.
            "taskId": (pr.get("headRefName") or "")[len(BRANCH_PREFIX):],
            "additions": pr.get("additions") or 0,
            "deletions": pr.get("deletions") or 0,
            "changedFiles": pr.get("changedFiles") or 0,
            "mergeState": pr.get("mergeStateStatus") or "",
            "isDraft": bool(pr.get("isDraft")),
            "checks": verdict,
            "updatedAt": pr.get("updatedAt") or "",
        })
    return out


@bp.route("/api/taskauto/status", methods=["GET"])
@limiter.limit("30 per minute")
def taskauto_status():
    """Every board we drive, its tasks by lane, and its open PRs."""
    try:
        client = TaskBoardClient()
        boards = client.automation_boards()
    except TaskBoardError as e:
        # No credential or an unreachable board API is an operator problem,
        # and saying which is the difference between a fix and a guess.
        logger.error("taskauto status: %s", e)
        return jsonify({"success": False, "error": str(e)}), 503

    # PR lists are one gh call per repo and dominate the response time; the
    # board reads are already fast. Fan out so adding a board costs latency
    # once rather than once per board.
    repos = sorted({b.repo for b in boards if b.repo})
    with ThreadPoolExecutor(max_workers=max(1, len(repos))) as pool:
        pr_by_repo = dict(zip(repos, pool.map(_prs_for, repos)))

    out_boards, running = [], []
    for b in sorted(boards, key=lambda x: x.name):
        try:
            full = client.get_board(b.handle)
        except TaskBoardError as e:
            out_boards.append({"handle": b.handle, "name": b.name,
                               "repo": b.repo, "error": str(e), "lanes": {}})
            continue
        lanes: dict[str, list] = {k: [] for k in LANE_ORDER}
        for t in full.active_tasks:
            lane = t.lane(full.lanes) or "(inbox)"
            entry = {
                "id": t.id,
                "title": t.title,
                "claimed": bool(t.claimed),
                "updatedAt": t.last_touched or "",
                "hasPlan": "## Plan" in (t.notes or ""),
                # A task carrying two lane tags resolves to no lane and is
                # invisible to the scheduler. Surfacing it is the whole
                # reason a status page beats reading the board.
                "stuck": len(t.lane_tags(full.lanes)) > 1,
                # Agent seconds only — the clock stops when the subprocess
                # returns, so CI and human thinking time never appear here.
                "metrics": (t.metadata or {}).get("taskauto") or {},
            }
            lanes.setdefault(lane, []).append(entry)
            if t.claimed:
                running.append({**entry, "board": b.name, "repo": b.repo,
                                "lane": lane})
        out_boards.append({
            "handle": b.handle, "name": b.name, "repo": b.repo,
            "schemaId": b.schema_id, "schemaVersion": b.schema_version,
            "lanes": lanes,
            "counts": {k: len(v) for k, v in lanes.items()},
            "prs": pr_by_repo.get(b.repo, []),
        })

    # Roll up finished work only. A task still mid-conversation has no
    # end-to-end number, and averaging partial ones would understate the cost.
    done = [t for b in out_boards for lane in b.get("lanes", {}).values()
            for t in lane if (t.get("metrics") or {}).get("agent_s")]
    agent_s = [t["metrics"]["agent_s"] for t in done]
    return jsonify({
        "success": True,
        "boards": out_boards,
        "running": running,
        "laneOrder": LANE_ORDER,
        "prCount": sum(len(v) for v in pr_by_repo.values()),
        "totals": {
            "completed": len(agent_s),
            "agentSecondsTotal": round(sum(agent_s), 1),
            "agentSecondsMean": round(sum(agent_s) / len(agent_s), 1) if agent_s else 0,
            "planSeconds": round(sum((t["metrics"].get("plan_s") or 0) for t in done), 1),
            "implementSeconds": round(
                sum((t["metrics"].get("implement_s") or 0) for t in done), 1),
            "planPasses": sum(int(t["metrics"].get("plan_passes") or 0) for t in done),
        },
    })


@bp.route("/api/taskauto/merge", methods=["POST"])
@limiter.limit("20 per minute")
def taskauto_merge():
    """Merge one pipeline PR. Explicit repo + number, never a batch.

    Refuses anything whose head branch isn't `taskauto/`: this endpoint exists
    to close the pipeline's own loop, and a generic "merge any PR" button
    reachable from a status page is a much larger thing than it looks.
    """
    body = request.get_json(silent=True) or {}
    repo = (body.get("repo") or "").strip()
    number = body.get("number")
    if not repo or not isinstance(number, int):
        return jsonify({"success": False,
                        "error": "repo and integer number are required"}), 400

    view = run_gh_command(["pr", "view", str(number), "--repo", repo,
                           "--json", "headRefName,state"], timeout=20)
    if not view.get("success"):
        return jsonify({"success": False, "error": view.get("error", "")}), 502
    import json as _json
    try:
        meta = _json.loads(view.get("output") or "{}")
    except ValueError:
        return jsonify({"success": False, "error": "unreadable pr metadata"}), 502
    if not str(meta.get("headRefName", "")).startswith(BRANCH_PREFIX):
        return jsonify({"success": False,
                        "error": f"{repo}#{number} is not a {BRANCH_PREFIX} branch"}), 403

    method = "--squash" if (body.get("method") or "squash") == "squash" else "--merge"
    res = run_gh_command(["pr", "merge", str(number), "--repo", repo,
                          method, "--delete-branch"], timeout=60)
    if not res.get("success"):
        return jsonify({"success": False, "error": res.get("error", "")}), 502
    logger.info("taskauto: merged %s#%s", repo, number)
    return jsonify({"success": True, "repo": repo, "number": number})
