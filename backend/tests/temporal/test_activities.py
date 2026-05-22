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


def test_fork_creates_with_explicit_fork_name_when_slug_supplied(ev):
    """B25: when the dispatch route supplies a collision-free fork_slug
    (e.g. WolffM/home-assistant-core), fork.py MUST create the fork
    with that exact repo name using `gh repo fork --fork-name`. The
    prior code ignored the supplied name and let gh default to just the
    upstream repo name — so the rest of the pipeline looked for the
    fork at the right path but GitHub had it at a different one."""
    from temporal.activities.fork import fork_and_scrub_brief

    calls = []

    def fake_gh(args, stdin_data=None):
        calls.append(list(args))
        if "repos/WolffM/home-assistant-core" in args and "--silent" in args:
            return {"success": False, "error": "404"}  # not yet forked
        if args[:2] == ["repo", "fork"]:
            return {"success": True, "output": ""}
        if len(args) >= 2 and (
            args[1] == "repos/WolffM/home-assistant-core"
            or args[1].endswith("/actions/permissions")
            or args[1].endswith("/actions/workflows")
            or "/disable" in args[1]
        ):
            return {"success": True, "output": ""}
        raise AssertionError(f"unexpected gh call: {args}")

    fork_and_scrub_brief(
        "home-assistant/core", 167957, "brief", "fix-branch", ev,
        fork_slug="WolffM/home-assistant-core",
        run_gh=fake_gh,
    )

    fork_calls = [c for c in calls if c[:2] == ["repo", "fork"]]
    assert len(fork_calls) == 1
    fork_cmd = fork_calls[0]
    assert "--fork-name" in fork_cmd
    idx = fork_cmd.index("--fork-name")
    assert fork_cmd[idx + 1] == "home-assistant-core"
    # The source repo is still the upstream — we're not renaming upstream
    assert "home-assistant/core" in fork_cmd


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
            slow, job,
            poll_interval_s=0.05,
            no_progress_timeout_s=10.0,
            hard_ceiling_s=10.0,
            heartbeat=hb,
        )
    finally:
        agent_mod._HEARTBEAT_INTERVAL_S = original_interval

    assert result.exit_reason == "success"
    # Several ticker-driven heartbeats should have fired during the stall
    assert len(heartbeats) >= 3, f"only got {len(heartbeats)} heartbeats during stall"


@pytest.mark.asyncio
async def test_wait_and_harvest_times_out_when_progress_stalls(ev, issue):
    """The no-progress timeout should fire when the agent keeps polling
    `running` with the SAME snapshot for longer than
    `no_progress_timeout_s`. This is the pnpm class of failure: Copilot
    is wedged but heartbeats fine; the activity should bail rather than
    burn the hard ceiling."""
    from temporal.activities.agent import _wait_and_harvest
    from temporal.agents import AgentStatus
    from temporal.agents.noop import NoopAgent

    class StuckAgent(NoopAgent):
        # Always returns the same `running` snapshot — never makes progress.
        def poll(self, job):
            return AgentStatus(
                state="running", progress=0.25, last_event="stuck",
            )

    stuck = StuckAgent()
    job = stuck.assign(issue, brief="x")
    result = await _wait_and_harvest(
        stuck, job,
        poll_interval_s=0.01,
        no_progress_timeout_s=0.1,   # 100 ms — fires after a few polls
        hard_ceiling_s=10.0,
    )

    assert result.exit_reason == "timeout"
    assert "no agent progress" in result.agent_log
    assert "stuck" in result.agent_log


@pytest.mark.asyncio
async def test_wait_and_harvest_succeeds_on_slow_but_progressing_agent(ev, issue):
    """The pnpm-style scenario in reverse: an agent that takes many polls
    to finish but advances `progress` / `last_event` on each one should
    NOT time out. This is the regression guard against the old fixed
    `max_polls=90` cap that gave up on slow monorepos."""
    from temporal.activities.agent import _wait_and_harvest
    from temporal.agents import AgentStatus
    from temporal.agents.noop import NoopAgent

    class SlowProgressingAgent(NoopAgent):
        def __init__(self):
            super().__init__()
            self._n = 0

        # Fresh snapshot on every poll until `done` — staleness should
        # never accumulate.
        def poll(self, job):
            self._n += 1
            if self._n >= 50:
                return AgentStatus(
                    state="done", progress=1.0, last_event="finished",
                )
            return AgentStatus(
                state="running",
                progress=min(0.99, self._n / 50.0),
                last_event=f"commit {self._n}",
            )

    slow = SlowProgressingAgent()
    job = slow.assign(issue, brief="x")
    result = await _wait_and_harvest(
        slow, job,
        poll_interval_s=0.0,
        # Tight no-progress window: 50 ms. Each poll resets staleness.
        no_progress_timeout_s=0.05,
        hard_ceiling_s=10.0,
    )

    assert result.exit_reason == "success"
    # NoopAgent.harvest returns its canned diff
    assert result.diff_text != ""


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
    # B26: must NOT include commit SHAs in the synthesized text.
    # Reviewers want repro instructions, not pre-squash implementation
    # history. Bare hex SHAs that survive into the rendered body
    # become stale references the moment replicate_fix_as_operator
    # squashes the agent commits away.
    assert "Commit SHAs" not in notes
    # No internal vocab leaks (B16/B20 lessons).
    notes_lower = notes.lower()
    for forbidden in ("agent", "auto-synthesized", "orchestrator", "exit_reason", "copilot"):
        assert forbidden not in notes_lower, f"'{forbidden}' leaked into synthesized repro notes"


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


