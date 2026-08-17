"""Tests for the taskauto task-detail route.

The route's whole job is assembling one answer from three sources — the
board's task, the board's claim log, GitHub's PR list — so the tests that
matter are about what happens when one of those three is missing, and about
the branch name that links a board task to its diff. Get that derivation
wrong and the detail view silently shows no PR for a task that has one.
"""

import json
from unittest.mock import patch

import pytest

from app import app
from extensions import limiter
from services.task_board import BoardSnapshot, BoardTask, Lane, TaskBoardUnavailable

PREFIX = "/tenhands"
BOARD = "MBOARDHANDLE00000000000000"
TASK_ID = "01KYJNFF5X7GV1VE59BZSJ32H2"


@pytest.fixture
def client():
    app.config["TESTING"] = True
    limiter.enabled = False
    with app.test_client() as c:
        yield c
    limiter.enabled = True


def _snapshot(tasks):
    return BoardSnapshot(
        id="b1", name="tenhands", handle=BOARD, repo="WolffM/tenhands",
        mode="automation",
        lanes=[Lane(tag="landed", label="Landed", order=1, editable_by="agent"),
               Lane(tag="working", label="Working", order=2, editable_by="agent")],
        tasks=tasks, schema_id="s1", schema_version=1, access="contributor",
        version=3,
    )


def _task(**over):
    base = dict(
        id=TASK_ID, title="review taskauto PRs", notes="## Plan\n\n1. do it\n",
        tag="landed", metadata={"taskauto": {"agent_s": 684.489}},
        claimed=False, state="Active",
        created_at="2026-07-27T20:50:18.678Z",
        updated_at="2026-07-28T01:52:52.304Z",
    )
    base.update(over)
    return BoardTask(**base)


def _gh_prs(payload):
    """A successful `gh pr list` result carrying `payload`."""
    return {"success": True, "output": json.dumps(payload)}


