"""Unit + integration tests for backend.temporal.judge — Phase 1A.7.

Per the test plan in phase-1-plan.md step 1A.7:
  - 6 unit tests (canary + parse + coerce + exception classes)
  - 1 integration test against the locally-installed `claude` CLI

The integration test fetches its own OAuth token from the vault via this
repo's service-tier key, so a plain `pytest tests/` exercises the real CLI with
no wrapper. It skips in exactly one case — the CLI says the account is out of
quota — and the skip reason carries the reset time. See its docstring for why
the old credential `skipif` was worse than no test at all.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from unittest.mock import MagicMock

import pytest

from temporal import judge as J
from temporal.config import MissingConfigError
from tests.support import vault


# ── canary unit tests ─────────────────────────────────────────────────────


def test_canary_raises_unreachable_on_nonzero_exit(monkeypatch):
    fake = MagicMock(returncode=1, stdout="", stderr="auth failed")
    monkeypatch.setattr(J, "_run_claude", lambda args, timeout, **kwargs: fake)

    with pytest.raises(J.JudgeUnreachable, match="canary exit 1"):
        J._canary_or_raise()


def test_canary_reports_stdout_when_stderr_is_empty(monkeypatch):
    """The real-world shape: `claude -p` puts its reason on stdout.

    The test above hands the canary stderr="auth failed", which is the opposite
    of how the CLI actually reports, and is why nothing caught that a genuine
    outage surfaced as a bare "canary exit 1:" with no reason attached.
    """
    fake = MagicMock(returncode=1, stdout="Credit balance is too low", stderr="")
    monkeypatch.setattr(J, "_run_claude", lambda args, timeout, **kwargs: fake)

    with pytest.raises(J.JudgeUnreachable, match="Credit balance is too low"):
        J._canary_or_raise()


def test_canary_says_so_when_both_streams_are_empty(monkeypatch):
    """Never raise a message whose reason half is blank."""
    fake = MagicMock(returncode=1, stdout="", stderr="")
    monkeypatch.setattr(J, "_run_claude", lambda args, timeout, **kwargs: fake)

    with pytest.raises(J.JudgeUnreachable, match="no output on either stream"):
        J._canary_or_raise()


def test_canary_raises_unreachable_on_timeout(monkeypatch):
    def boom(args, timeout, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["claude"], timeout=timeout)

    monkeypatch.setattr(J, "_run_claude", boom)
    with pytest.raises(J.JudgeUnreachable, match="canary timed out"):
        J._canary_or_raise()


def test_canary_raises_unreachable_when_binary_missing(monkeypatch):
    def boom(args, timeout, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(J, "_run_claude", boom)
    with pytest.raises(J.JudgeUnreachable, match="claude binary not found"):
        J._canary_or_raise()


def test_canary_raises_unreachable_on_unexpected_output(monkeypatch):
    fake = MagicMock(returncode=0, stdout="something else", stderr="")
    monkeypatch.setattr(J, "_run_claude", lambda args, timeout, **kwargs: fake)

    with pytest.raises(J.JudgeUnreachable, match="unexpected output"):
        J._canary_or_raise()


def test_canary_passes_on_ok(monkeypatch):
    fake = MagicMock(returncode=0, stdout="OK\n", stderr="")
    monkeypatch.setattr(J, "_run_claude", lambda args, timeout, **kwargs: fake)
    J._canary_or_raise()  # no raise


# ── _extract_json unit tests ──────────────────────────────────────────────


def test_extract_json_from_envelope_form():
    """`--output-format json` wraps the model text in a {result: ...} envelope."""
    rubric_json = '{"verdict": "pass", "score": 0.85, "reasoning": "looks good"}'
    text = f"Here is my analysis.\n\n```json\n{rubric_json}\n```\n"
    envelope = json.dumps({"result": text, "session_id": "abc"})

    parsed = J._extract_json(envelope)
    assert parsed == {"verdict": "pass", "score": 0.85, "reasoning": "looks good"}


def test_extract_json_from_plain_text_form():
    """Without --output-format json, stdout is plain markdown with a fenced block."""
    text = "Reasoning here.\n\n```json\n{\"verdict\": \"fail\", \"score\": 0.2, \"reasoning\": \"empty\"}\n```\n"
    parsed = J._extract_json(text)
    assert parsed["verdict"] == "fail"
    assert parsed["score"] == 0.2


def test_extract_json_raises_on_empty_stdout():
    with pytest.raises(J.JudgeParseError, match="empty stdout"):
        J._extract_json("")


def test_extract_json_raises_when_no_fenced_block():
    text = "I am just text with no fenced JSON block at all."
    with pytest.raises(J.JudgeParseError, match="no fenced"):
        J._extract_json(text)


def test_extract_json_raises_on_malformed_inside_block():
    text = "```json\n{not valid json}\n```"
    with pytest.raises(J.JudgeParseError, match="not valid JSON"):
        J._extract_json(text)


def test_extract_json_raises_on_multiple_blocks():
    text = "```json\n{\"a\": 1}\n```\n\n```json\n{\"b\": 2}\n```"
    with pytest.raises(J.JudgeParseError, match="multiple fenced"):
        J._extract_json(text)


def test_extract_json_raises_when_inner_is_not_object():
    text = "```json\n[1, 2, 3]\n```"
    with pytest.raises(J.JudgeParseError, match="must be an object"):
        J._extract_json(text)


# ── _coerce_result unit tests ─────────────────────────────────────────────


def test_coerce_result_happy_path():
    result = J._coerce_result({
        "verdict": "pass",
        "score": 0.9,
        "reasoning": "all sections present",
    })
    assert result.verdict == "pass"
    assert result.score == 0.9
    assert result.reasoning == "all sections present"
    assert result.raw["score"] == 0.9


@pytest.mark.parametrize("payload, fragment", [
    ({"verdict": "maybe", "score": 0.5, "reasoning": ""}, "invalid verdict"),
    ({"verdict": "pass", "score": "high", "reasoning": ""}, "invalid score"),
    ({"verdict": "pass", "score": 1.5, "reasoning": ""}, "out of"),
    ({"verdict": "pass", "score": 0.5, "reasoning": 123}, "reasoning"),
])
def test_coerce_result_rejects_invalid(payload, fragment):
    with pytest.raises(J.JudgeParseError, match=fragment):
        J._coerce_result(payload)


# ── score() integration with mocked subprocess ────────────────────────────


def test_score_raises_missing_config_when_token_unset(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    with pytest.raises(MissingConfigError):
        J.score("rubric text", "payload")


def test_score_full_path_with_mocked_subprocess(monkeypatch):
    """End-to-end through score() with the subprocess seam mocked."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-token")

    rubric_json = '{"verdict": "pass", "score": 0.75, "reasoning": "fine"}'
    judge_envelope = json.dumps({"result": f"Done.\n```json\n{rubric_json}\n```\n"})

    call_log = []

    def fake_run(args, timeout, **kwargs):
        call_log.append(list(args))
        if "respond with exactly: OK" in args:
            return MagicMock(returncode=0, stdout="OK\n", stderr="")
        return MagicMock(returncode=0, stdout=judge_envelope, stderr="")

    monkeypatch.setattr(J, "_run_claude", fake_run)

    result = J.score("rubric text", "payload data")
    assert result.verdict == "pass"
    assert result.score == 0.75
    assert result.reasoning == "fine"

    # Canary first, judge second
    assert len(call_log) == 2
    assert "respond with exactly: OK" in call_log[0]
    assert "--output-format" in call_log[1]