def test_synthesize_verify_notes_has_no_internal_language():
    """The verify-fallback content goes verbatim into the upstream PR's
    Verification section. It must not contain internal pipeline
    vocabulary — no "agent", "exit_reason", "auto-synthesized",
    "orchestrator", "copilot". User-reported regression after v13."""
    from temporal.activities.agent import _synthesize_verify_notes
    from temporal.agents import AgentResult

    # Case 1: agent did produce test files
    result = AgentResult(
        commit_shas=["abc123"],
        diff_text="diff",
        files_touched=["src/x.py", "tests/test_x.py", "src/y.py"],
        agent_log="...",
        exit_reason="success",
    )
    notes = _synthesize_verify_notes(result).lower()
    for forbidden in ("agent", "exit_reason", "auto-synthesized", "orchestrator", "copilot"):
        assert forbidden not in notes, f"'{forbidden}' in verify notes"
    # The test file is named in the notes so reviewers know what to run
    assert "tests/test_x.py" in _synthesize_verify_notes(result)

    # Case 2: agent didn't write any test files
    result_no_tests = AgentResult(
        commit_shas=["abc123"],
        diff_text="diff",
        files_touched=["src/x.py"],
        agent_log="...",
        exit_reason="timeout",
    )
    notes2 = _synthesize_verify_notes(result_no_tests).lower()
    for forbidden in ("agent", "exit_reason", "auto-synthesized", "orchestrator", "copilot", "timeout"):
        assert forbidden not in notes2, f"'{forbidden}' in verify notes (no-tests case)"


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
    to accept.

    The synthesized content is upstream-visible — the v13 user audit
    surfaced that the old synth leaked "agent" and "exit_reason" into
    the upstream PR body. The 2026-04-30 cleanup also removed the
    leading `## How this fix is verified` H2 (was producing duplicate
    headers under the parent `## Verification`) and the third-person
    "Reviewers can run..." reviewer-instruction prose. Assert the new
    shape: concrete prose, no internal vocab, no leading H2, ≥20 words
    for the gate."""
    from temporal.activities.agent import request_verify

    await request_verify(NoopAgent(), issue, "verify", ev)

    assert ev.exists("06-verified/verify_notes.md")
    notes = ev.read_text("06-verified/verify_notes.md")
    # No leading H2 — the parent `## Verification` heading is added
    # downstream in _render_default, and a duplicate would scream "AI
    # filler" to a reviewer.
    assert not notes.lstrip().startswith("##")
    # Must have enough words for the verify gate's 20-word minimum
    assert len(notes.split()) >= 20
    # NO internal pipeline vocabulary
    notes_lower = notes.lower()
    for forbidden in ("agent", "exit_reason", "auto-synthesized", "orchestrator", "copilot"):
        assert forbidden not in notes_lower, f"'{forbidden}' leaked into verify notes"
    # NO third-person reviewer-instruction prose (the flag from 2026-04-30)
    for forbidden_phrase in ("reviewers can run", "reviewers should run"):
        assert forbidden_phrase not in notes_lower, (
            f"'{forbidden_phrase}' leaked back into verify notes — "
            "third-person reviewer-instruction prose was the smell we cleaned up"
        )


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
        def assign(self, issue, brief, instruction="", *, batch_id=""):
            captured_briefs.append(brief)
            return super().assign(issue, brief=brief, instruction=instruction, batch_id=batch_id)

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


def test_read_review_summary_returns_zeros_when_missing(ev):
    """No severity_summary file → safe defaults so the workflow's
    branch decision treats it as 'no blockers' rather than aborting."""
    from temporal.activities.review import read_review_summary

    result = read_review_summary(ev)
    assert result == {"blocking": 0, "suggested": 0, "nit": 0}


def test_read_review_summary_passes_through_counts(ev):
    """Real summary file → counts surface verbatim as ints."""
    from temporal.activities.review import read_review_summary

    ev.write_json("07-reviewed/severity_summary.json",
                  {"blocking": 2, "suggested": 5, "nit": 1})
    result = read_review_summary(ev)
    assert result == {"blocking": 2, "suggested": 5, "nit": 1}


def test_read_review_summary_coerces_non_int_values(ev):
    """Defensive: malformed summary (e.g. missing keys, string counts)
    falls back to zero rather than blowing up the workflow."""
    from temporal.activities.review import read_review_summary

    ev.write_json("07-reviewed/severity_summary.json",
                  {"blocking": "3", "suggested": None})
    result = read_review_summary(ev)
    assert result["blocking"] == 3
    assert result["suggested"] == 0
    assert result["nit"] == 0


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


def test_render_pr_body_scrubs_internal_language_from_verify_notes(ev):
    """User-reported leak after v13: the synthesized verify_notes.md
    contained "the agent's PR diff", "exit_reason was success", and
    "## Commits from this agent session" — all internal pipeline
    vocabulary that must NEVER appear in an upstream-visible PR.

    The render step now strips any line containing internal terms
    (agent, exit_reason, auto-synthesized, orchestrator, harvest,
    copilot, scrubbed) before composing the Verification section.
    """
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x", "body": "y"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    # Old-style verify notes with all the leaks inline
    ev.write_text(
        "06-verified/verify_notes.md",
        "> Auto-synthesized by the orchestrator. The agent's verify phase\n"
        "> completed but did not commit a standalone test output.\n\n"
        "## Files touched in verify phase\n\nsrc/x.py\n\n"
        "## Commits from this agent session\n\n  - abc12345\n\n"
        "## Verification basis\n\n"
        "Evidence of verification lives in the agent's PR diff.\n"
        "The agent's final exit_reason was `success`.\n",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md").lower()

    # None of the internal pipeline vocabulary survives into the body
    for forbidden in ("agent", "exit_reason", "auto-synthesized", "orchestrator", "copilot"):
        assert forbidden not in body, f"'{forbidden}' leaked into PR body"


def test_render_pr_body_embeds_screenshot_when_after_url_present(ev):
    """2026-04-30: when the screenshot activity uploaded a verification
    PNG to the fork's release assets and persisted the URL to
    06-verified/after_url.txt, the rendered Verification section embeds
    `![Verification](url)` at the top — visual proof of the test run.

    Updated 2026-05-20: the agent's `verify_notes.md` is now ignored
    (recurring hand-wave phrases were leaking through). The image is
    the only signal coming out of this test fixture; the test-changes
    sentence and the test_output codeblock only fire when their inputs
    are present."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x", "body": "y"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text(
        "06-verified/after_url.txt",
        "https://github.com/WolffM/demo/releases/download/crimson-kitty-assets/issue-1-after.png\n",
    )
    # Agent verify_notes is deliberately ignored now — seeded only to
    # prove the renderer no longer reaches for it.
    ev.write_text(
        "06-verified/verify_notes.md",
        "Adds tests covering the corrected behavior:\n\n"
        "- `tests/test_x.py`\n\nThe diff is small enough to read in full.",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    assert (
        "![Verification](https://github.com/WolffM/demo/releases/download/"
        "crimson-kitty-assets/issue-1-after.png)" in body
    )
    # Agent's verify_notes content must NOT appear anywhere.
    assert "diff is small enough to read in full" not in body
    assert "Adds tests covering the corrected behavior" not in body


def test_render_pr_body_embeds_both_screenshot_and_test_output(ev):
    """Updated 2026-05-20: a screenshot does not replace the raw test
    output. The image is at-a-glance proof; the code block is what the
    submission_judge actually reads. Both render."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x", "body": "y"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text("06-verified/after_url.txt", "https://example.com/after.png\n")
    ev.write_text(
        "06-verified/test_output.txt",
        "PASS: TestExample (0.01s)\nok      example.com/foo    0.034s\n",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    assert "![Verification](https://example.com/after.png)" in body
    assert "Test output:" in body
    assert "PASS: TestExample" in body


def test_render_pr_body_falls_back_to_text_when_no_screenshot(ev):
    """No after_url.txt → existing text-only chain still works. Tests
    the absence path so the screenshot feature stays opt-in cleanly."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x", "body": "y"}})
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text(
        "06-verified/test_output.txt",
        "PASS: TestExample (0.01s)\nok      example.com/foo    0.034s\n",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    # No image embed
    assert "![Verification]" not in body
    # Test output code block IS present (the fallback path)
    assert "Test output:\n\n```" in body
    assert "PASS: TestExample" in body


def test_render_pr_body_strips_stale_commit_shas_from_repro_section(ev):
    """B26: legacy `_synthesize_repro_notes` runs embedded
    `Commit SHAs:\\n  - abc1234` blocks in the Steps to reproduce
    section. After `replicate_fix_as_operator` squashes, those SHAs
    are stale — they reference commits that no longer exist on the
    submission branch. User flagged this on v15 svelte/cli where the
    body listed `eab5c43` and `f862221`.

    The render-side scrubber strips both the `Commit SHAs:` heading
    and the bullet lines that look like bare hex SHAs. Reviewers
    don't need pre-squash commit history in Steps to reproduce."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "Some bug", "body": "There's a bug here."},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/foo.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "newsquash\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text(
        "04-reproduced/notes.md",
        "## Steps to reproduce\n\n"
        "1. Run the failing test.\n"
        "2. Observe the crash.\n"
        "Commit SHAs:\n"
        "  - eab5c43\n"
        "  - f862221\n\n"
        "## Observed\n\n"
        "It crashes loudly with " + ("noise " * 30) + "\n\n"
        "## Expected\n\n"
        "No crash.\n",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    # Stale SHAs gone
    assert "eab5c43" not in body
    assert "f862221" not in body
    assert "Commit SHAs:" not in body

    # Real Steps-to-reproduce content survives
    assert "Run the failing test" in body
    assert "Observe the crash" in body


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
    # 2026-05-20: SHA-listing dropped from the Fix section; file list stays
    # so reviewers can see scope, and the post-replicate commit message
    # (when present in commits.json) supplies the prose.
    assert "src/XlsxParser.java" in body
    assert "## Verification" in body
    assert "12 tests passed" in body

    # Body must have substance — enough words for a human reviewer to
    # evaluate. v9 argo-cd aborted with the earlier skeletal body at 0.25.
    assert len(body.split()) >= 60


def test_render_pr_body_summary_skips_issue_form_heading(ev):
    """2026-05-21: GitHub issue-forms repos (svelte, keycloak) start the
    issue body with a bare template heading (`### Describe the bug`,
    `### Description`). The naive first-paragraph extraction returned just
    that heading, so the PR Summary rendered as an empty `### Describe the
    bug` block. The summary must skip the heading and use real prose."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {
            "title": "Promote dynamic client scopes feature to preview",
            "body": (
                "### Description\n\n"
                "Promote dynamic client scopes feature to preview.\n\n"
                "### Value Proposition\n\n"
                "Allows parameterizable scopes.\n\n"
                "### Discussion\n\n_No response_\n"
            ),
        },
    })
    ev.write_text("04-reproduced/notes.md", "## Observed\nFeature stays EXPERIMENTAL.\n")
    ev.write_text("05-fixed/files_touched.txt", "common/src/main/java/Profile.java\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("keycloak/keycloak", 46523, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    # The Summary section carries the real description, not the bare heading
    assert "Promote dynamic client scopes feature to preview." in body
    # No orphaned issue-form heading leaked in as the summary content
    assert "### Description" not in body
    assert "_No response_" not in body


def test_render_pr_body_uses_fix_summary_md_for_fix_prose(ev):
    """2026-05-20: judge complained that the Fix section was always just a
    file list. Agent now writes `05-fixed/fix_summary.md` describing what
    the code change does; the renderer surfaces it as the Fix-section
    prose. When the file is absent, the section falls back to the file
    list only (no hallucinated prose)."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "Parser drops merged-cell anchors", "body": "Bug."},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/parser.py\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")
    ev.write_text(
        "05-fixed/fix_summary.md",
        "Clamped the anchor-cell lookup in `parser.py` to "
        "`max(0, anchor_row)` so the walk stays inside the merged range "
        "when row 0 has span > 1.",
    )

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")
    assert "## Fix" in body
    assert "Clamped the anchor-cell lookup" in body
    # File list still appears beneath the prose.
    assert "src/parser.py" in body


def test_render_pr_body_fix_section_omits_prose_when_summary_md_absent(ev):
    """Without `05-fixed/fix_summary.md`, the Fix section is just the
    file list — no fabricated prose. The judge will defer/fail this,
    which is the correct signal: the agent didn't produce a fix
    description."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "Bug", "body": "Body."},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")
    # Fix section present but with file list only.
    assert "## Fix" in body
    assert "src/x.py" in body
    # No phantom prose: the Files-changed line is the first content beneath
    # the Fix heading.
    _, fix_and_after = body.split("## Fix", 1)
    fix_section = fix_and_after.split("\n## ", 1)[0]
    assert "Files changed" in fix_section