class TestTaskDetail:
    @patch("routes.taskauto_routes.run_gh_command")
    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_assembles_task_history_and_pr(self, mock_client_cls, mock_gh, client):
        c = mock_client_cls.return_value
        c.get_board.return_value = _snapshot([_task()])
        c.history.return_value = [
            {"agentId": "a1", "claimedAt": "2026-07-28T01:41:20Z",
             "endedAt": "2026-07-28T01:52:52Z", "endedBy": "release",
             "outcome": "pr-open:88"},
            {"agentId": "a1", "claimedAt": "2026-07-27T21:16:58Z",
             "endedAt": "2026-07-27T21:21:46Z", "endedBy": "release",
             "outcome": "plan:questions"},
        ]
        mock_gh.return_value = _gh_prs([{
            "number": 88, "title": "review taskauto PRs",
            "url": "https://github.com/WolffM/tenhands/pull/88",
            "headRefName": "taskauto/01kyjnff5x7g", "additions": 465,
            "deletions": 11, "changedFiles": 6, "mergeStateStatus": "CLEAN",
            "isDraft": False, "statusCheckRollup": [{"conclusion": "SUCCESS"}],
            "state": "MERGED", "mergedAt": "2026-07-28T09:00:00Z",
            "createdAt": "2026-07-28T01:52:51Z",
            "updatedAt": "2026-07-28T09:00:00Z",
        }])

        data = client.get(f"{PREFIX}/api/taskauto/task/{BOARD}/{TASK_ID}").get_json()

        assert data["success"] is True
        assert data["board"]["repo"] == "WolffM/tenhands"
        assert data["task"]["lane"] == "landed"
        assert data["task"]["metrics"]["agent_s"] == 684.489
        # Oldest first — the order a timeline is read.
        assert [h["outcome"] for h in data["history"]] == [
            "plan:questions", "pr-open:88"]
        assert data["prs"][0]["state"] == "MERGED"
        assert data["prs"][0]["checks"] == "passing"

    @patch("routes.taskauto_routes.run_gh_command")
    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_looks_up_prs_by_the_branch_the_pipeline_pushes(
            self, mock_client_cls, mock_gh, client):
        """First 12 characters of the ULID, lowercased — same as jobs.py."""
        mock_client_cls.return_value.get_board.return_value = _snapshot([_task()])
        mock_client_cls.return_value.history.return_value = []
        mock_gh.return_value = _gh_prs([])

        client.get(f"{PREFIX}/api/taskauto/task/{BOARD}/{TASK_ID}")

        args = mock_gh.call_args[0][0]
        assert "--head" in args
        assert args[args.index("--head") + 1] == "taskauto/01kyjnff5x7g"
        assert args[args.index("--state") + 1] == "all"

    @patch("routes.taskauto_routes.run_gh_command")
    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_history_failure_leaves_the_rest_intact(
            self, mock_client_cls, mock_gh, client):
        """The claim log is supplementary; losing it must not 503 the view."""
        c = mock_client_cls.return_value
        c.get_board.return_value = _snapshot([_task()])
        c.history.side_effect = TaskBoardUnavailable("history timed out")
        mock_gh.return_value = _gh_prs([])

        resp = client.get(f"{PREFIX}/api/taskauto/task/{BOARD}/{TASK_ID}")
        data = resp.get_json()

        assert resp.status_code == 200
        assert data["history"] == []
        assert data["task"]["title"] == "review taskauto PRs"

    @patch("routes.taskauto_routes.run_gh_command")
    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_gh_failure_leaves_the_plan_intact(
            self, mock_client_cls, mock_gh, client):
        c = mock_client_cls.return_value
        c.get_board.return_value = _snapshot([_task()])
        c.history.return_value = []
        mock_gh.return_value = {"success": False, "error": "gh: not authorized"}

        data = client.get(f"{PREFIX}/api/taskauto/task/{BOARD}/{TASK_ID}").get_json()

        assert data["prs"] == []
        assert data["task"]["notes"].startswith("## Plan")

    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_unknown_task_is_404(self, mock_client_cls, client):
        mock_client_cls.return_value.get_board.return_value = _snapshot([])

        resp = client.get(f"{PREFIX}/api/taskauto/task/{BOARD}/{TASK_ID}")

        assert resp.status_code == 404
        assert resp.get_json()["success"] is False

    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_unreachable_board_is_503(self, mock_client_cls, client):
        mock_client_cls.return_value.get_board.side_effect = TaskBoardUnavailable(
            "board timed out")

        resp = client.get(f"{PREFIX}/api/taskauto/task/{BOARD}/{TASK_ID}")

        assert resp.status_code == 503
        assert "timed out" in resp.get_json()["error"]

    @patch("routes.taskauto_routes.run_gh_command")
    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_two_lane_tags_report_no_lane(self, mock_client_cls, mock_gh, client):
        """A task the scheduler cannot see must not look like it is in a lane."""
        c = mock_client_cls.return_value
        c.get_board.return_value = _snapshot([_task(tag="landed working")])
        c.history.return_value = []
        mock_gh.return_value = _gh_prs([])

        data = client.get(f"{PREFIX}/api/taskauto/task/{BOARD}/{TASK_ID}").get_json()

        assert data["task"]["lane"] == "(inbox)"
        assert data["task"]["laneTags"] == ["landed", "working"]