def test_run_claude_uses_utf8_encoding_on_subprocess(monkeypatch):
    """B18: Windows Python defaults subprocess.run text mode to cp1252,
    which crashes on unicode chars like `≥` that Copilot freely uses
    in diffs. The wrapper must pin encoding="utf-8"."""
    captured: dict = {}

    def fake_subprocess_run(args, **kwargs):
        captured.update(kwargs)
        return MagicMock(returncode=0, stdout="OK\n", stderr="")

    monkeypatch.setattr(J.subprocess, "run", fake_subprocess_run)
    J._run_claude(["-p", "hi"], timeout=5)

    assert captured.get("encoding") == "utf-8"
    # `errors=replace` means unicode chars in child stdout never crash
    # the parent — we'd rather lose a char than lose the whole judge call.
    assert captured.get("errors") == "replace"


def test_score_sends_prompt_via_stdin_not_argv(monkeypatch):
    """Windows CreateProcess rejects command lines > ~32KB. Large fix
    diffs blow that ceiling when passed as `-p <prompt>`. The score()
    path must send the prompt via stdin so the argv stays small.

    Regression for B14 (2026-04-20 phase-4 v5 retro).
    """
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-token")

    huge_payload = "x" * 40_000  # beyond the Windows argv ceiling
    stdin_captured = {}

    def fake_run(args, timeout, *, stdin_text=None):
        if stdin_text is None:  # canary call
            return MagicMock(returncode=0, stdout="OK\n", stderr="")
        stdin_captured["argv"] = list(args)
        stdin_captured["stdin_text"] = stdin_text
        rubric_json = '{"verdict":"pass","score":0.5,"reasoning":"ok"}'
        return MagicMock(
            returncode=0,
            stdout=json.dumps({"result": f"```json\n{rubric_json}\n```"}),
            stderr="",
        )

    monkeypatch.setattr(J, "_run_claude", fake_run)
    J.score("rubric", huge_payload)

    # Prompt went via stdin, NOT argv
    assert huge_payload in stdin_captured["stdin_text"]
    argv_joined = " ".join(stdin_captured["argv"])
    assert huge_payload not in argv_joined
    # Argv stays small regardless of payload size
    assert len(argv_joined) < 200