def test_render_pr_body_filters_notes_md_from_displayed_files(ev):
    """The operator PR tree already strips notes.md; the rendered file
    list must match — otherwise the judge flags notes.md as unexplained
    even though it's not actually in the diff being submitted."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "Bug", "body": "Body."},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\nnotes.md\ntests/test_x.py\n")
    ev.write_text("05-fixed/diff.patch", "diff")
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")

    def fake_get(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")
    _, fix_and_after = body.split("## Fix", 1)
    fix_section = fix_and_after.split("\n## ", 1)[0]
    # Source + test file appear; notes.md does not.
    assert "src/x.py" in fix_section
    assert "tests/test_x.py" in fix_section
    assert "notes.md" not in fix_section


def test_build_title_strips_bracket_prefix_and_word_snaps(ev):
    """2026-05-20: the title renderer was emitting `[Bug] ...`-prefixed
    titles + chopping mid-word at the 80-char cap. Strip prefixes, add
    `fix:`, snap to a word boundary."""
    from temporal.activities.submission import _build_title

    assert _build_title("[Bug] Failed to load source map") == (
        "fix: Failed to load source map"
    )
    assert _build_title("[BUG]: NanoGPT Model Selector overflowing") == (
        "fix: NanoGPT Model Selector overflowing"
    )
    assert _build_title("[question] is it possible to stop parsing") == (
        "fix: is it possible to stop parsing"
    )
    # Already-conventional title is not double-prefixed.
    assert _build_title("feat: add new flag") == "feat: add new flag"
    # Long title word-snaps at the cap, with an ellipsis.
    long_in = (
        "Random sorting in GetSimilarItems (PR #14918) breaks recommendation "
        "accuracy in More Like This panel rendering"
    )
    out = _build_title(long_in)
    assert out.startswith("fix: Random sorting")
    assert out.endswith("…")
    assert len(out) <= 80
    # Title that arrives empty after stripping prefixes still produces a
    # sensible default rather than a bare `fix: `.
    assert _build_title("[Bug]") == "fix: Crimson-kitty fix"


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


def test_render_pr_body_template_path_uses_rich_default_content(ev):
    """B24: when upstream has a PR template, the rendered body must
    still carry the rich narrative from `_render_default` (real issue
    prose, repro steps, commit SHAs) — not the old skeletal "paste
    fix_summary under every heading" output. Regression for v10
    prettier/mermaid aborts at submission_judge 0.27–0.34 with
    "unfilled template placeholders" feedback.

    Also verifies the template's required headings are still present
    so `pr_template_compliance` passes.
    """
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {
            "title": "Angular: add support for comment blocks in elements",
            "body": "Prettier doesn't currently preserve HTML comment "
                    "blocks inside Angular template elements. This "
                    "breaks comment-based developer notes that ship "
                    "in component templates.",
        },
    })
    ev.write_text(
        "04-reproduced/notes.md",
        "## Steps to reproduce\n1. Format an Angular component with inline comments.\n\n"
        "## Observed\nComments are stripped from the element scope.\n\n"
        "## Expected\nComments preserved verbatim.\n",
    )
    ev.write_text("05-fixed/files_touched.txt", "src/angular/parser.js\n")
    ev.write_text("05-fixed/commit_shas.txt", "abcdef12\n")
    ev.write_text("05-fixed/diff.patch", "diff --git x y")
    ev.write_text("06-verified/test_output.txt", "42 tests passed")

    def fake_get(endpoint: str):
        return {"success": True, "data": {
            "path": ".github/PULL_REQUEST_TEMPLATE.md",
            "raw_text": "## Description\n\n<!-- please describe -->\n\n## Checklist\n- [ ] tests\n",
            "sections": [
                {"heading": "## Description", "required": True},
                {"heading": "## Checklist", "required": True},
            ],
        }}

    render_pr_body("prettier/prettier", 18974, ev, aggregator_get=fake_get)
    body = ev.read_text("09-submittable/pr_body.md")

    # Rich content from _render_default is the PRIMARY body
    assert "## Summary" in body
    assert "Prettier doesn't currently preserve" in body  # issue prose
    assert "## Root cause" in body
    assert "Comments are stripped from the element scope" in body  # repro observed
    # 2026-05-20: SHA-listing dropped from Fix section; file list still here.
    assert "src/angular/parser.js" in body
    assert "42 tests passed" in body

    # Template required headings present so pr_template_compliance passes
    assert "## Description" in body
    assert "## Checklist" in body

    # No stale raw template noise — the old code would've left "<!-- please describe -->"
    # and duplicated "Files touched" under every heading
    assert body.count("## Description") == 1
    assert body.count("## Checklist") == 1

    # Body must be substantive (previous template-path output scored 0.25-0.34)
    assert len(body.split()) >= 60


def test_replicate_fix_as_operator_squashes_and_opens_preview(ev):
    """Phase 4.5: the core re-authoring step. Agent's fix is harvested
    as a single operator-authored commit on branch_name with no lineage
    to the agent's commits, a fork-internal preview PR is opened, and
    the agent's draft is closed.

    Also verifies that after replicate runs, the operator PR's body
    reflects the new single squashed SHA in its Fix section — NOT the
    agent's pre-replicate SHAs (the leak the user surfaced after v13).
    """
    from temporal.activities.submission import replicate_fix_as_operator

    # Seed evidence the way the upstream activities would write it
    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {
            "number": 183,
            "title": "Fix the merged-cell bug",
            "body": "Spreadsheet anchors get dropped on import.",
        },
    })
    ev.write_json("05-fixed/agent_result.json", {
        "pr_url": "https://github.com/WolffM/demo/pull/7",
        "commit_shas": ["botA", "botB"],
        "files_touched": ["src/x.py", "tests/test_x.py"],
        "diff_bytes": 100,
        "exit_reason": "success",
    })
    ev.write_json("05-fixed/commits.json", [
        {"sha": "botA", "message": "Initial plan"},
        {"sha": "botB", "message": "Fix it"},
    ])
    ev.write_text("05-fixed/commit_shas.txt", "botA\nbotB\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\ntests/test_x.py\n")
    ev.write_text("09-submittable/pr_title.txt", "Fix the merged-cell bug")
    ev.write_text(
        "09-submittable/pr_body.md",
        "## Summary\n\nThe converter drops merged-cell anchors.\n\n"
        "## Root cause\n\nThe parser skips merged ranges.\n",
    )

    calls: list[tuple[list, str | None]] = []

    def fake_gh(args, stdin_data=None):
        calls.append((list(args), stdin_data))

        # GET pulls/7 detail
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "--jq" in args:
            return {"success": True, "output": '{"head_ref":"copilot/x","head_sha":"BOT_HEAD_SHA","base_ref":"main"}'}
        # GET commit tree sha
        if "git/commits/BOT_HEAD_SHA" in args[1] if len(args) > 1 else False:
            return {"success": True, "output": "BOT_TREE_SHA\n"}
        # GET tree root entries (notes.md strip pre-pass — 2026-04-30)
        if args[1] == "repos/WolffM/demo/git/trees/BOT_TREE_SHA" and "--jq" in args:
            # No notes.md in the tree — strip should be a no-op
            return {"success": True, "output": '["src/x.py", "tests/test_x.py"]'}
        # GET base ref sha
        if args[1] == "repos/WolffM/demo/git/refs/heads/main" and "--jq" in args:
            return {"success": True, "output": "BASE_HEAD_SHA\n"}
        # POST git/commits — return the new squashed commit
        if args[1] == "repos/WolffM/demo/git/commits" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"sha":"NEW_SQUASH_SHA"}'}
        # Ref existence check — simulate branch doesn't exist yet
        if args[1] == "repos/WolffM/demo/git/refs/heads/crimson-kitty-183" and "--silent" in args:
            return {"success": False, "error": "404"}
        # POST git/refs — create branch ref
        if args[1] == "repos/WolffM/demo/git/refs" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"ref":"refs/heads/crimson-kitty-183"}'}
        # GET pulls?state=open&head=... — stale-preview-PR audit (2026-05-21)
        if (
            args[:2] == ["api"][:1] + [args[1]]
            and "pulls?state=open&head=" in args[1]
        ):
            return {"success": True, "output": "[]"}
        # POST pulls — open operator PR
        if args[1] == "repos/WolffM/demo/pulls" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"number":42,"html_url":"https://github.com/WolffM/demo/pull/42"}'}
        # PATCH pulls/7 — close agent draft
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "-X" in args and "PATCH" in args:
            return {"success": True, "output": "{}"}
        raise AssertionError(f"unexpected gh call: {args}")

    def fake_aggregator_get(endpoint: str):
        # Upstream has no PR template — render_pr_body uses _render_default
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    result = replicate_fix_as_operator(
        upstream_slug="upstream/demo",
        fork_slug="WolffM/demo",
        branch_name="crimson-kitty-183",
        evidence=ev,
        run_gh=fake_gh,
        aggregator_get=fake_aggregator_get,
    )

    # Returned metadata
    assert result["ok"] is True
    assert result["operator_pr_number"] == 42
    assert result["operator_pr_url"] == "https://github.com/WolffM/demo/pull/42"
    assert result["squashed_commit_sha"] == "NEW_SQUASH_SHA"
    assert result["agent_pr_closed"] == 7

    # The new commit's parent is the fork default HEAD, tree matches the
    # agent's final tree, and the agent's commit SHAs are NOT in the parents
    create_commit_calls = [
        (a, s) for a, s in calls
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/commits" and "POST" in a
    ]
    assert len(create_commit_calls) == 1
    import json as _json
    commit_payload = _json.loads(create_commit_calls[0][1])
    assert commit_payload["tree"] == "BOT_TREE_SHA"
    assert commit_payload["parents"] == ["BASE_HEAD_SHA"]
    assert "BOT_HEAD_SHA" not in commit_payload["parents"]  # lineage severed
    assert "Fix the merged-cell bug" in commit_payload["message"]

    # Evidence: commits.json now has only the new squashed commit, and
    # the agent's original commits are archived for audit.
    new_commits = ev.read_json("05-fixed/commits.json")
    assert new_commits == [{"sha": "NEW_SQUASH_SHA", "message": commit_payload["message"]}]
    agent_archive = ev.read_json("05-fixed/agent_original_commits.json")
    assert {c["sha"] for c in agent_archive} == {"botA", "botB"}

    # Operator PR URL + number persisted
    assert ev.read_text("09-submittable/operator_pr_url") == "https://github.com/WolffM/demo/pull/42"
    assert ev.read_text("09-submittable/operator_pr_number").strip() == "42"

    # The agent's draft was closed (PATCH state:closed)
    close_calls = [
        (a, s) for a, s in calls
        if a[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "PATCH" in a
    ]
    assert len(close_calls) == 1
    assert _json.loads(close_calls[0][1])["state"] == "closed"

    # Operator PR body must reflect the SQUASHED commit, not stale
    # agent SHAs. Regression for the v13 leak the user surfaced.
    open_pr_calls = [
        (a, s) for a, s in calls
        if a[1] == "repos/WolffM/demo/pulls" and "POST" in a
    ]
    assert len(open_pr_calls) == 1
    op_pr_body = _json.loads(open_pr_calls[0][1])["body"]

    # Stale agent SHAs must NOT appear in the operator PR body. The Fix
    # section no longer carries the squashed commit message as prose
    # (that just restated the Summary) — prose now comes from an agent-
    # written `05-fixed/fix_summary.md`, absent in this test. The leak-
    # prevention promise still holds: agent SHAs botA/botB don't appear,
    # and `commits.json` is rewritten to only the new squashed commit.
    assert "botA" not in op_pr_body
    assert "botB" not in op_pr_body
    # Sanity: the file list is still present so the operator can see scope.
    assert "src/x.py" in op_pr_body

    # No internal pipeline language can leak into the upstream-visible body
    body_lower = op_pr_body.lower()
    for forbidden in ("agent", "exit_reason", "auto-synthesized", "orchestrator", "copilot"):
        assert forbidden not in body_lower, f"internal term '{forbidden}' leaked into operator PR body"

    # commit_shas.txt is also rewritten so submit_upstream_pr (later)
    # doesn't re-render with stale data
    new_shas = ev.read_text("05-fixed/commit_shas.txt").strip()
    assert new_shas == "NEW_SQUASH_SHA"
    assert ev.exists("05-fixed/agent_original_commit_shas.txt")


def test_replicate_closes_stale_branch_prs_before_opening_new(ev):
    """Audit 2026-05-21 fix: if a prior batch left an open operator preview
    PR on the same head branch, replicate must close it before opening a
    fresh one — otherwise the operator sees two PRs on one branch."""
    from temporal.activities.submission import replicate_fix_as_operator

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"number": 183, "title": "Fix X", "body": "broken"},
    })
    ev.write_json("05-fixed/agent_result.json", {
        "pr_url": "https://github.com/WolffM/demo/pull/7",
        "commit_shas": ["bot1"],
        "files_touched": ["src/x.py"],
        "diff_bytes": 50,
        "exit_reason": "success",
    })
    ev.write_json("05-fixed/commits.json", [{"sha": "bot1", "message": "fix"}])
    ev.write_text("05-fixed/commit_shas.txt", "bot1\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("09-submittable/pr_title.txt", "Fix X")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nbroken thing\n")

    closed_prs: list[int] = []

    def fake_gh(args, stdin_data=None):
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "--jq" in args:
            return {"success": True, "output": '{"head_ref":"copilot/x","head_sha":"H","base_ref":"main"}'}
        if len(args) > 1 and "git/commits/H" in args[1]:
            return {"success": True, "output": "T\n"}
        if args[1] == "repos/WolffM/demo/git/trees/T" and "--jq" in args:
            return {"success": True, "output": '["src/x.py"]'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/main" and "--jq" in args:
            return {"success": True, "output": "BASE\n"}
        if args[1] == "repos/WolffM/demo/git/commits" and "POST" in args:
            return {"success": True, "output": '{"sha":"NEW"}'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/crimson-kitty-183" and "--silent" in args:
            return {"success": False, "error": "404"}
        if args[1] == "repos/WolffM/demo/git/refs" and "POST" in args:
            return {"success": True, "output": '{}'}
        # Stale-PR lookup returns one open PR (#99) on the head branch
        if "pulls?state=open&head=WolffM:crimson-kitty-183" in args[1]:
            return {"success": True, "output": "[99]"}
        # PATCH /pulls/99 — the stale one being closed
        if args[:2] == ["api", "repos/WolffM/demo/pulls/99"] and "PATCH" in args:
            closed_prs.append(99)
            return {"success": True, "output": "{}"}
        if args[1] == "repos/WolffM/demo/pulls" and "POST" in args:
            return {"success": True, "output": '{"number":100,"html_url":"https://github.com/WolffM/demo/pull/100"}'}
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "PATCH" in args:
            return {"success": True, "output": "{}"}
        raise AssertionError(f"unexpected gh call: {args}")

    def fake_agg(endpoint):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    result = replicate_fix_as_operator(
        upstream_slug="upstream/demo",
        fork_slug="WolffM/demo",
        branch_name="crimson-kitty-183",
        evidence=ev,
        run_gh=fake_gh,
        aggregator_get=fake_agg,
    )

    assert result["operator_pr_number"] == 100
    # The stale PR #99 from a prior batch was closed before #100 was opened
    assert closed_prs == [99]


# ── Phase 5.3 — per-repo contribution conventions ────────────────────────


def _conventions_envelope(**overrides) -> dict:
    """Build a {success, data} envelope shaped like the aggregator's
    /recon/{slug}/contribution-conventions response."""
    refs_override = overrides.pop("references", None) or {}
    base = {
        "commit_style": "freeform",
        "title_prefix_pattern": None,
        "signoff_required": False,
        "body_structure": [],
        "references": {
            "close_keyword": "Fixes",
            "syntax": "Fixes #N",
            "in_body": True,
            **refs_override,
        },
        "evidence": {"source": "default", "raw_excerpt": None},
    }
    base.update(overrides)
    return {"success": True, "data": base}


def test_render_pr_body_prepends_conventional_prefix(ev):
    """Phase 5.3 acceptance: a conventional-commits repo gets `fix:`
    prepended to the PR title."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "Crashes when loading merged xlsx", "body": "x"},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc1234\n")
    ev.write_text("05-fixed/diff.patch", "diff")

    def fake_get(endpoint: str):
        if "contribution-conventions" in endpoint:
            return _conventions_envelope(commit_style="conventional")
        if "pr-template" in endpoint:
            return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    render_pr_body("microsoft/terminal", 1, ev, aggregator_get=fake_get)
    title = ev.read_text("09-submittable/pr_title.txt")
    assert title.startswith("fix: "), title
    # Conventions persisted to evidence
    assert ev.exists("09-submittable/contribution_conventions.json")
    cached = ev.read_json("09-submittable/contribution_conventions.json")
    assert cached["commit_style"] == "conventional"


