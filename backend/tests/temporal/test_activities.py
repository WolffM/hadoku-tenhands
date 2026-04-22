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


def test_eligibility_activity_writes_evidence_files(ev):
    from temporal.activities.eligibility import check_eligibility

    def fake_get(endpoint: str):
        if "dossier" in endpoint:
            return {"success": True, "data": {"sections": []}}
        if "health" in endpoint:
            return {"success": True, "data": {"maintainerHealthScore": 80}}
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
    assert ev.exists("01-eligible/health.json")
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
        if "issue-brief" in endpoint:
            # force fallback attempts to exercise the scored-issues path
            return {"success": True, "data": {"issue": {}}}
        return {"success": True, "data": {}}

    check_eligibility("mermaid-js/mermaid", 4099, ev, aggregator_get=fake_get)
    assert any("mermaid-js-mermaid" in e for e in seen)
    assert not any("mermaid-js/mermaid" in e for e in seen)


def test_eligibility_falls_back_to_scored_snapshot(ev):
    """When /issue-brief/{id} returns success=false, find snapshot in
    /scored-issues and POST /compose-brief."""
    from temporal.activities.eligibility import check_eligibility

    get_calls = []
    post_calls = []

    def fake_get(endpoint: str):
        get_calls.append(endpoint)
        if "dossier" in endpoint:
            return {"success": True, "data": {"sections": []}}
        if "health" in endpoint:
            return {"success": True, "data": {}}
        if "issue-brief/github-" in endpoint:
            # Aged out of top-100
            return {"success": False, "error": "issue not found: ..."}
        if "scored-issues" in endpoint:
            return {"success": True, "data": {"issues": [
                {"url": "https://github.com/cli/cli/issues/9569", "title": "foo", "body": "bar"},
                {"url": "https://github.com/cli/cli/issues/1234", "title": "other"},
            ]}}
        if "contributing" in endpoint:
            return {"success": True, "data": {"ai_policy": "unknown"}}
        raise AssertionError(f"unexpected GET: {endpoint}")

    def fake_post(endpoint: str, body: dict):
        post_calls.append((endpoint, body))
        assert endpoint == "/recon/cli-cli/compose-brief"
        assert body["issue"]["url"].endswith("/9569")
        return {"success": True, "data": {"issue": {"state": "open"}, "brief": "composed text"}}

    def fake_gh(slug, num):
        raise AssertionError("should not fall through to gh fetcher when snapshot is in scored-issues")

    result = check_eligibility(
        "cli/cli", 9569, ev,
        aggregator_get=fake_get, aggregator_post=fake_post, gh_issue_fetcher=fake_gh,
    )
    assert result["brief_source"] == "scored-snapshot"
    assert ev.read_text("01-eligible/brief_source.txt") == "scored-snapshot"
    assert len(post_calls) == 1


def test_eligibility_falls_back_to_gh_snapshot(ev):
    """When issue isn't in scored-issues either, fetch from gh api, build
    snapshot, and POST /compose-brief."""
    from temporal.activities.eligibility import check_eligibility

    def fake_get(endpoint: str):
        if "dossier" in endpoint:
            return {"success": True, "data": {}}
        if "health" in endpoint:
            return {"success": True, "data": {}}
        if "issue-brief/github-" in endpoint:
            return {"success": False, "error": "issue not found"}
        if "scored-issues" in endpoint:
            # Not in scored-issues either
            return {"success": True, "data": {"issues": []}}
        if "contributing" in endpoint:
            return {"success": True, "data": {"ai_policy": "unknown"}}
        raise AssertionError(f"unexpected GET: {endpoint}")

    def fake_post(endpoint: str, body: dict):
        assert endpoint == "/recon/shadcn-ui-ui/compose-brief"
        # snapshot built from gh API
        assert body["issue"]["id"] == "github-shadcn-ui-ui-6843"
        assert body["issue"]["title"] == "Cursor pointer issue"
        assert body["issue"]["dataCompleteness"] == "raw"
        return {"success": True, "data": {"issue": {"state": "open"}, "brief": "composed text"}}

    def fake_gh(slug, num):
        assert slug == "shadcn-ui/ui"
        assert num == 6843
        return {
            "title": "Cursor pointer issue",
            "body": "body text",
            "html_url": "https://github.com/shadcn-ui/ui/issues/6843",
            "labels": [{"name": "bug"}],
            "user": {"login": "someone"},
            "created_at": "2025-03-03T18:53:16Z",
            "updated_at": "2025-03-03T18:53:16Z",
            "comments": 47,
            "reactions": {"+1": 121},
            "author_association": "NONE",
        }

    result = check_eligibility(
        "shadcn-ui/ui", 6843, ev,
        aggregator_get=fake_get, aggregator_post=fake_post, gh_issue_fetcher=fake_gh,
    )
    assert result["brief_source"] == "gh-snapshot"


