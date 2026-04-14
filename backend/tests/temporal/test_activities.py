"""Unit tests for backend.temporal.activities — Phase 1C.

Covers all 9 activity modules with mocked external dependencies (no
network, no subprocess, no real Copilot). Each activity is a thin
wrapper, so the tests focus on:
  - the right evidence files get written with the right shape
  - the right external calls get made
  - errors propagate as exceptions (orchestrator catches them)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from temporal.agents import IssueRef
from temporal.agents.noop import NoopAgent
from temporal.evidence.store import EvidenceStore


@pytest.fixture
def issue() -> IssueRef:
    return IssueRef(
        fork_slug="WolffM/markitdown",
        upstream_slug="microsoft/markitdown",
        number=183,
    )


@pytest.fixture
def ev(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "issue")


# ── eligibility activity ──────────────────────────────────────────────────


def test_eligibility_activity_writes_three_files(ev):
    from temporal.activities.eligibility import check_eligibility

    def fake_get(endpoint: str):
        if "dossier" in endpoint:
            return {"success": True, "data": {"health": {"activity_score": 0.8}}}
        if "issue-brief" in endpoint:
            return {"success": True, "data": {"issue": {"state": "open", "title": "x", "body": "y"}}}
        if "contributing" in endpoint:
            return {"success": True, "data": {"ai_policy": "unknown", "dco_required": False, "license_check_required": False}}
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    result = check_eligibility(
        "microsoft/markitdown", 183, ev,
        aggregator_get=fake_get,
    )
    assert result["ok"] is True
    assert ev.exists("01-eligible/dossier.json")
    assert ev.exists("01-eligible/issue_brief.json")
    assert ev.exists("01-eligible/contributing_check.json")


def test_eligibility_activity_raises_on_envelope_failure(ev):
    from temporal.activities.eligibility import check_eligibility

    def fake_get(endpoint: str):
        return {"success": False, "data": None}

    with pytest.raises(RuntimeError, match="success=false"):
        check_eligibility("microsoft/markitdown", 183, ev, aggregator_get=fake_get)


def test_eligibility_activity_uses_hyphenated_slug(ev):
    from temporal.activities.eligibility import check_eligibility

    seen = []

    def fake_get(endpoint: str):
        seen.append(endpoint)
        return {"success": True, "data": {}}

    check_eligibility("mermaid-js/mermaid", 4099, ev, aggregator_get=fake_get)
    assert any("mermaid-js-mermaid" in e for e in seen)
    assert not any("mermaid-js/mermaid" in e for e in seen)


# ── fork + scrub activity ─────────────────────────────────────────────────


def test_fork_and_scrub_brief_writes_evidence_when_fork_exists(ev):
    from temporal.activities.fork import fork_and_scrub_brief

    calls = []

    def fake_gh(args, stdin_data=None):
        calls.append(args)
        if args[:3] == ["api", "repos/WolffM/markitdown", "--silent"]:
            return {"success": True, "output": ""}
        raise AssertionError(f"unexpected gh call: {args}")

    raw_brief = "fix microsoft/markitdown#183 — see https://github.com/microsoft/markitdown/issues/183"
    result = fork_and_scrub_brief(
        upstream_slug="microsoft/markitdown",
        issue_number=183,
        raw_brief_text=raw_brief,
        branch_name="fix-merged-cells",
        evidence=ev,
        run_gh=fake_gh,
    )

    assert result["ok"] is True
    assert result["scrub_count"] >= 2  # url + short ref both stripped
    assert ev.exists("02-forked/scrubbed_brief.md")
    scrubbed = ev.read_text("02-forked/scrubbed_brief.md")
    assert "microsoft/markitdown#183" not in scrubbed
    assert "github.com/microsoft/markitdown" not in scrubbed


def test_fork_and_scrub_brief_creates_fork_when_missing(ev):
    from temporal.activities.fork import fork_and_scrub_brief

    calls = []

    def fake_gh(args, stdin_data=None):
        calls.append(args)
        if "repos/WolffM/markitdown" in args and "--silent" in args:
            return {"success": False, "error": "404"}
        if args[:2] == ["repo", "fork"]:
            return {"success": True, "output": ""}
        raise AssertionError(f"unexpected gh call: {args}")

    fork_and_scrub_brief(
        "microsoft/markitdown", 183, "clean brief", "branch-x", ev,
        run_gh=fake_gh,
    )
    fork_calls = [c for c in calls if c[:2] == ["repo", "fork"]]
    assert len(fork_calls) == 1


# ── environment activity ──────────────────────────────────────────────────


def test_setup_environment_pass(ev, tmp_path):
    from temporal.activities.environment import setup_environment

    def fake_runner(cmd, cwd, timeout):
        return {"success": True, "output": "installed", "error": "", "returncode": 0}

    setup_environment(
        fork_slug="WolffM/markitdown",
        branch_name="b",
        workdir=str(tmp_path),
        install_cmd=["pip", "install", "-e", "."],
        evidence=ev,
        runner=fake_runner,
    )
    health = ev.read_json("03-environment/health.json")
    assert health == {"installable": True}
    assert ev.exists("03-environment/install_log.txt")


def test_setup_environment_records_install_failure(ev, tmp_path):
    from temporal.activities.environment import setup_environment

    def fake_runner(cmd, cwd, timeout):
        return {"success": False, "output": "", "error": "missing dep", "returncode": 1}

    setup_environment(
        "WolffM/markitdown", "b", str(tmp_path), ["pip", "install", "-e", "."], ev,
        runner=fake_runner,
    )
    assert ev.read_json("03-environment/health.json")["installable"] is False


def test_setup_environment_with_dev_server(ev, tmp_path):
    from temporal.activities.environment import setup_environment

    def fake_runner(cmd, cwd, timeout):
        return {"success": True, "output": "", "error": "", "returncode": 0}

    setup_environment(
        "WolffM/x", "b", str(tmp_path), ["pip", "install"], ev,
        dev_server_cmd=["python", "-m", "http.server"],
        runner=fake_runner,
    )
    health = ev.read_json("03-environment/health.json")
    assert health == {"installable": True, "runnable": True}


# ── agent-driven activities ───────────────────────────────────────────────


def test_request_fix_writes_diff_and_commits(ev, issue):
    from temporal.activities.agent import request_fix

    agent = NoopAgent()
    request_fix(agent, issue, scrubbed_brief="fix it", evidence=ev)

    assert ev.exists("05-fixed/diff.patch")
    assert ev.exists("05-fixed/commit_shas.txt")
    assert ev.exists("05-fixed/files_touched.txt")
    assert ev.exists("05-fixed/commits.json")
    assert ev.exists("05-fixed/agent_result.json")

    diff = ev.read_text("05-fixed/diff.patch")
    assert "diff --git" in diff


def test_request_fix_propagates_failure(ev, issue):
    from temporal.activities.agent import request_fix

    agent = NoopAgent(diff_text="", commit_shas=[], exit_reason="error")
    result = request_fix(agent, issue, "x", ev)
    assert result["ok"] is False
    assert result["exit_reason"] == "error"


def test_request_repro_writes_agent_result(ev, issue):
    from temporal.activities.agent import request_repro

    agent = NoopAgent()
    request_repro(agent, issue, "reproduce it", ev)
    assert ev.exists("04-reproduced/agent_result.json")


def test_request_verify_writes_agent_result(ev, issue):
    from temporal.activities.agent import request_verify

    agent = NoopAgent()
    request_verify(agent, issue, "verify it", ev)
    assert ev.exists("06-verified/agent_result.json")


def test_request_remediation_appends_review_comments_to_brief(ev, issue):
    from temporal.activities.agent import request_remediation

    ev.write_json("07-reviewed/comments.json", [
        {"id": "c1", "severity": "blocking", "body": "fix this"},
    ])

    captured_briefs = []

    class CapturingAgent(NoopAgent):
        def assign(self, issue, brief, instruction=""):
            captured_briefs.append(brief)
            return super().assign(issue, brief=brief, instruction=instruction)

    request_remediation(
        CapturingAgent(),
        issue,
        scrubbed_brief="base brief",
        review_comments_path="07-reviewed/comments.json",
        evidence=ev,
    )

    assert "fix this" in captured_briefs[0]
    assert ev.exists("08-remediated/diff.patch")


# ── review activity ───────────────────────────────────────────────────────


def test_review_activity_normalizes_comments(ev):
    from temporal.activities.review import run_review

    def fake_runner(fork_slug, pr_number):
        return {
            "comments": [
                {"id": 1, "severity": "BLOCKING", "body": "x", "path": "a.py", "line": 10},
                {"id": 2, "severity": "nit", "body": "y", "path": "b.py", "line": 5},
                {"comment_id": "x3", "severity": None, "body": "z"},  # weird shape
                "not a dict",  # filtered out
            ]
        }

    result = run_review("WolffM/x", 9, ev, review_runner=fake_runner)
    assert result["comment_count"] == 3
    comments = ev.read_json("07-reviewed/comments.json")
    assert comments[0]["severity"] == "blocking"
    assert comments[2]["severity"] == "suggested"  # default
    summary = ev.read_json("07-reviewed/severity_summary.json")
    assert summary["blocking"] == 1
    assert summary["nit"] == 1


# ── submission activity ───────────────────────────────────────────────────


def test_render_pr_body_without_template(ev):
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "Fix the merged-cell bug"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\ntests/test_x.py\n")
    ev.write_text("05-fixed/diff.patch", "diff " * 50)
    ev.write_text("05-fixed/commit_shas.txt", "abc\ndef\n")

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    result = render_pr_body(
        "microsoft/markitdown", 183, ev, aggregator_get=fake_get,
    )
    assert result["ok"] is True
    title = ev.read_text("09-submittable/pr_title.txt")
    body = ev.read_text("09-submittable/pr_body.md")
    assert "Fix the merged-cell bug" in title
    assert "## Summary" in body
    assert "src/x.py" in body
    assert "Fixes #183" in body


def test_render_pr_body_with_template(ev):
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x"}})
    ev.write_text("05-fixed/files_touched.txt", "a.py\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")

    def fake_get(endpoint: str):
        return {"success": True, "data": {
            "path": ".github/PULL_REQUEST_TEMPLATE.md",
            "raw_text": "## Summary\n\n## Test plan\n",
            "sections": [
                {"heading": "## Summary", "required": True},
                {"heading": "## Test plan", "required": True},
            ],
        }}

    render_pr_body("microsoft/markitdown", 183, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")
    assert "## Summary" in body
    assert "## Test plan" in body
    assert "Fixes #183" in body
    assert ev.exists("09-submittable/template.json")


def test_submit_upstream_pr_writes_evidence_on_success(ev):
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "Fix x")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix\n")

    def fake_gh(args, stdin_data=None):
        if args[:2] == ["pr", "create"]:
            return {"success": True, "output": "https://github.com/microsoft/markitdown/pull/9999\n"}
        raise AssertionError(f"unexpected gh call: {args}")

    result = submit_upstream_pr(
        "microsoft/markitdown", "WolffM/markitdown", "fix-x", "main", ev,
        run_gh=fake_gh,
    )
    assert result["pr_number"] == 9999
    assert "9999" in result["pr_url"]
    assert ev.read_text("10-submitted/upstream_pr_url").strip().endswith("9999")


def test_submit_upstream_pr_raises_on_failure(ev):
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "x")
    ev.write_text("09-submittable/pr_body.md", "y")

    def fake_gh(args, stdin_data=None):
        return {"success": False, "error": "pr already exists"}

    with pytest.raises(RuntimeError, match="gh pr create failed"):
        submit_upstream_pr("u/r", "WolffM/r", "b", "main", ev, run_gh=fake_gh)


# ── watcher activity ──────────────────────────────────────────────────────


def test_notify_human_comments_filters_bots_and_dedupes(ev):
    from temporal.activities.watchers import notify_human_comments_for_issue

    notifications: list[str] = []

    def fake_gh(args, stdin_data=None):
        return {
            "success": True,
            "output": json.dumps([
                {"id": 1, "user": "alice", "body": "looks good", "created_at": "2026-04-14T00:00Z"},
                {"id": 2, "user": "copilot[bot]", "body": "auto", "created_at": "2026-04-14T00:01Z"},
                {"id": 3, "user": "bob", "body": "fix this", "created_at": "2026-04-14T00:02Z"},
            ]),
        }

    def fake_notify(message: str) -> None:
        notifications.append(message)

    def fake_is_bot(login: str) -> bool:
        return "[bot]" in login.lower()

    result = notify_human_comments_for_issue(
        "microsoft/markitdown", 9, set(), ev,
        run_gh=fake_gh, notify=fake_notify, is_bot=fake_is_bot,
    )
    assert result["new_count"] == 2  # alice + bob, copilot filtered
    assert len(notifications) == 2

    # Second call with same seen_ids → no new
    result2 = notify_human_comments_for_issue(
        "microsoft/markitdown", 9, set(result["seen_ids"]), ev,
        run_gh=fake_gh, notify=fake_notify, is_bot=fake_is_bot,
    )
    assert result2["new_count"] == 0


# ── inbox activity ────────────────────────────────────────────────────────


def test_enqueue_for_human_review_writes_entry_and_notifies(ev):
    from temporal.activities.inbox import enqueue_for_human_review

    notifications = []

    enqueue_for_human_review(
        state="fixed",
        gate_name="relevance",
        reason="borderline score 0.55",
        score=0.55,
        upstream_slug="microsoft/markitdown",
        issue_number=183,
        evidence=ev,
        notify=lambda m: notifications.append(m),
    )

    entry = ev.read_json("awaiting/inbox_entry.json")
    assert entry["state"] == "fixed"
    assert entry["gate"] == "relevance"
    assert entry["score"] == 0.55
    assert ev.exists("awaiting/queued_at")
    assert len(notifications) == 1
    assert "183" in notifications[0]


def test_enqueue_for_human_review_swallows_notify_errors(ev):
    from temporal.activities.inbox import enqueue_for_human_review

    def boom(message: str):
        raise RuntimeError("discord down")

    # Should not raise — notification failure is best-effort
    result = enqueue_for_human_review(
        "fixed", "relevance", "x", 0.5, "x/y", 1, ev, notify=boom,
    )
    assert result["ok"] is True
    assert ev.exists("awaiting/inbox_entry.json")