def test_render_pr_body_skips_prefix_when_already_present(ev):
    """Idempotent: if the issue title already has a conventional prefix,
    don't double-prefix it."""
    from temporal.activities.submission import render_pr_body

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"title": "feat: add new flag", "body": "x"},
    })
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")
    ev.write_text("05-fixed/diff.patch", "diff")

    def fake_get(endpoint: str):
        if "contribution-conventions" in endpoint:
            return _conventions_envelope(commit_style="conventional")
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    render_pr_body("a/b", 1, ev, aggregator_get=fake_get)
    title = ev.read_text("09-submittable/pr_title.txt")
    assert title.startswith("feat: "), title
    assert not title.startswith("fix: feat:")


def test_replicate_strips_notes_md_from_squashed_tree(ev):
    """2026-04-30: `notes.md` is a pipeline-internal scratch file the
    agent commits at repo root for the `repro_evidence_present` gate.
    It belongs in evidence (`04-reproduced/notes.md`), NOT in the
    upstream-bound diff. `replicate_fix_as_operator` must build a
    delta tree that strips `notes.md` from the agent's tree before
    creating the operator commit, so the upstream maintainer never
    sees the leak.

    Surfaced after the strapi + gofiber operator preview PRs leaked
    `notes.md` into their diffs.
    """
    from temporal.activities.submission import replicate_fix_as_operator

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"number": 5, "title": "Fix it", "body": "Bug."},
    })
    ev.write_json("05-fixed/agent_result.json", {
        "pr_url": "https://github.com/WolffM/demo/pull/9",
        "commit_shas": ["botA"],
        "files_touched": ["src/x.py"],
        "diff_bytes": 100,
        "exit_reason": "success",
    })
    ev.write_json("05-fixed/commits.json", [{"sha": "botA", "message": "Fix"}])
    ev.write_text("05-fixed/commit_shas.txt", "botA\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("09-submittable/pr_title.txt", "Fix it")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix.\n")

    captured: list[tuple[list, str | None]] = []

    def fake_gh(args, stdin_data=None):
        captured.append((list(args), stdin_data))

        if args[:2] == ["api", "repos/WolffM/demo/pulls/9"] and "--jq" in args:
            return {"success": True, "output": '{"head_ref":"x","head_sha":"BOT_HEAD","base_ref":"main"}'}
        if "git/commits/BOT_HEAD" in (args[1] if len(args) > 1 else ""):
            return {"success": True, "output": "OLD_TREE\n"}
        # Tree root listing INCLUDES notes.md → must be stripped
        if args[1] == "repos/WolffM/demo/git/trees/OLD_TREE" and "--jq" in args:
            return {"success": True, "output": '["src/x.py", "notes.md", "tests/test_x.py"]'}
        # POST git/trees → return a NEW tree sha that the squash should use
        if args[1] == "repos/WolffM/demo/git/trees" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"sha":"STRIPPED_TREE"}'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/main" and "--jq" in args:
            return {"success": True, "output": "BASE_SHA\n"}
        if args[1] == "repos/WolffM/demo/git/commits" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"sha":"NEW_SHA"}'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/op-branch" and "--silent" in args:
            return {"success": False, "error": "404"}
        if args[1] == "repos/WolffM/demo/git/refs" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"ref":"refs/heads/op-branch"}'}
        if args[1] == "repos/WolffM/demo/pulls" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"number":42,"html_url":"https://github.com/WolffM/demo/pull/42"}'}
        if args[:2] == ["api", "repos/WolffM/demo/pulls/9"] and "PATCH" in args:
            return {"success": True, "output": "{}"}
        return {"success": True, "output": "{}"}

    def fake_aggregator(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    replicate_fix_as_operator(
        upstream_slug="upstream/demo", fork_slug="WolffM/demo",
        branch_name="op-branch", evidence=ev,
        run_gh=fake_gh, aggregator_get=fake_aggregator,
    )

    # Assert the strip POST happened with the right payload
    strip_calls = [
        (a, s) for a, s in captured
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/trees" and "POST" in a
    ]
    assert len(strip_calls) == 1, "expected exactly one POST git/trees to strip notes.md"
    strip_payload = json.loads(strip_calls[0][1])
    assert strip_payload["base_tree"] == "OLD_TREE"
    assert strip_payload["tree"] == [
        {"path": "notes.md", "mode": "100644", "type": "blob", "sha": None}
    ]

    # Assert the squashed commit was built against the STRIPPED tree
    create_commit = [
        (a, s) for a, s in captured
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/commits" and "POST" in a
    ]
    assert len(create_commit) == 1
    commit_payload = json.loads(create_commit[0][1])
    assert commit_payload["tree"] == "STRIPPED_TREE", (
        "operator commit should reference the stripped tree, not the "
        "agent's original tree containing notes.md"
    )


def test_replicate_no_strip_when_notes_md_absent(ev):
    """If the agent didn't commit notes.md, no POST git/trees should
    happen — we don't want a no-op API call on every replicate. The
    squash commit just uses the original tree directly."""
    from temporal.activities.submission import replicate_fix_as_operator

    ev.write_json("01-eligible/issue_brief.json", {
        "issue": {"number": 5, "title": "Fix it", "body": "Bug."},
    })
    ev.write_json("05-fixed/agent_result.json", {
        "pr_url": "https://github.com/WolffM/demo/pull/9",
        "commit_shas": ["botA"], "files_touched": ["src/x.py"],
        "diff_bytes": 100, "exit_reason": "success",
    })
    ev.write_json("05-fixed/commits.json", [{"sha": "botA", "message": "Fix"}])
    ev.write_text("05-fixed/commit_shas.txt", "botA\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("09-submittable/pr_title.txt", "Fix it")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix.\n")

    captured: list[tuple[list, str | None]] = []

    def fake_gh(args, stdin_data=None):
        captured.append((list(args), stdin_data))
        if args[:2] == ["api", "repos/WolffM/demo/pulls/9"] and "--jq" in args:
            return {"success": True, "output": '{"head_ref":"x","head_sha":"BOT_HEAD","base_ref":"main"}'}
        if "git/commits/BOT_HEAD" in (args[1] if len(args) > 1 else ""):
            return {"success": True, "output": "CLEAN_TREE\n"}
        # No notes.md in this tree
        if args[1] == "repos/WolffM/demo/git/trees/CLEAN_TREE" and "--jq" in args:
            return {"success": True, "output": '["src/x.py", "tests/test_x.py"]'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/main" and "--jq" in args:
            return {"success": True, "output": "BASE_SHA\n"}
        if args[1] == "repos/WolffM/demo/git/commits" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"sha":"NEW_SHA"}'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/op-branch" and "--silent" in args:
            return {"success": False, "error": "404"}
        if args[1] == "repos/WolffM/demo/git/refs" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"ref":"refs/heads/op-branch"}'}
        if args[1] == "repos/WolffM/demo/pulls" and "-X" in args and "POST" in args:
            return {"success": True, "output": '{"number":42,"html_url":"https://github.com/WolffM/demo/pull/42"}'}
        if args[:2] == ["api", "repos/WolffM/demo/pulls/9"] and "PATCH" in args:
            return {"success": True, "output": "{}"}
        return {"success": True, "output": "{}"}

    def fake_aggregator(endpoint: str):
        return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}

    replicate_fix_as_operator(
        upstream_slug="upstream/demo", fork_slug="WolffM/demo",
        branch_name="op-branch", evidence=ev,
        run_gh=fake_gh, aggregator_get=fake_aggregator,
    )

    # No POST git/trees should happen
    strip_calls = [
        (a, s) for a, s in captured
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/trees" and "POST" in a
    ]
    assert len(strip_calls) == 0, "no notes.md present → no strip POST should happen"

    # Squashed commit uses the original tree
    create_commit = [
        (a, s) for a, s in captured
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/commits" and "POST" in a
    ]
    assert len(create_commit) == 1
    commit_payload = json.loads(create_commit[0][1])
    assert commit_payload["tree"] == "CLEAN_TREE"