def test_eligibility_direct_path_still_works(ev):
    """When the aggregator's pre-composed brief is available, no fallback fires."""
    from temporal.activities.eligibility import check_eligibility

    post_calls = []

    def fake_get(endpoint: str):
        if "dossier" in endpoint:
            return {"success": True, "data": {}}
        if "health" in endpoint:
            return {"success": True, "data": {}}
        if "issue-brief/github-" in endpoint:
            return {"success": True, "data": {"issue": {"state": "open"}, "brief": "pre-composed"}}
        if "contributing" in endpoint:
            return {"success": True, "data": {"ai_policy": "unknown"}}
        raise AssertionError(f"unexpected GET: {endpoint}")

    def fake_post(endpoint: str, body: dict):
        post_calls.append((endpoint, body))
        return None

    def fake_gh(slug, num):
        raise AssertionError("should not be called on direct-path success")

    result = check_eligibility(
        "jestjs/jest", 2070, ev,
        aggregator_get=fake_get, aggregator_post=fake_post, gh_issue_fetcher=fake_gh,
    )
    assert result["brief_source"] == "direct"
    assert post_calls == []


# ── fork + scrub activity ─────────────────────────────────────────────────


def _fake_gh_fork(include_upstream_workflows=True):
    """Build a fake gh runner that handles fork existence + safety-config calls.

    Simulated workflow listing includes three inherited (`.github/workflows/*.yml`),
    three auto-provisioned dynamic/* (codeql, dependabot, copilot-reviewer), and
    the copilot-swe-agent — the single workflow we keep.
    """
    calls = []

    def fake_gh(args, stdin_data=None):
        calls.append(args)
        # Fork existence check
        if args[:3] == ["api", "repos/WolffM/markitdown", "--silent"]:
            return {"success": True, "output": ""}
        # Fork creation
        if args[:2] == ["repo", "fork"]:
            return {"success": True, "output": ""}
        # Enable issues (PATCH /repos/{slug} with has_issues=true)
        if (
            len(args) >= 6
            and args[0] == "api"
            and args[1] == "repos/WolffM/markitdown"
            and args[2] == "-X"
            and args[3] == "PATCH"
            and "has_issues=true" in args
        ):
            return {"success": True, "output": ""}
        # Actions policy PUT
        if len(args) >= 4 and args[1].endswith("/actions/permissions") and args[2] == "-X" and args[3] == "PUT":
            return {"success": True, "output": ""}
        # Workflow list
        if len(args) >= 2 and args[1].endswith("/actions/workflows"):
            if include_upstream_workflows:
                rows = [
                    "1\t.github/workflows/test-matrix.yml\tactive",
                    "2\t.github/workflows/ci.yml\tactive",
                    "3\t.github/workflows/release.yml\tactive",
                    "4\tdynamic/github-code-scanning/codeql\tactive",
                    "5\tdynamic/dependabot/dependabot-updates\tactive",
                    "6\tdynamic/copilot-pull-request-reviewer/copilot-pull-request-reviewer\tactive",
                    "7\tdynamic/copilot-swe-agent/copilot\tactive",
                ]
                return {"success": True, "output": "\n".join(rows)}
            return {"success": True, "output": ""}
        # Workflow disable
        if len(args) >= 2 and "/disable" in args[1]:
            return {"success": True, "output": ""}
        raise AssertionError(f"unexpected gh call: {args}")

    return fake_gh, calls


