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