def test_replicate_appends_signoff_when_dco_required(ev):
    """Phase 5.3 acceptance: a DCO-required upstream → squash commit
    carries `Signed-off-by: <name> <email>`."""
    from temporal.activities.submission import replicate_fix_as_operator

    # Pre-seed conventions with DCO required so the activity reads from
    # cache rather than calling the aggregator
    ev.write_json("09-submittable/contribution_conventions.json",
                  _conventions_envelope(signoff_required=True)["data"])
    # Issue brief for the internal render_pr_body call
    ev.write_json("01-eligible/issue_brief.json",
                  {"issue": {"number": 1, "title": "Fix the bug", "body": "x"}})
    # Standard agent-result + render scaffolding
    ev.write_json("05-fixed/agent_result.json", {
        "pr_url": "https://github.com/WolffM/demo/pull/7",
        "commit_shas": ["botA"], "files_touched": ["src/x.py"],
        "diff_bytes": 100, "exit_reason": "success",
    })
    ev.write_json("05-fixed/commits.json", [{"sha": "botA", "message": "Initial"}])
    ev.write_text("05-fixed/commit_shas.txt", "botA\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("09-submittable/pr_title.txt", "Fix the bug")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFixes the bug.\n")

    captured: list[tuple[list, str | None]] = []

    def fake_gh(args, stdin_data=None):
        captured.append((list(args), stdin_data))
        if args[:2] == ["api", "user"] and "--jq" in args:
            return {"success": True, "output": json.dumps({
                "name": "Test Operator", "login": "testop", "email": "test@example.com",
            })}
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "--jq" in args:
            return {"success": True, "output": '{"head_ref":"x","head_sha":"BOT_HEAD","base_ref":"main"}'}
        if "git/commits/BOT_HEAD" in (args[1] if len(args) > 1 else ""):
            return {"success": True, "output": "BOT_TREE\n"}
        if args[1] == "repos/WolffM/demo/git/refs/heads/main":
            return {"success": True, "output": "BASE_SHA\n"}
        if args[1] == "repos/WolffM/demo/git/commits" and "POST" in args:
            return {"success": True, "output": '{"sha":"NEW_SHA"}'}
        if args[1] == "repos/WolffM/demo/git/refs/heads/operator-branch" and "--silent" in args:
            return {"success": False, "error": "404"}
        if args[1] == "repos/WolffM/demo/git/refs" and "POST" in args:
            return {"success": True, "output": '{"ref":"refs/heads/operator-branch"}'}
        if args[1] == "repos/WolffM/demo/pulls" and "POST" in args:
            return {"success": True, "output": '{"number":42,"html_url":"https://github.com/WolffM/demo/pull/42"}'}
        if args[:2] == ["api", "repos/WolffM/demo/pulls/7"] and "PATCH" in args:
            return {"success": True, "output": "{}"}
        return {"success": True, "output": "{}"}

    def fake_aggregator(endpoint: str):
        # render_pr_body still calls pr-template
        if "pr-template" in endpoint:
            return {"success": True, "data": {"path": None, "raw_text": None, "sections": []}}
        if "contribution-conventions" in endpoint:
            return _conventions_envelope(signoff_required=True)
        return {"success": True, "data": {}}

    replicate_fix_as_operator(
        upstream_slug="upstream/demo", fork_slug="WolffM/demo",
        branch_name="operator-branch", evidence=ev,
        run_gh=fake_gh, aggregator_get=fake_aggregator,
    )

    create_commit = [
        (a, s) for a, s in captured
        if len(a) > 1 and a[1] == "repos/WolffM/demo/git/commits" and "POST" in a
    ]
    assert len(create_commit) == 1
    payload = json.loads(create_commit[0][1])
    assert "Signed-off-by: Test Operator <test@example.com>" in payload["message"]