def test_fork_and_scrub_brief_writes_evidence_when_fork_exists(ev):
    from temporal.activities.fork import fork_and_scrub_brief

    fake_gh, _calls = _fake_gh_fork()

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
        # Safety config calls — accept and no-op
        if len(args) >= 2 and (
            args[1] == "repos/WolffM/markitdown"  # has_issues PATCH
            or args[1].endswith("/actions/permissions")
            or args[1].endswith("/actions/workflows")
            or "/disable" in args[1]
        ):
            return {"success": True, "output": ""}
        raise AssertionError(f"unexpected gh call: {args}")

    fork_and_scrub_brief(
        "microsoft/markitdown", 183, "clean brief", "branch-x", ev,
        run_gh=fake_gh,
    )
    fork_calls = [c for c in calls if c[:2] == ["repo", "fork"]]
    assert len(fork_calls) == 1


def test_fork_retries_actions_policy_on_race(ev, monkeypatch):
    """Right after `gh repo fork`, /actions/permissions 404s for a few
    seconds. Verify the retry loop eventually succeeds and doesn't raise."""
    from temporal.activities import fork as fork_mod
    from temporal.activities.fork import fork_and_scrub_brief

    # Zero out sleep so the test doesn't actually wait seconds
    monkeypatch.setattr(fork_mod, "_FORK_RETRY_DELAYS", (0, 0, 0, 0, 0))

    policy_call_count = [0]

    def fake_gh(args, stdin_data=None):
        if args[:3] == ["api", "repos/WolffM/markitdown", "--silent"]:
            return {"success": True, "output": ""}
        if args[:2] == ["repo", "fork"]:
            return {"success": True, "output": ""}
        if len(args) >= 4 and args[1] == "repos/WolffM/markitdown" and "PATCH" in args:
            return {"success": True, "output": ""}
        if len(args) >= 4 and args[1].endswith("/actions/permissions"):
            policy_call_count[0] += 1
            # Fail first 2 attempts, succeed on 3rd — simulating GitHub
            # provisioning delay
            if policy_call_count[0] < 3:
                return {"success": False, "error": "Not Found"}
            return {"success": True, "output": ""}
        if len(args) >= 2 and args[1].endswith("/actions/workflows"):
            return {"success": True, "output": ""}
        if "/disable" in (args[1] if len(args) >= 2 else ""):
            return {"success": True, "output": ""}
        raise AssertionError(f"unexpected gh call: {args}")

    result = fork_and_scrub_brief(
        "microsoft/markitdown", 183, "brief", "b", ev, run_gh=fake_gh,
    )
    assert result["ok"] is True
    # Retry loop should have recovered
    assert policy_call_count[0] == 3
    summary = ev.read_json("02-forked/fork_safety.json")
    assert summary["actions_policy_set"] is True


def test_fork_raises_when_actions_policy_retries_exhausted(ev, monkeypatch):
    """If /actions/permissions keeps failing past all retries, we raise
    rather than proceed with an unlocked fork."""
    from temporal.activities import fork as fork_mod
    from temporal.activities.fork import fork_and_scrub_brief

    monkeypatch.setattr(fork_mod, "_FORK_RETRY_DELAYS", (0, 0, 0, 0, 0))
    monkeypatch.setattr(fork_mod, "_FORK_RETRIES", 3)

    def fake_gh(args, stdin_data=None):
        if args[:3] == ["api", "repos/WolffM/markitdown", "--silent"]:
            return {"success": True, "output": ""}
        if args[:2] == ["repo", "fork"]:
            return {"success": True, "output": ""}
        if len(args) >= 4 and args[1] == "repos/WolffM/markitdown" and "PATCH" in args:
            return {"success": True, "output": ""}
        if len(args) >= 4 and args[1].endswith("/actions/permissions"):
            return {"success": False, "error": "Not Found (persistently)"}
        raise AssertionError(f"unexpected gh call: {args}")

    with pytest.raises(RuntimeError, match="failed to set Actions policy"):
        fork_and_scrub_brief(
            "microsoft/markitdown", 183, "brief", "b", ev, run_gh=fake_gh,
        )