def test_score_unreachable_when_judge_subprocess_times_out(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-token")

    def fake_run(args, timeout, **kwargs):
        if "respond with exactly: OK" in args:
            return MagicMock(returncode=0, stdout="OK", stderr="")
        raise subprocess.TimeoutExpired(cmd=["claude"], timeout=timeout)

    monkeypatch.setattr(J, "_run_claude", fake_run)
    with pytest.raises(J.JudgeUnreachable, match="judge call timed out"):
        J.score("rubric", "payload")


def test_score_parse_error_when_judge_returns_garbage(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fake-token")

    def fake_run(args, timeout, **kwargs):
        if "respond with exactly: OK" in args:
            return MagicMock(returncode=0, stdout="OK", stderr="")
        return MagicMock(returncode=0, stdout="just prose, no fenced block", stderr="")

    monkeypatch.setattr(J, "_run_claude", fake_run)
    with pytest.raises(J.JudgeParseError):
        J.score("rubric", "payload")


def test_exception_hierarchy():
    """All judge errors derive from JudgeError so callers can catch broadly."""
    assert issubclass(J.JudgeUnreachable, J.JudgeError)
    assert issubclass(J.JudgeParseError, J.JudgeError)
    # Gates catch JudgeUnreachable and defer; quota must keep landing there.
    assert issubclass(J.JudgeQuotaExhausted, J.JudgeUnreachable)


# ── quota exhaustion is a named outcome, not a failure (#108) ────────────

# Verbatim from run 41932921976, the run that held main red.
WEEKLY_LIMIT = "You've hit your weekly limit · resets Nov 6, 3pm (America/Los_Angeles)"


@pytest.mark.parametrize("stdout, resets", [
    (WEEKLY_LIMIT, "Nov 6, 3pm (America/Los_Angeles)"),
    ("5-hour limit reached ∙ resets 3pm", "3pm"),
    ("Claude AI usage limit reached|1762470000", None),
    ('API Error: 429 {"type":"error","error":{"type":"rate_limit_error"}}', None),
])
def test_canary_names_quota_exhaustion(monkeypatch, stdout, resets):
    fake = MagicMock(returncode=1, stdout=stdout, stderr="")
    monkeypatch.setattr(J, "_run_claude", lambda args, timeout, **kwargs: fake)

    with pytest.raises(J.JudgeQuotaExhausted) as exc:
        J._canary_or_raise()
    assert exc.value.resets == resets


@pytest.mark.parametrize("stdout", [
    "auth failed",
    "Credit balance is too low",
    "Invalid API key · Please run /login",
    "",
])
def test_canary_does_not_call_other_failures_quota(monkeypatch, stdout):
    """Broken credentials, billing, or silence are things to fix: still a failure."""
    fake = MagicMock(returncode=1, stdout=stdout, stderr="")
    monkeypatch.setattr(J, "_run_claude", lambda args, timeout, **kwargs: fake)

    with pytest.raises(J.JudgeUnreachable) as exc:
        J._canary_or_raise()
    assert not isinstance(exc.value, J.JudgeQuotaExhausted)


def test_real_judge_call_names_quota_exhaustion(monkeypatch):
    """The canary can pass and the real call still hit the limit."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")

    def fake_run(args, timeout, *, stdin_text=None):
        if stdin_text is None:
            return MagicMock(returncode=0, stdout="OK", stderr="")
        return MagicMock(returncode=1, stdout=WEEKLY_LIMIT, stderr="")

    monkeypatch.setattr(J, "_run_claude", fake_run)
    with pytest.raises(J.JudgeQuotaExhausted, match="judge exit 1"):
        J.score("rubric", "payload")


def test_integration_outcome_on_weekly_limit_is_skipped_not_failed(monkeypatch):
    """The exact message that held main red becomes a skip that says when it lifts.

    Drives `_score_or_skip_on_quota`, the same call the real-CLI test makes,
    with only the subprocess faked.
    """
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    fake = MagicMock(returncode=1, stdout=WEEKLY_LIMIT, stderr="")
    monkeypatch.setattr(J, "_run_claude", lambda args, timeout, **kwargs: fake)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    with pytest.raises(pytest.skip.Exception) as exc:
        _score_or_skip_on_quota("rubric", "payload")
    assert "quota exhausted" in str(exc.value)
    assert "resets Nov 6, 3pm (America/Los_Angeles)" in str(exc.value)


@pytest.mark.parametrize("failure", [
    FileNotFoundError("claude"),
    MagicMock(returncode=1, stdout="Invalid API key · Please run /login", stderr=""),
])
def test_integration_outcome_on_broken_judge_still_fails(monkeypatch, failure):
    """A missing binary or a broken judge is not a quota skip."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")

    def fake_run(args, timeout, **kwargs):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(J, "_run_claude", fake_run)
    with pytest.raises(J.JudgeUnreachable) as exc:
        _score_or_skip_on_quota("rubric", "payload")
    assert not isinstance(exc.value, J.JudgeQuotaExhausted)


def test_quota_skip_is_written_to_the_step_summary(monkeypatch, tmp_path):
    """In Actions the reason must be visible on the run page, not only in the log."""
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    fake = MagicMock(returncode=1, stdout=WEEKLY_LIMIT, stderr="")
    monkeypatch.setattr(J, "_run_claude", lambda args, timeout, **kwargs: fake)

    with pytest.raises(pytest.skip.Exception):
        _score_or_skip_on_quota("rubric", "payload")
    assert "Nov 6, 3pm (America/Los_Angeles)" in summary.read_text()


# ── integration test against the real claude CLI ─────────────────────────


def _claude_binary() -> str:
    """Where the `claude` CLI is, or "" if it isn't installed."""
    found = shutil.which(os.environ.get("CRIMSON_CLAUDE_BIN", "claude"))
    if found:
        return found
    home_bin = os.path.expanduser("~/.npm-global/bin/claude")
    return home_bin if os.path.exists(home_bin) else ""


def _score_or_skip_on_quota(rubric: str, payload: str) -> J.JudgeResult:
    """`J.score`, except an exhausted account quota skips instead of failing.

    Quota is the one outcome no change in this repo can fix, and failing on it
    held main red from 2026-11-04 until the reset (#108). Everything else —
    missing binary, bad token, timeout, unparseable answer — still raises.
    The skip reason, and the Actions step summary, carry the reset time.
    """
    try:
        return J.score(rubric, payload)
    except J.JudgeQuotaExhausted as e:
        when = f"resets {e.resets}" if e.resets else "reset time not given"
        reason = f"Claude account quota exhausted ({when}); judge not exercised: {e}"
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"### Judge integration skipped: quota exhausted\n\n{when}.\n\n"
                        f"```\n{e}\n```\n")
        pytest.skip(reason)