def test_submit_upstream_pr_omits_close_keyword_when_in_body_false(ev):
    """Phase 5.3 acceptance: a repo whose CONTRIBUTING.md says "do not
    include Fixes in body" → submit_upstream_pr does NOT append the
    close keyword to the body."""
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "Fix the bug")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix.\n")
    ev.write_json("09-submittable/contribution_conventions.json",
                  _conventions_envelope(references={"in_body": False})["data"])

    captured_body: list[str] = []

    def fake_gh(args, stdin_data=None):
        if args[:2] == ["pr", "create"]:
            for i, a in enumerate(args):
                if a == "--body":
                    captured_body.append(args[i + 1])
                    break
            return {"success": True, "output": "https://github.com/u/r/pull/100\n"}
        raise AssertionError(f"unexpected gh call: {args}")

    submit_upstream_pr(
        "u/r", "WolffM/r", "branch", "main", ev,
        issue_number=42, run_gh=fake_gh,
    )

    assert len(captured_body) == 1
    assert "Fixes #42" not in captured_body[0]
    assert "Closes #42" not in captured_body[0]
    assert "## Summary" in captured_body[0]


def test_submit_upstream_pr_uses_custom_close_keyword(ev):
    """A `Resolves #N`-style upstream → footer uses Resolves, not Fixes."""
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "Fix the bug")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix.\n")
    ev.write_json("09-submittable/contribution_conventions.json",
                  _conventions_envelope(references={
                      "close_keyword": "Resolves",
                      "syntax": "Resolves #N",
                      "in_body": True,
                  })["data"])

    captured_body: list[str] = []

    def fake_gh(args, stdin_data=None):
        if args[:2] == ["pr", "create"]:
            for i, a in enumerate(args):
                if a == "--body":
                    captured_body.append(args[i + 1])
                    break
            return {"success": True, "output": "https://github.com/u/r/pull/100\n"}
        raise AssertionError(f"unexpected gh call: {args}")

    submit_upstream_pr(
        "u/r", "WolffM/r", "branch", "main", ev,
        issue_number=42, run_gh=fake_gh,
    )

    assert len(captured_body) == 1
    assert "Resolves #42" in captured_body[0]
    assert "Fixes #42" not in captured_body[0]