class TestMerge:
    """The merge route is the pipeline's human gate, so its two modes matter.

    An immediate merge and a scheduled ("merge when green") one are different
    promises to the user: the first says the work landed, the second says a
    decision was recorded and CI still gets a veto. Conflating them would
    report a merge that has not happened.
    """

    def _view(self, branch="taskauto/01kyjnff5x7g"):
        return {"success": True,
                "output": json.dumps({"headRefName": branch, "state": "OPEN"})}

    @patch("routes.taskauto_routes.run_gh_command")
    def test_immediate_merge_omits_auto(self, mock_gh, client):
        mock_gh.side_effect = [self._view(), {"success": True, "output": ""}]

        resp = client.post(f"{PREFIX}/api/taskauto/merge",
                           json={"repo": "WolffM/tenhands", "number": 88})

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["scheduled"] is False
        assert "--auto" not in mock_gh.call_args_list[1].args[0]

    @patch("routes.taskauto_routes.run_gh_command")
    def test_auto_merge_passes_auto_and_reports_scheduled(self, mock_gh, client):
        mock_gh.side_effect = [self._view(), {"success": True, "output": ""}]

        resp = client.post(f"{PREFIX}/api/taskauto/merge",
                           json={"repo": "WolffM/tenhands", "number": 88,
                                 "auto": True})

        assert resp.status_code == 200
        assert resp.get_json()["scheduled"] is True
        merge_cmd = mock_gh.call_args_list[1].args[0]
        assert "--auto" in merge_cmd
        assert "--squash" in merge_cmd

    @patch("routes.taskauto_routes.run_gh_command")
    def test_refuses_a_branch_the_pipeline_did_not_push(self, mock_gh, client):
        """Auto-merge must not widen what this endpoint will touch."""
        mock_gh.side_effect = [self._view(branch="feature/hand-written")]

        resp = client.post(f"{PREFIX}/api/taskauto/merge",
                           json={"repo": "WolffM/tenhands", "number": 88,
                                 "auto": True})

        assert resp.status_code == 403
        assert mock_gh.call_count == 1