def test_fork_disables_inherited_workflows(ev):
    from temporal.activities.fork import fork_and_scrub_brief

    fake_gh, calls = _fake_gh_fork(include_upstream_workflows=True)
    result = fork_and_scrub_brief(
        "microsoft/markitdown", 183, "brief", "b", ev, run_gh=fake_gh,
    )

    # Enable-issues PATCH must fire on the fork root.
    issues_patch = [c for c in calls
                    if len(c) >= 4 and c[0] == "api" and c[1] == "repos/WolffM/markitdown"
                    and c[2] == "-X" and c[3] == "PATCH" and "has_issues=true" in c]
    assert len(issues_patch) == 1

    disables = [c for c in calls if len(c) >= 2 and "/disable" in c[1]]
    # Whitelist is {dynamic/copilot-swe-agent/copilot}. All 6 other
    # workflows (3 inherited .yml + codeql + dependabot + copilot-reviewer)
    # should be disabled.
    assert len(disables) == 6
    summary = ev.read_json("02-forked/fork_safety.json")
    assert summary["disabled_workflows"] == 6
    assert summary["issues_enabled"] is True
    assert summary["actions_policy_set"] is True
    assert summary["kept_workflows"] == ["dynamic/copilot-swe-agent/copilot"]
    assert result["workflows_disabled"] == 6


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


@pytest.mark.asyncio
async def test_request_fix_writes_diff_and_commits(ev, issue):
    from temporal.activities.agent import request_fix

    agent = NoopAgent()
    await request_fix(agent, issue, scrubbed_brief="fix it", evidence=ev)

    assert ev.exists("05-fixed/diff.patch")
    assert ev.exists("05-fixed/commit_shas.txt")
    assert ev.exists("05-fixed/files_touched.txt")
    assert ev.exists("05-fixed/commits.json")
    assert ev.exists("05-fixed/agent_result.json")

    diff = ev.read_text("05-fixed/diff.patch")
    assert "diff --git" in diff


@pytest.mark.asyncio
async def test_request_fix_propagates_failure(ev, issue):
    from temporal.activities.agent import request_fix

    agent = NoopAgent(diff_text="", commit_shas=[], exit_reason="error")
    result = await request_fix(agent, issue, "x", ev)
    assert result["ok"] is False
    assert result["exit_reason"] == "error"


@pytest.mark.asyncio
async def test_request_repro_writes_agent_result(ev, issue):
    from temporal.activities.agent import request_repro

    agent = NoopAgent()
    await request_repro(agent, issue, "reproduce it", ev)
    assert ev.exists("04-reproduced/agent_result.json")


@pytest.mark.asyncio
async def test_wait_and_harvest_heartbeats_during_slow_poll(ev, issue):
    """B17: the Temporal heartbeat must keep firing even when a single
    `agent.poll()` call stalls longer than the heartbeat timeout. A
    background ticker inside `_wait_and_harvest` fires every 30s
    independent of the poll loop; we prove it here by using a poll
    that blocks in the thread pool while we assert the heartbeat
    keeps ticking."""
    import asyncio as _asyncio
    from temporal.activities.agent import _wait_and_harvest

    heartbeats: list[str] = []

    def hb(detail: str) -> None:
        heartbeats.append(detail)

    class SlowAgent(NoopAgent):
        def poll(self, job):
            import time as _time
            _time.sleep(0.3)  # sync stall — simulates hung gh call
            return super().poll(job)

    # Shorten the ticker interval so the test doesn't take 30s.
    import temporal.activities.agent as agent_mod
    original_interval = agent_mod._HEARTBEAT_INTERVAL_S
    agent_mod._HEARTBEAT_INTERVAL_S = 0.05
    try:
        slow = SlowAgent(polls_until_done=1)
        job = slow.assign(issue, brief="x")
        result = await _wait_and_harvest(
            slow, job, max_polls=2, poll_interval_s=0.05, heartbeat=hb,
        )
    finally:
        agent_mod._HEARTBEAT_INTERVAL_S = original_interval

    assert result.exit_reason == "success"
    # Several ticker-driven heartbeats should have fired during the stall
    assert len(heartbeats) >= 3, f"only got {len(heartbeats)} heartbeats during stall"


@pytest.mark.asyncio
async def test_request_repro_synthesizes_notes_md_when_agent_skipped_it(ev, issue):
    """B16: if the agent didn't write notes.md, the orchestrator must
    generate a valid one so the `repro_evidence_present` gate still
    passes. Otherwise a fully-complete Copilot session gets rejected
    for a documentation miss."""
    from temporal.activities.agent import request_repro

    # NoopAgent doesn't produce notes.md and touches no files, so this
    # should fall through to the synthesis fallback.
    agent = NoopAgent()
    brief = (
        "## Repro steps\n"
        "1. Run the thing.\n"
        "2. Observe the crash.\n\n"
        "Expected: no crash.\n"
    )
    await request_repro(agent, issue, brief, ev)

    assert ev.exists("04-reproduced/notes.md")
    notes = ev.read_text("04-reproduced/notes.md")
    # All three required headings must be present (gate invariant).
    assert "## Steps to reproduce" in notes
    assert "## Observed" in notes
    assert "## Expected" in notes
    # 50-word minimum for the gate
    assert len(notes.split()) >= 50
    # Clearly attributed as auto-synthesized
    assert "Auto-synthesized" in notes