def test_load_conventions_falls_back_to_defaults_on_aggregator_failure(ev):
    """Defensive: aggregator outage / 5xx → activities use safe defaults
    (freeform, Fixes #N, no signoff) rather than crashing the workflow."""
    from temporal.activities.submission import _load_conventions

    def failing_aggregator(endpoint: str):
        return None  # simulating _call_aggregator's None-on-error contract

    result = _load_conventions(ev, failing_aggregator, "any/repo")
    assert result["commit_style"] == "freeform"
    assert result["signoff_required"] is False
    assert result["references"]["close_keyword"] == "Fixes"
    assert result["references"]["in_body"] is True
    # Persisted to evidence so subsequent activities see the same defaults
    assert ev.exists("09-submittable/contribution_conventions.json")


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


def test_submit_upstream_pr_reads_live_fork_preview_when_present(ev):
    """Phase 4.5 — when `09-submittable/operator_pr_number` is recorded
    (the operator-signoff flow), submit_upstream_pr fetches the LIVE
    title and body from the fork preview PR via gh api. The operator
    may have edited the preview between submittable gates passing and
    signaling approve; their edits MUST flow upstream verbatim."""
    from temporal.activities.submission import submit_upstream_pr

    # Stale evidence — the operator edited the live PR after this was written
    ev.write_text("09-submittable/pr_title.txt", "Stale title from before edits")
    ev.write_text("09-submittable/pr_body.md", "Stale rendered body.")
    # The replicate step records the fork preview PR number
    ev.write_text("09-submittable/operator_pr_number", "42")

    captured_create = []
    edited_title = "Operator's edited title — much better"
    edited_body = (
        "## Summary\n\nThe operator added a screenshot and tightened the\n"
        "repro narrative here. This is the source of truth for upstream.\n"
    )

    def fake_gh(args, stdin_data=None):
        # Live preview PR fetch
        if (
            len(args) > 1 and args[0] == "api"
            and "/pulls/42" in args[1] and "--jq" in args
        ):
            return {
                "success": True,
                "output": json.dumps({"title": edited_title, "body": edited_body}),
            }
        if args[:2] == ["pr", "create"]:
            captured_create.append(list(args))
            return {"success": True, "output": "https://github.com/u/r/pull/77\n"}
        raise AssertionError(f"unexpected gh call: {args}")

    result = submit_upstream_pr(
        "u/r", "WolffM/r", "branch", "main", ev,
        issue_number=99,
        run_gh=fake_gh,
    )
    assert result["pr_number"] == 77

    # The upstream PR was created with the LIVE title + body, not the
    # stale evidence-file content
    assert len(captured_create) == 1
    create_args = captured_create[0]
    title_idx = create_args.index("--title")
    body_idx = create_args.index("--body")
    assert create_args[title_idx + 1] == edited_title
    submitted_body = create_args[body_idx + 1]
    assert "operator added a screenshot" in submitted_body
    # Stale content must NOT appear
    assert "Stale title from before edits" not in submitted_body
    assert "Stale rendered body." not in submitted_body
    # Close keyword still appended at submit time
    assert "Fixes #99" in submitted_body


def test_submit_upstream_pr_blocks_when_operator_edit_introduces_upstream_ref(ev):
    """Defense in depth: an operator who pastes an upstream URL into the
    fork preview PR's body must NOT bypass the no_upstream_refs gate
    just because that gate already ran before signoff. submit_upstream_pr
    re-scans the live content right before opening the upstream PR."""
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "Fix x")
    ev.write_text("09-submittable/pr_body.md", "x")
    ev.write_text("09-submittable/operator_pr_number", "42")
    ev.write_json("01-eligible/issue_brief.json", {"issue": {"number": 100, "title": "Fix"}})

    leaky_body = (
        "## Summary\n\nOperator added context: see "
        "https://github.com/upstream/repo/issues/100 — same as that issue.\n"
    )

    def fake_gh(args, stdin_data=None):
        if (
            len(args) > 1 and args[0] == "api"
            and "/pulls/42" in args[1] and "--jq" in args
        ):
            return {
                "success": True,
                "output": json.dumps({"title": "Fix x", "body": leaky_body}),
            }
        if args[:2] == ["pr", "create"]:
            raise AssertionError("gh pr create must NOT run when sanitizer trips")
        return {"success": True, "output": "{}"}

    with pytest.raises(RuntimeError, match="upstream ref"):
        submit_upstream_pr(
            "upstream/repo", "WolffM/repo", "branch", "main", ev,
            issue_number=100,
            run_gh=fake_gh,
        )


def test_submit_upstream_pr_edits_existing_upstream_pr_on_remediation(ev):
    """Phase 5.1: when 10-submitted/upstream_pr_number is already recorded
    (i.e. this is a remediation cycle), submit_upstream_pr does NOT call
    `gh pr create` — it calls `gh pr edit` to refresh the existing
    upstream PR's title/body. The branch was already force-pushed by
    replicate_fix_as_operator, so GitHub auto-refreshes the diff."""
    from temporal.activities.submission import submit_upstream_pr

    # Stale evidence + recorded existing upstream PR + recorded operator preview
    ev.write_text("09-submittable/pr_title.txt", "stale title")
    ev.write_text("09-submittable/pr_body.md", "stale body")
    ev.write_text("09-submittable/operator_pr_number", "42")
    ev.write_text("10-submitted/upstream_pr_number", "888")
    ev.write_text("10-submitted/upstream_pr_url", "https://github.com/u/r/pull/888")

    edited_title = "Operator's refined title (after remediation)"
    edited_body = "## Summary\n\nAddressed maintainer's feedback on src/x.py.\n"

    captured_edit: list[list[str]] = []

    def fake_gh(args, stdin_data=None):
        if (
            len(args) > 1 and args[0] == "api"
            and "/pulls/42" in args[1] and "--jq" in args
        ):
            return {
                "success": True,
                "output": json.dumps({"title": edited_title, "body": edited_body}),
            }
        if args[:2] == ["pr", "create"]:
            raise AssertionError("must not call `gh pr create` on remediation re-submit")
        if args[:2] == ["pr", "edit"]:
            captured_edit.append(list(args))
            return {"success": True, "output": ""}
        raise AssertionError(f"unexpected gh call: {args}")

    result = submit_upstream_pr(
        "u/r", "WolffM/r", "branch", "main", ev,
        issue_number=999,
        run_gh=fake_gh,
    )

    assert result["pr_number"] == 888
    assert result["updated"] is True
    assert "888" in result["pr_url"]

    assert len(captured_edit) == 1
    edit_args = captured_edit[0]
    assert edit_args[2] == "888"  # the existing upstream PR number
    title_idx = edit_args.index("--title")
    body_idx = edit_args.index("--body")
    assert edit_args[title_idx + 1] == edited_title
    submitted_body = edit_args[body_idx + 1]
    assert "Addressed maintainer's feedback" in submitted_body
    # Close keyword still appended at submit time
    assert "Fixes #999" in submitted_body
    # Stale evidence content NOT used
    assert "stale title" not in submitted_body
    assert "stale body" not in submitted_body


def test_submit_upstream_pr_raises_on_failure(ev):
    from temporal.activities.submission import submit_upstream_pr

    ev.write_text("09-submittable/pr_title.txt", "x")
    ev.write_text("09-submittable/pr_body.md", "y")

    def fake_gh(args, stdin_data=None):
        return {"success": False, "error": "pr already exists"}

    with pytest.raises(RuntimeError, match="gh pr create failed"):
        submit_upstream_pr("u/r", "WolffM/r", "b", "main", ev, run_gh=fake_gh)


# ── watcher activity ──────────────────────────────────────────────────────


