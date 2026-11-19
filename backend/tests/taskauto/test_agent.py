"""Tests for temporal/taskauto/agent.py.

The environment-scrubbing tests are the important ones. The tenhands process
holds the vault key, the board key and GitHub tokens; a subprocess inherits
all of it by default, and the agent has no business seeing any of it.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from temporal.taskauto.agent import (
    ENV_ALLOWLIST,
    AgentError,
    AgentRun,
    AgentUnavailable,
    ClaudeCodeAgent,
    scrubbed_env,
)


@pytest.fixture(autouse=True)
def _leases(crossposter):
    """Every run here leases from a stand-in crossposter (tests/support)."""
    return crossposter


class FakeGit:
    def __init__(self, status="", diff=""):
        self.status, self.diff = status, diff
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        out = self.status if "status" in args else self.diff

        class R:
            ok = True
        R.out = out
        return R


def agent(status="", diff="", run=None):
    return ClaudeCodeAgent(run=run or (lambda *a, **k: AgentRun(True, "done")),
                           git=FakeGit(status, diff))


# ── environment containment ───────────────────────────────────────────────


SECRETS = {
    "HADOKU_SERVICE_KEY": "board-key",
    "TENHANDS_ADMIN_KEY": "admin-key",
    "SAML_ORG_TOKEN": "saml-token",
    "HADOKU_SITE_TOKEN": "site",
    "GH_TOKEN": "gh",
    "GITHUB_TOKEN": "gh2",
    "AWS_SECRET_ACCESS_KEY": "aws",
}


@pytest.mark.parametrize("name", sorted(SECRETS))
def test_secrets_never_reach_the_agent(monkeypatch, name):
    """A subprocess inherits the whole environment by default, and this
    process holds credentials for the vault, the board and GitHub."""
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    assert name not in scrubbed_env()


def test_a_claude_token_in_the_environment_never_reaches_the_agent(monkeypatch):
    """Its credential is the leased one, passed in per run (#115)."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in scrubbed_env()


def test_the_agent_gets_enough_to_run(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/x")
    env = scrubbed_env()
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/x"


def test_it_is_an_allow_list_not_a_deny_list(monkeypatch):
    """A deny-list silently leaks whatever someone adds later. This must
    fail closed, so an unknown variable is absent by construction."""
    monkeypatch.setenv("SOME_FUTURE_CREDENTIAL", "oops")
    assert "SOME_FUTURE_CREDENTIAL" not in scrubbed_env()
    assert set(scrubbed_env()) <= set(ENV_ALLOWLIST)


def test_extra_values_can_be_injected_explicitly(monkeypatch):
    assert scrubbed_env({"EXTRA": "1"})["EXTRA"] == "1"


def test_the_run_receives_the_scrubbed_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "ambient")
    seen = {}

    def fake_run(args, cwd, timeout, env, stdin_text=None):
        seen.update(env=env, cwd=cwd, args=args, prompt=stdin_text)
        return AgentRun(True, "ok")

    a = ClaudeCodeAgent(run=fake_run, git=FakeGit())
    a.work(tmp_path, "do the thing")
    assert "HADOKU_SERVICE_KEY" not in seen["env"]
    # The leased token, never one the environment happened to hold.
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-matth2"


# ── it runs in the checkout, with the prompt on stdin ─────────────────────


def test_runs_inside_the_given_checkout(tmp_path):
    seen = {}

    def fake_run(args, cwd, timeout, env, stdin_text=None):
        seen["cwd"] = cwd
        return AgentRun(True)

    ClaudeCodeAgent(run=fake_run, git=FakeGit()).work(tmp_path, "p")
    assert seen["cwd"] == tmp_path


def test_prompt_goes_on_stdin_not_argv(tmp_path):
    """Large prompts blow past argv limits; the judge already learned this."""
    seen = {}

    def fake_run(args, cwd, timeout, env, stdin_text=None):
        seen.update(args=args, prompt=stdin_text)
        return AgentRun(True)

    ClaudeCodeAgent(run=fake_run, git=FakeGit()).work(tmp_path, "x" * 50000)
    assert seen["prompt"] == "x" * 50000
    assert not any(len(a) > 1000 for a in seen["args"])


# ── measuring the tree, not believing the agent ───────────────────────────


def test_changed_files_come_from_git_not_the_agents_summary():
    """An agent reporting a fix it didn't make is the most common failure
    crimson-kitty found. The only defence that works is reading the tree."""
    a = agent(status=" M backend/app.py\n?? new_file.py\n",
              run=lambda *x, **k: AgentRun(True, "I changed everything!"))
    out = a.work(Path("/tmp"), "p")
    assert out.changed_files == ["backend/app.py", "new_file.py"]


def test_no_changes_is_reported_honestly():
    out = agent(status="").work(Path("/tmp"), "p")
    assert out.changed_files == [] and out.made_changes is False


def test_a_chatty_agent_that_changed_nothing_still_reports_nothing():
    a = agent(status="", run=lambda *x, **k: AgentRun(True, "Fixed it!"))
    assert a.work(Path("/tmp"), "p").made_changes is False


def test_quoted_paths_with_spaces_are_parsed():
    out = agent(status=' M "src/some file.ts"\n').work(Path("/tmp"), "p")
    assert out.changed_files == ["src/some file.ts"]


def test_the_diff_is_captured():
    out = agent(status=" M a.py", diff="--- a/a.py\n+++ b/a.py\n").work(Path("/tmp"), "p")
    assert "+++ b/a.py" in out.diff


# ── timeouts ──────────────────────────────────────────────────────────────


def test_timeout_is_reported_but_changes_are_still_harvested():
    """An agent killed mid-run may have made real edits. Discarding them
    silently would be worse than reporting both facts."""
    a = agent(status=" M a.py",
              run=lambda *x, **k: AgentRun(False, "", "timed out", timed_out=True))
    out = a.work(Path("/tmp"), "p")
    assert out.timed_out is True
    assert out.changed_files == ["a.py"]


def test_log_is_truncated_so_notes_stay_readable():
    a = agent(run=lambda *x, **k: AgentRun(True, "y" * 100000))
    assert len(a.work(Path("/tmp"), "p").log) <= 20000


# ── a failed process is never an answer ───────────────────────────────────
#
# The regression these pin is 2026-08-08: a revoked CLAUDE_CODE_OAUTH_TOKEN
# made `claude -p` exit 1 in 3.5s having printed its 401 to STDOUT, with
# stderr empty. `ask` checked only for a timeout and for empty output, so the
# error text became the plan, parsed to an empty document, and was published
# to a human as "no action proposed" by a run that reported success.

AUTH_401 = "Failed to authenticate. API Error: 401 OAuth access token has been revoked."


def test_a_failed_planning_process_is_not_a_plan():
    a = agent(run=lambda *x, **k: AgentRun(False, AUTH_401))
    with pytest.raises(AgentUnavailable):
        a.ask(Path("/tmp"), "p")


def test_the_auth_error_never_reaches_the_caller_as_content():
    """The specific shape that broke: non-empty stdout on a non-zero exit."""
    a = agent(run=lambda *x, **k: AgentRun(False, AUTH_401, ""))
    with pytest.raises(AgentUnavailable) as e:
        a.ask(Path("/tmp"), "p")
    assert "401" in str(e.value)


def test_an_unusable_agent_is_distinguishable_from_a_bad_task():
    """AgentUnavailable must be catchable on its own — the runner aborts the
    whole sweep for it and merely stalls one task for AgentError."""
    assert issubclass(AgentUnavailable, AgentError)
    a = agent(run=lambda *x, **k: AgentRun(True, "   "))
    with pytest.raises(AgentError) as e:
        a.ask(Path("/tmp"), "p")
    assert not isinstance(e.value, AgentUnavailable)


def test_a_planning_timeout_is_the_tasks_problem_not_the_pipelines():
    a = agent(run=lambda *x, **k: AgentRun(False, "", "", timed_out=True))
    with pytest.raises(AgentError) as e:
        a.ask(Path("/tmp"), "p")
    assert not isinstance(e.value, AgentUnavailable)


def test_a_successful_plan_still_comes_back():
    a = agent(run=lambda *x, **k: AgentRun(True, "## Plan\n\n1. do it\n"))
    assert "## Plan" in a.ask(Path("/tmp"), "p")


def test_implementing_with_a_dead_agent_is_not_declining_to_change_anything():
    """`work` measures the tree, and an empty tree reads as "the agent read
    the plan and decided against it" — which stalls the task and blames a
    human for a credential nobody replaced."""
    a = agent(status="", run=lambda *x, **k: AgentRun(False, AUTH_401))
    with pytest.raises(AgentUnavailable):
        a.work(Path("/tmp"), "p")


def test_a_failed_agent_that_edited_something_still_reports_its_work():
    """It got far enough to have an opinion; the gates judge the diff."""
    a = agent(status=" M a.py", run=lambda *x, **k: AgentRun(False, "crashed late"))
    assert a.work(Path("/tmp"), "p").changed_files == ["a.py"]


def test_an_oom_kill_is_this_tasks_pathology_not_an_outage():
    """One task blowing the memory ceiling must not red-flag the pipeline."""
    a = agent(status="", run=lambda *x, **k: AgentRun(
        False, "", "killed: exceeded 12G", out_of_memory=True))
    assert a.work(Path("/tmp"), "p").made_changes is False


def test_a_timeout_that_changed_nothing_is_still_only_a_timeout():
    a = agent(status="", run=lambda *x, **k: AgentRun(
        False, "", "timed out", timed_out=True))
    assert a.work(Path("/tmp"), "p").timed_out is True


# ── the lease: a spent account hands the task to the next ─────────────────

from temporal.taskauto.agent import AgentQuotaExhausted  # noqa: E402

WEEKLY = "You've hit your weekly limit · resets Nov 18, 3pm (America/Los_Angeles)"


def by_token(outcomes):
    """A fake run whose result depends on which leased token it was handed."""
    seen = []

    def run(args, cwd, timeout, env, stdin_text=None):
        tok = env.get("CLAUDE_CODE_OAUTH_TOKEN")
        seen.append(tok)
        return outcomes[tok]
    return run, seen


def test_a_good_run_reports_ok(crossposter):
    agent().ask(Path("/tmp"), "p")
    assert crossposter.outcomes == [{"account": "matth2", "outcome": "ok"}]


def test_each_run_takes_its_own_lease(crossposter):
    a = agent(run=lambda *x, **k: AgentRun(True, "## Plan\n"))
    a.ask(Path("/tmp"), "p")
    a.ask(Path("/tmp"), "p")
    assert len({x["lease_id"] for x in crossposter.leases}) == 2


def test_planning_moves_to_the_account_crossposter_names_when_one_is_spent(crossposter):
    run, seen = by_token({"tok-matth2": AgentRun(False, WEEKLY),
                          "tok-matth": AgentRun(True, "## Plan\n")})
    assert "## Plan" in agent(run=run).ask(Path("/tmp"), "p")
    assert seen == ["tok-matth2", "tok-matth"]
    assert crossposter.outcomes == [{"account": "matth2", "outcome": "rate_limited"},
                                    {"account": "matth", "outcome": "ok"}]


def test_a_revoked_token_is_reported_and_the_work_still_runs(crossposter):
    run, seen = by_token({"tok-matth2": AgentRun(False, AUTH_401),
                          "tok-matth": AgentRun(True, "done")})
    git = FakeGit()

    def edits_when_it_works(*args, **kwargs):
        res = run(*args, **kwargs)
        if res.ok:
            git.status = " M f.py"
        return res
    out = ClaudeCodeAgent(run=edits_when_it_works, git=git).work(Path("/tmp"), "p")
    assert out.changed_files == ["f.py"]
    assert seen == ["tok-matth2", "tok-matth"]
    assert crossposter.outcomes[0] == {"account": "matth2", "outcome": "unauthorized"}


def test_a_half_edited_tree_is_not_handed_to_another_account(crossposter):
    """The run stopped mid-task; a second agent on top of its edits would
    produce a diff neither of them meant."""
    run, seen = by_token({"tok-matth2": AgentRun(False, WEEKLY),
                          "tok-matth": AgentRun(True, "done")})
    out = agent(status=" M half.py", run=run).work(Path("/tmp"), "p")
    assert seen == ["tok-matth2"]
    assert out.changed_files == ["half.py"]
    # Still reported, so the next run starts on a working account.
    assert crossposter.outcomes == [{"account": "matth2", "outcome": "rate_limited"}]


def test_a_task_failure_is_not_blamed_on_the_account(crossposter):
    run, seen = by_token({"tok-matth2": AgentRun(False, "error: something odd"),
                          "tok-matth": AgentRun(True, "## Plan\n")})
    with pytest.raises(AgentUnavailable):
        agent(run=run).ask(Path("/tmp"), "p")
    assert seen == ["tok-matth2"]
    assert crossposter.outcomes == [{"account": "matth2", "outcome": "error"}]
    assert crossposter.benched == {}


def test_every_account_out_of_quota_is_waiting_not_broken(crossposter):
    resets = int(time.time()) + 3600
    spent = AgentRun(False, f"Claude AI usage limit reached|{resets}")
    run, seen = by_token({t: spent for t in crossposter.accounts.values()})
    with pytest.raises(AgentQuotaExhausted) as e:
        agent(run=run).ask(Path("/tmp"), "p")
    assert e.value.earliest == resets
    assert seen == ["tok-matth2", "tok-matth", "tok-james"]
    # And with all of them benched, crossposter leases nothing and nothing runs.
    with pytest.raises(AgentQuotaExhausted):
        agent(run=run).ask(Path("/tmp"), "p")
    assert len(seen) == 3


def test_every_account_rejected_is_an_outage(crossposter):
    run, _ = by_token({t: AgentRun(False, AUTH_401) for t in crossposter.accounts.values()})
    with pytest.raises(AgentUnavailable) as e:
        agent(run=run).ask(Path("/tmp"), "p")
    assert not isinstance(e.value, AgentQuotaExhausted)


def test_without_the_grant_nothing_runs_and_the_reason_says_why(crossposter):
    crossposter.refuse = 403
    run, seen = by_token({})
    with pytest.raises(AgentUnavailable, match="crossposter-claude-code-lease"):
        agent(run=run).ask(Path("/tmp"), "p")
    assert seen == []


def test_crossposter_down_is_an_outage_with_no_fallback_to_the_environment(monkeypatch):
    """No silent fallback: a token in the environment is never used instead."""
    monkeypatch.setenv("TENHANDS_CROSSPOSTER_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "ambient")
    monkeypatch.setenv("CLAUDE_OAUTH_TOKEN_MATTH", "ambient-pool")
    run, seen = by_token({})
    with pytest.raises(AgentUnavailable, match="unreachable"):
        agent(run=run).ask(Path("/tmp"), "p")
    assert seen == []