@pytest.mark.real_egress
def test_score_integration_real_cli(monkeypatch):
    """Hit the real claude CLI with a tiny rubric + payload.

    Verifies the full pipeline: subprocess invocation, canary, real call, JSON
    extraction, coercion to JudgeResult. This is the only test that proves
    `score()` works against the actual CLI rather than a mocked seam, which
    makes it the one test whose absence is least visible and most expensive.

    **It used to skip when `CLAUDE_CODE_OAUTH_TOKEN` was unset, and that was
    the bug.** There are no `.env` files in this ecosystem, so the token is
    never ambiently present — it lives in the vault. The old gate therefore
    fired on the *normal* case: a plain `pytest` run skipped this silently and
    reported the same green as a run that had exercised it. The only way to
    actually run it was to remember the `dev-vault.mjs` wrapper, and a test
    that depends on the operator remembering something is a test that does not
    run.

    So it fetches its own credential now, by the intended path: the per-repo
    service-tier key in `.devvault.local.json` (or `HADOKU_VAULT_KEY`) against
    the vault broker. No wrapper, no skip. If the credential cannot be
    resolved that is a **failure** with the broker's reason attached, because
    every cause — no key, sealed vault, missing ACL grant — is something to go
    fix rather than something to shrug past.

    In CI it runs in its own `judge integration` job, not the required
    `backend pytest` check (#107): every run spends the Claude account's
    weekly quota, and an exhausted quota held the auto-merge gate red for days
    on a failure no change could fix. Locally a plain `pytest` still runs it.

    And when the quota *is* exhausted it skips, by name, with the reset time
    (#108) — see `_score_or_skip_on_quota`. That is the only skip it has.
    """
    binary = _claude_binary()
    assert binary, (
        "the `claude` CLI is not installed, so the judge cannot be exercised "
        "against anything real. Install it rather than skipping: this is the "
        "only unmocked coverage `score()` has.")

    # Fetched, not read from the environment — see the docstring. A failure
    # here carries the broker's own diagnosis (sealed / no grant / no key).
    token = vault.fetch("CLAUDE_CODE_OAUTH_TOKEN")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", token)

    # `score()` shells out, so the child needs the install path too. monkeypatch
    # rather than mutating os.environ directly — the old version leaked a PATH
    # edit into every test that ran after it.
    home_bin = os.path.dirname(binary)
    if home_bin and home_bin not in os.environ.get("PATH", ""):
        monkeypatch.setenv("PATH", home_bin + os.pathsep + os.environ.get("PATH", ""))

    rubric = """# Tiny test rubric

Score the input on a single criterion: does it contain the word "hello"?

- verdict: "pass" if hello is present, "fail" if not
- score: 1.0 if pass, 0.0 if fail
- reasoning: one short sentence

Output a fenced ```json block with keys: verdict, score, reasoning."""

    result = _score_or_skip_on_quota(rubric, "the payload says hello world")
    assert isinstance(result, J.JudgeResult)
    assert result.verdict in ("pass", "fail", "defer")
    assert 0.0 <= result.score <= 1.0
    assert isinstance(result.reasoning, str) and len(result.reasoning) > 0