@pytest.mark.asyncio
async def test_request_repro_keeps_agent_notes_md_if_present(ev, issue, tmp_path, monkeypatch):
    """If the agent DID commit notes.md AND it passes validation, the
    synthesis fallback must not touch it — the agent's prose is always
    richer than the boilerplate."""
    from temporal.activities.agent import request_repro

    # Simulate a harvested agent result whose download step wrote notes.md
    class NotesWritingAgent(NoopAgent):
        def harvest(self, job):
            result = super().harvest(job)
            # Pretend the download step already wrote a rich notes.md
            ev.write_text(
                "04-reproduced/notes.md",
                "## Steps to reproduce\nRun x.\n\n"
                "## Observed\nIt crashed with " + ("blah " * 50) + "\n\n"
                "## Expected\nNo crash.\n",
            )
            return result

    await request_repro(NotesWritingAgent(), issue, "the brief", ev)

    notes = ev.read_text("04-reproduced/notes.md")
    assert "Auto-synthesized" not in notes  # synthesis did NOT run
    assert "Run x." in notes  # agent's content preserved


@pytest.mark.asyncio
async def test_request_repro_repairs_invalid_agent_notes_md(ev, issue):
    """B16 part 2: if the agent wrote notes.md but it misses a required
    label or is too short, prepend a canonical header that satisfies the
    gate while preserving the agent's original content in an appendix.
    Regression for v7 airflow: rich prose with plain (non-H2) labels."""
    from temporal.activities.agent import request_repro

    class BadFormatAgent(NoopAgent):
        def harvest(self, job):
            result = super().harvest(job)
            # Copilot's actual airflow v7 output — no ## prefixes
            ev.write_text(
                "04-reproduced/notes.md",
                "Steps to Reproduce\nRun a deferrable operator.\n\n"
                "observed\non_kill is not called.\n\n"
                "expected\nshould call on_kill",
            )
            return result

    await request_repro(BadFormatAgent(), issue, "airflow brief", ev)

    notes = ev.read_text("04-reproduced/notes.md")
    # Our canonical header must be present at the top
    assert "## Steps to reproduce" in notes
    assert "## Observed" in notes
    assert "## Expected" in notes
    # Agent's original content preserved below
    assert "Run a deferrable operator" in notes
    assert "Agent notes (original)" in notes


@pytest.mark.asyncio
async def test_request_verify_writes_agent_result(ev, issue):
    from temporal.activities.agent import request_verify

    agent = NoopAgent()
    await request_verify(agent, issue, "verify it", ev)
    assert ev.exists("06-verified/agent_result.json")


@pytest.mark.asyncio
async def test_request_verify_synthesizes_verify_notes_when_missing(ev, issue):
    """B20: when the agent's harvest doesn't commit a standalone
    test_output.txt or after.png (common for adopted Copilot PRs where
    tests live in the fix diff), the orchestrator writes a
    verify_notes.md summary so the gate's fallback path has something
    to accept."""
    from temporal.activities.agent import request_verify

    await request_verify(NoopAgent(), issue, "verify", ev)

    assert ev.exists("06-verified/verify_notes.md")
    notes = ev.read_text("06-verified/verify_notes.md")
    assert "Auto-synthesized" in notes
    assert "Verification basis" in notes
    # Must have enough words for the gate's 20-word minimum
    assert len(notes.split()) >= 20


@pytest.mark.asyncio
async def test_request_verify_keeps_existing_verify_notes(ev, issue):
    """If the agent (or a prior run) already wrote verify_notes.md,
    don't stomp it — the agent's content is richer than the synth."""
    from temporal.activities.agent import request_verify

    ev.write_text(
        "06-verified/verify_notes.md",
        "## Verified by running pytest\n\nAll 14 tests pass including "
        "the 3 new regression tests for the null-pointer path.",
    )

    await request_verify(NoopAgent(), issue, "verify", ev)

    notes = ev.read_text("06-verified/verify_notes.md")
    assert "Auto-synthesized" not in notes
    assert "Verified by running pytest" in notes


