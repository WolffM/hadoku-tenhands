"""the fork + scrub-brief activity

Split out of the 2217-line `test_activities.py`, which vibeCompact flagged at
its top size tier. The cut follows the `# ── ... activity ──` banners that
file already carried, so one module covers one activity. Shared `issue` and
`ev` fixtures live in conftest.py.
"""

from __future__ import annotations

import json

import pytest

def _fake_gh_fork(include_upstream_workflows=True):
    """Build a fake gh runner that handles fork existence + safety-config calls.

    Simulated workflow listing includes three inherited (`.github/workflows/*.yml`),
    three auto-provisioned dynamic/* (codeql, dependabot, copilot-reviewer), and
    the copilot-swe-agent — the single workflow we keep. Models stateful
    disable so the post-disable verification re-list reflects actual state.
    """
    calls = []
    disabled_ids: set[str] = set()
    workflow_rows = [
        ("1", ".github/workflows/test-matrix.yml"),
        ("2", ".github/workflows/ci.yml"),
        ("3", ".github/workflows/release.yml"),
        ("4", "dynamic/github-code-scanning/codeql"),
        ("5", "dynamic/dependabot/dependabot-updates"),
        ("6", "dynamic/copilot-pull-request-reviewer/copilot-pull-request-reviewer"),
        ("7", "dynamic/copilot-swe-agent/copilot"),
    ]

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
        # Workflow list — reflects current disabled set
        if len(args) >= 2 and args[1].endswith("/actions/workflows"):
            if include_upstream_workflows:
                rows = [
                    f"{wid}\t{path}\t{'disabled_manually' if wid in disabled_ids else 'active'}"
                    for wid, path in workflow_rows
                ]
                return {"success": True, "output": "\n".join(rows)}
            return {"success": True, "output": ""}
        # Workflow disable — record the ID so the next list call reflects it
        if len(args) >= 2 and "/disable" in args[1]:
            # path: api repos/.../actions/workflows/{id}/disable
            wid = args[1].rsplit("/", 2)[-2]
            disabled_ids.add(wid)
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


def test_fork_raises_if_workflow_listing_fails(ev):
    """Silent failure here previously skipped the disable step entirely —
    fork got pushed to with inherited workflows still active, billing
    GitHub-hosted runner minutes (cli-cli + crewAIInc 2026-05-29). Now
    must abort the dispatch loudly."""
    from temporal.activities.fork import fork_and_scrub_brief

    def fake_gh(args, stdin_data=None):
        if args[:3] == ["api", "repos/WolffM/markitdown", "--silent"]:
            return {"success": True, "output": ""}
        if args[:2] == ["repo", "fork"]:
            return {"success": True, "output": ""}
        if (len(args) >= 4 and args[1] == "repos/WolffM/markitdown" and "PATCH" in args):
            return {"success": True, "output": ""}
        if len(args) >= 4 and args[1].endswith("/actions/permissions"):
            return {"success": True, "output": ""}
        if len(args) >= 2 and args[1].endswith("/actions/workflows"):
            return {"success": False, "error": "API down", "output": ""}
        raise AssertionError(f"unexpected gh call: {args}")

    with pytest.raises(RuntimeError, match="failed to list workflows"):
        fork_and_scrub_brief(
            "microsoft/markitdown", 183, "brief", "b", ev, run_gh=fake_gh,
        )


def test_fork_raises_if_individual_disable_fails(ev):
    """A single 422/403 on /workflows/{id}/disable used to be silently
    ignored — the workflow stayed active and fired on push. Now any
    disable failure aborts the dispatch."""
    from temporal.activities.fork import fork_and_scrub_brief

    def fake_gh(args, stdin_data=None):
        if args[:3] == ["api", "repos/WolffM/markitdown", "--silent"]:
            return {"success": True, "output": ""}
        if args[:2] == ["repo", "fork"]:
            return {"success": True, "output": ""}
        if (len(args) >= 4 and args[1] == "repos/WolffM/markitdown" and "PATCH" in args):
            return {"success": True, "output": ""}
        if len(args) >= 4 and args[1].endswith("/actions/permissions"):
            return {"success": True, "output": ""}
        if len(args) >= 2 and args[1].endswith("/actions/workflows"):
            return {"success": True, "output":
                "1\t.github/workflows/test-matrix.yml\tactive\n"
                "7\tdynamic/copilot-swe-agent/copilot\tactive"}
        if len(args) >= 2 and "/disable" in args[1]:
            return {"success": False, "error": "HTTP 422", "output": ""}
        raise AssertionError(f"unexpected gh call: {args}")

    with pytest.raises(RuntimeError, match="failed to disable .* inherited workflow"):
        fork_and_scrub_brief(
            "microsoft/markitdown", 183, "brief", "b", ev, run_gh=fake_gh,
        )


def test_fork_raises_if_verification_finds_non_keep_still_active(ev):
    """Even if every disable call returned 200, the verification pass
    re-lists workflows and aborts if any non-keep is still active.
    Catches the GitHub-eventual-consistency case where disable succeeds
    but state hasn't propagated, or a workflow re-enables itself."""
    from temporal.activities.fork import fork_and_scrub_brief

    def fake_gh(args, stdin_data=None):
        if args[:3] == ["api", "repos/WolffM/markitdown", "--silent"]:
            return {"success": True, "output": ""}
        if args[:2] == ["repo", "fork"]:
            return {"success": True, "output": ""}
        if (len(args) >= 4 and args[1] == "repos/WolffM/markitdown" and "PATCH" in args):
            return {"success": True, "output": ""}
        if len(args) >= 4 and args[1].endswith("/actions/permissions"):
            return {"success": True, "output": ""}
        # List: always returns the same workflows as active (disable
        # claimed success but didn't propagate, or a workflow auto-re-enabled).
        if len(args) >= 2 and args[1].endswith("/actions/workflows"):
            return {"success": True, "output":
                "1\t.github/workflows/test-matrix.yml\tactive\n"
                "7\tdynamic/copilot-swe-agent/copilot\tactive"}
        if len(args) >= 2 and "/disable" in args[1]:
            return {"success": True, "output": ""}  # claims success — lie
        raise AssertionError(f"unexpected gh call: {args}")

    with pytest.raises(RuntimeError, match="verification failed:.*still active"):
        fork_and_scrub_brief(
            "microsoft/markitdown", 183, "brief", "b", ev, run_gh=fake_gh,
        )