class TestActionable:
    """GET /api/taskauto/actionable — open issues + PRs for a board's repo,
    with the pipeline's own taskauto/* PRs and bot authors filtered out."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        # The route caches per repo; tests reuse WolffM/tenhands, so a stale
        # entry would leak one test's gh payload into the next.
        import routes.taskauto_routes as tr
        tr._actionable_cache.clear()
        yield
        tr._actionable_cache.clear()

    @staticmethod
    def _gh(issues, prs):
        """A run_gh_command side_effect that answers issue-list vs pr-list."""
        def _side(cmd, timeout=None):
            if cmd[0] == "issue":
                return {"success": True, "output": json.dumps(issues)}
            if cmd[0] == "pr":
                return {"success": True, "output": json.dumps(prs)}
            return {"success": False, "error": f"unexpected {cmd[0]}"}
        return _side

    @patch("routes.taskauto_routes.run_gh_command")
    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_returns_issues_and_prs_filtered(self, mock_client_cls, mock_gh, client):
        mock_client_cls.return_value.get_board.return_value = _snapshot([])
        mock_gh.side_effect = self._gh(
            issues=[
                {"number": 42, "title": "Fix the thing",
                 "url": "https://github.com/WolffM/tenhands/issues/42",
                 "author": {"login": "someone", "is_bot": False},
                 "body": "line one\n\nline two " + "x" * 400},
                {"number": 9, "title": "dep bump",
                 "url": "https://github.com/WolffM/tenhands/issues/9",
                 "author": {"login": "dependabot", "is_bot": True}, "body": ""},
            ],
            prs=[
                {"number": 17, "title": "WIP feature",
                 "url": "https://github.com/WolffM/tenhands/pull/17",
                 "author": {"login": "someone", "is_bot": False},
                 "headRefName": "feature-x", "body": "continue me"},
                {"number": 88, "title": "landing",
                 "url": "https://github.com/WolffM/tenhands/pull/88",
                 "author": {"login": "someone", "is_bot": False},
                 "headRefName": "taskauto/01kyjnff5x7g", "body": "our own PR"},
            ],
        )

        data = client.get(
            f"{PREFIX}/api/taskauto/actionable?board={BOARD}").get_json()

        assert data["success"] is True
        assert data["repo"] == "WolffM/tenhands"
        # bot issue #9 and taskauto PR #88 are dropped; #42 and #17 remain.
        by_kind = {(i["kind"], i["number"]): i for i in data["items"]}
        assert set(by_kind) == {("issue", 42), ("pr", 17)}

        issue = by_kind[("issue", 42)]
        assert issue["suggested_title"] == "Address #42"
        assert issue["author"] == "someone"
        # body collapsed to one line and capped with an ellipsis.
        assert issue["body_snippet"].startswith("line one line two")
        assert issue["body_snippet"].endswith("…")
        assert len(issue["body_snippet"]) <= 281

        pr = by_kind[("pr", 17)]
        assert pr["suggested_title"] == "Address PR #17"
        assert pr["head_ref"] == "feature-x"

    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_missing_board_param_is_400(self, mock_client_cls, client):
        resp = client.get(f"{PREFIX}/api/taskauto/actionable")
        assert resp.status_code == 400
        assert resp.get_json()["success"] is False

    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_board_without_repo_is_404(self, mock_client_cls, client):
        snap = _snapshot([])
        object.__setattr__(snap, "repo", "")
        mock_client_cls.return_value.get_board.return_value = snap
        resp = client.get(f"{PREFIX}/api/taskauto/actionable?board={BOARD}")
        assert resp.status_code == 404

    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_board_api_failure_is_503(self, mock_client_cls, client):
        mock_client_cls.return_value.get_board.side_effect = \
            TaskBoardUnavailable("board api down")
        resp = client.get(f"{PREFIX}/api/taskauto/actionable?board={BOARD}")
        assert resp.status_code == 503
        assert resp.get_json()["success"] is False

    @patch("routes.taskauto_routes.run_gh_command")
    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_gh_failure_is_503_not_an_empty_list(self, mock_client_cls, mock_gh,
                                                 client):
        """A dead token must not read as "nothing open".

        Both answers hide the consumer's button, so degrading to empty leaves an
        expired credential with no symptom at all.
        """
        mock_client_cls.return_value.get_board.return_value = _snapshot([])
        mock_gh.return_value = {
            "success": False, "error": "gh: Bad credentials (HTTP 401)"}
        resp = client.get(f"{PREFIX}/api/taskauto/actionable?board={BOARD}")
        assert resp.status_code == 503
        body = resp.get_json()
        assert body["success"] is False
        # The 503 names the cause, or the next investigation starts from zero.
        assert "Bad credentials" in body["error"]

    @patch("routes.taskauto_routes.run_gh_command")
    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_one_failing_source_fails_the_whole_scan(self, mock_client_cls,
                                                     mock_gh, client):
        """Issues fine, PRs broken — a partial list is not a short list."""
        mock_client_cls.return_value.get_board.return_value = _snapshot([])

        def _side(cmd, timeout=None):
            if cmd[0] == "issue":
                return {"success": True, "output": json.dumps([
                    {"number": 42, "title": "Fix the thing",
                     "url": "https://github.com/WolffM/tenhands/issues/42",
                     "author": {"login": "someone", "is_bot": False},
                     "body": ""},
                ])}
            return {"success": False, "error": "gh pr list exploded"}

        mock_gh.side_effect = _side
        resp = client.get(f"{PREFIX}/api/taskauto/actionable?board={BOARD}")
        assert resp.status_code == 503
        assert "exploded" in resp.get_json()["error"]

    @patch("routes.taskauto_routes.run_gh_command")
    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_failure_is_not_cached(self, mock_client_cls, mock_gh, client):
        """A recovered token takes effect now, not in 30 seconds."""
        mock_client_cls.return_value.get_board.return_value = _snapshot([])
        mock_gh.return_value = {"success": False, "error": "gh boom"}
        assert client.get(
            f"{PREFIX}/api/taskauto/actionable?board={BOARD}").status_code == 503

        mock_gh.side_effect = self._gh(issues=[], prs=[])
        mock_gh.return_value = None
        resp = client.get(f"{PREFIX}/api/taskauto/actionable?board={BOARD}")
        assert resp.status_code == 200
        assert resp.get_json() == {
            "success": True, "repo": "WolffM/tenhands", "items": []}

    @patch("routes.taskauto_routes.run_gh_command")
    @patch("routes.taskauto_routes.TaskBoardClient")
    def test_empty_repo_is_a_success(self, mock_client_cls, mock_gh, client):
        """The other half of the contract: nothing open really is `items: []`."""
        mock_client_cls.return_value.get_board.return_value = _snapshot([])
        mock_gh.side_effect = self._gh(issues=[], prs=[])
        resp = client.get(f"{PREFIX}/api/taskauto/actionable?board={BOARD}")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert resp.get_json()["items"] == []