@pytest.mark.asyncio
async def test_request_remediation_appends_review_comments_to_brief(ev, issue):
    from temporal.activities.agent import request_remediation

    ev.write_json("07-reviewed/comments.json", [
        {"id": "c1", "severity": "blocking", "body": "fix this"},
    ])

    captured_briefs = []

    class CapturingAgent(NoopAgent):
        def assign(self, issue, brief, instruction=""):
            captured_briefs.append(brief)
            return super().assign(issue, brief=brief, instruction=instruction)

    await request_remediation(
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
    # Fixes #N is intentionally NOT in the rendered body — it gets
    # appended at submit_upstream_pr time, after the no_upstream_refs
    # gate has run on the leak-free body. See cross-ref-isolation.md.
    assert "Fixes #" not in body


def test_render_pr_body_pulls_rich_content_from_evidence(ev):
    """B21: the default render must produce a reviewable PR body with
    real problem/fix/verify content, not a skeletal checklist. v9
    submission_judge scored an empty-template body at 0.25 and aborted."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {
            "title": "Crashes when loading .xlsx with merged cells",
            "body": (
                "When opening a spreadsheet with merged cells in the header "
                "row, the parser crashes with a NullPointerException. This "
                "reproduces consistently on v1.2.3 and later."
            ),
        },
    })
    ev.write_text(
        "04-reproduced/notes.md",
        "## Steps to reproduce\n"
        "1. Create an xlsx with merged cells in row 1.\n"
        "2. Call parse_xlsx() on it.\n\n"
        "## Observed\n"
        "NullPointerException at XlsxParser.java:142 during cell coalescing "
        "because the merged-cell resolver returns null when row 0 has span > 1.\n\n"
        "## Expected\n"
        "Merged header cells should resolve to their anchor cell's value.\n",
    )
    ev.write_text("05-fixed/files_touched.txt", "src/XlsxParser.java\ntests/XlsxParserTest.java\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\ndef5678\n")
    ev.write_text("05-fixed/diff.patch", "diff --git a/x b/x\n")
    ev.write_text(
        "06-verified/test_output.txt",
        "12 tests passed including merged_header_regression",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("microsoft/markitdown", 183, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    # All four main sections present with real content
    assert "## Summary" in body
    assert "NullPointerException" in body  # from the brief
    assert "## Root cause" in body
    assert "cell coalescing" in body  # from the repro notes' Observed section
    assert "## Steps to reproduce" in body
    assert "## Fix" in body
    assert "abc1234" in body  # commit SHA
    assert "src/XlsxParser.java" in body
    assert "## Verification" in body
    assert "12 tests passed" in body

    # Body must have substance — enough words for a human reviewer to
    # evaluate. v9 argo-cd aborted with the earlier skeletal body at 0.25.
    assert len(body.split()) >= 60


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
    # Fixes #N appended at submit time, not render time
    assert "Fixes #" not in body
    assert ev.exists("09-submittable/template.json")


def test_submit_upstream_pr_writes_evidence_on_success(ev):
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "Fix x")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix\n")

    captured_body = []

    def fake_gh(args, stdin_data=None):
        if args[:2] == ["pr", "create"]:
            # Capture the --body arg for the close-keyword assertion below
            for i, a in enumerate(args):
                if a == "--body":
                    captured_body.append(args[i + 1])
                    break
            return {"success": True, "output": "https://github.com/microsoft/markitdown/pull/9999\n"}
        raise AssertionError(f"unexpected gh call: {args}")

    result = submit_upstream_pr(
        "microsoft/markitdown", "WolffM/markitdown", "fix-x", "main", ev,
        issue_number=183,
        run_gh=fake_gh,
    )
    assert result["pr_number"] == 9999
    assert "9999" in result["pr_url"]
    assert ev.read_text("10-submitted/upstream_pr_url").strip().endswith("9999")

    # The intentional close keyword was appended to the body at submit time
    # (not present in the on-disk pr_body.md, which is what no_upstream_refs scanned)
    assert len(captured_body) == 1
    assert "Fixes #183" in captured_body[0]
    assert "Fixes #183" not in ev.read_text("09-submittable/pr_body.md")


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