def test_watch_upstream_pr_state_open_no_changes(ev):
    """Healthy poll on an open PR with no new reviews: ok=True, no
    terminal flags, all_seen_review_ids unchanged."""
    from temporal.activities.watchers import watch_upstream_pr_state

    def fake_gh(args, stdin_data=None):
        if "pulls/9" in args[1] and "/reviews" not in args[1]:
            return {
                "success": True,
                "output": json.dumps({
                    "state": "open", "merged": False,
                    "merged_at": None, "merge_commit_sha": None,
                    "closed_at": None, "merged_by": None,
                    "closed_by_login": None,
                }),
            }
        if "/reviews" in args[1]:
            return {"success": True, "output": json.dumps([])}
        raise AssertionError(f"unexpected gh call: {args}")

    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [], ev,
        run_gh=fake_gh,
        is_bot=lambda l: False,
        notify=lambda m: None,
    )
    assert result["ok"] is True
    assert result["state"] == "open"
    assert result["merged"] is False
    assert result["closed_unmerged"] is False
    assert result["new_blocking_review"] is False
    assert result["all_seen_review_ids"] == []


def test_watch_upstream_pr_state_detects_merged(ev):
    """A merged PR returns merged=True with merge_sha + writes 11-merged/."""
    from temporal.activities.watchers import watch_upstream_pr_state

    def fake_gh(args, stdin_data=None):
        if "pulls/9" in args[1] and "/reviews" not in args[1]:
            return {
                "success": True,
                "output": json.dumps({
                    "state": "closed", "merged": True,
                    "merged_at": "2026-04-26T12:00:00Z",
                    "merge_commit_sha": "abc1234deadbeef",
                    "closed_at": None,
                    "merged_by": "maintainer",
                    "closed_by_login": "operator",
                }),
            }
        if "/reviews" in args[1]:
            return {"success": True, "output": json.dumps([])}
        raise AssertionError(f"unexpected gh call: {args}")

    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [], ev,
        run_gh=fake_gh, is_bot=lambda l: False, notify=lambda m: None,
    )
    assert result["merged"] is True
    assert result["merge_sha"] == "abc1234deadbeef"
    assert result["closed_unmerged"] is False
    # Terminal evidence written
    assert ev.exists("11-merged/merge_info.json")
    assert ev.read_text("11-merged/merge_sha") == "abc1234deadbeef"
    info = ev.read_json("11-merged/merge_info.json")
    assert info["merge_sha"] == "abc1234deadbeef"
    assert info["pr_number"] == 9


def test_watch_upstream_pr_state_detects_closed_unmerged(ev):
    """A closed-without-merge PR returns closed_unmerged=True + writes
    11-closed_by_upstream/."""
    from temporal.activities.watchers import watch_upstream_pr_state

    def fake_gh(args, stdin_data=None):
        if "pulls/9" in args[1] and "/reviews" not in args[1]:
            return {
                "success": True,
                "output": json.dumps({
                    "state": "closed", "merged": False,
                    "merged_at": None, "merge_commit_sha": None,
                    "closed_at": "2026-04-26T13:00:00Z",
                    "merged_by": None,
                    "closed_by_login": "grumpy-maintainer",
                }),
            }
        if "/reviews" in args[1]:
            return {"success": True, "output": json.dumps([])}
        raise AssertionError(f"unexpected gh call: {args}")

    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [], ev,
        run_gh=fake_gh, is_bot=lambda l: False, notify=lambda m: None,
    )
    assert result["closed_unmerged"] is True
    assert result["merged"] is False
    assert ev.exists("11-closed_by_upstream/close_info.json")
    info = ev.read_json("11-closed_by_upstream/close_info.json")
    assert info["closed_at"] == "2026-04-26T13:00:00Z"


def test_watch_upstream_pr_state_flags_new_blocking_review(ev):
    """A new CHANGES_REQUESTED review from a non-bot user → new_blocking_review=True."""
    from temporal.activities.watchers import watch_upstream_pr_state

    notifications: list[str] = []

    def fake_gh(args, stdin_data=None):
        if "pulls/9" in args[1] and "/reviews" not in args[1]:
            return {
                "success": True,
                "output": json.dumps({
                    "state": "open", "merged": False,
                    "merged_at": None, "merge_commit_sha": None,
                    "closed_at": None, "merged_by": None,
                    "closed_by_login": None,
                }),
            }
        if "/reviews" in args[1]:
            return {
                "success": True,
                "output": json.dumps([
                    {"id": 100, "user": "bot[bot]", "state": "CHANGES_REQUESTED",
                     "body": "auto-flagged", "submitted_at": "2026-04-26T10:00Z"},
                    {"id": 200, "user": "alice", "state": "COMMENTED",
                     "body": "looks good", "submitted_at": "2026-04-26T10:30Z"},
                    {"id": 300, "user": "bob", "state": "CHANGES_REQUESTED",
                     "body": "needs work on src/x.py", "submitted_at": "2026-04-26T11:00Z"},
                ]),
            }
        raise AssertionError(f"unexpected gh call: {args}")

    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [], ev,
        run_gh=fake_gh,
        is_bot=lambda l: "[bot]" in l.lower(),
        notify=lambda m: notifications.append(m),
    )
    # Bob's CHANGES_REQUESTED is the blocking one (bot's filtered out, alice is COMMENTED)
    assert result["new_blocking_review"] is True
    assert result["new_blocking_review_id"] == 300
    assert result["new_blocking_review_user"] == "bob"
    # all_seen_review_ids includes both new ids (bot, alice, bob)
    assert set(result["all_seen_review_ids"]) == {100, 200, 300}
    # Discord notification fired with blocking-review marker
    assert len(notifications) == 1
    assert "BLOCKING" in notifications[0]


def test_watch_upstream_pr_state_dedupes_seen_reviews(ev):
    """Reviews already in seen_review_ids don't re-fire."""
    from temporal.activities.watchers import watch_upstream_pr_state

    def fake_gh(args, stdin_data=None):
        if "pulls/9" in args[1] and "/reviews" not in args[1]:
            return {
                "success": True,
                "output": json.dumps({
                    "state": "open", "merged": False,
                    "merged_at": None, "merge_commit_sha": None,
                    "closed_at": None, "merged_by": None,
                    "closed_by_login": None,
                }),
            }
        if "/reviews" in args[1]:
            return {
                "success": True,
                "output": json.dumps([
                    {"id": 300, "user": "bob", "state": "CHANGES_REQUESTED",
                     "body": "needs work", "submitted_at": "2026-04-26T11:00Z"},
                ]),
            }
        raise AssertionError(f"unexpected gh call: {args}")

    # 300 was already seen — shouldn't re-fire
    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [300], ev,
        run_gh=fake_gh, is_bot=lambda l: False, notify=lambda m: None,
    )
    assert result["new_blocking_review"] is False
    assert result["all_seen_review_ids"] == [300]


def test_watch_upstream_pr_state_returns_ok_false_on_pr_fetch_failure(ev):
    """Transient gh failure → ok=False, error populated, no terminal flags."""
    from temporal.activities.watchers import watch_upstream_pr_state

    def fake_gh(args, stdin_data=None):
        return {"success": False, "error": "503 service unavailable"}

    result = watch_upstream_pr_state(
        "microsoft/markitdown", 9, [], ev,
        run_gh=fake_gh, is_bot=lambda l: False, notify=lambda m: None,
    )
    assert result["ok"] is False
    assert "503" in (result["error"] or "")
    assert result["merged"] is False
    assert result["closed_unmerged"] is False
    assert result["new_blocking_review"] is False


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
        notify=lambda m, **kw: notifications.append((m, kw)),
    )

    entry = ev.read_json("awaiting/inbox_entry.json")
    assert entry["state"] == "fixed"
    assert entry["gate"] == "relevance"
    assert entry["score"] == 0.55
    assert ev.exists("awaiting/queued_at")
    assert len(notifications) == 1
    msg, kw = notifications[0]
    assert "183" in msg
    # Deep-link URL is computed from evidence.root; the test fixture's
    # evidence path encodes batch+issue ids that should appear in the URL.
    assert "view=temporal" in kw["url"]


def test_enqueue_for_human_review_swallows_notify_errors(ev):
    from temporal.activities.inbox import enqueue_for_human_review

    def boom(message: str, **kw):
        raise RuntimeError("discord down")

    # Should not raise — notification failure is best-effort
    result = enqueue_for_human_review(
        "fixed", "relevance", "x", 0.5, "x/y", 1, ev, notify=boom,
    )
    assert result["ok"] is True
    assert ev.exists("awaiting/inbox_entry.json")
