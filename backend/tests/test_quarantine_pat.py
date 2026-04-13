"""Unit tests for scripts/test_quarantine_pat.py.

The script is itself a smoke test that hits real GitHub. These unit tests
verify the *plumbing*: command construction, error handling, env routing,
and exit codes — without touching the network.
"""

import json
import os
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import test_quarantine_pat as tqp  # noqa: E402


# ── Fake gh runner ────────────────────────────────────────────────────────────


class FakeRunner:
    """Replays canned (returncode, stdout, stderr) tuples by argv pattern."""

    def __init__(self):
        self.calls: list[tuple[list[str], str]] = []
        self.fail_step: str | None = None  # set to "create" | "commit" | "delete" | "verify"
        self.created_full_name = "WolffM-temporal/_pat-canary-1700000000"

    def __call__(self, args, pat):
        self.calls.append((list(args), pat))
        joined = " ".join(args)

        if "orgs/" in joined and "/repos" in joined and "POST" in joined:
            if self.fail_step == "create":
                return (1, "", "Resource not accessible")
            return (
                0,
                json.dumps({"full_name": self.created_full_name}),
                "",
            )

        if "/contents/" in joined and "PUT" in joined:
            if self.fail_step == "commit":
                return (1, "", "401 Bad credentials")
            return (
                0,
                json.dumps({"commit": {"sha": "deadbeefcafe1234"}}),
                "",
            )

        if "DELETE" in joined and "repos/" in joined:
            if self.fail_step == "delete":
                return (1, "", "Must have admin rights")
            return (0, "", "")

        if joined.startswith("api repos/"):
            # verify_deleted: success means non-zero exit (404)
            if self.fail_step == "verify":
                return (0, '{"full_name": "still here"}', "")
            return (1, "", "Not Found (HTTP 404)")

        raise AssertionError(f"unexpected gh call: {args}")


@pytest.fixture
def fake_runner(monkeypatch):
    fake = FakeRunner()
    monkeypatch.setattr(tqp, "_run_gh", fake)
    monkeypatch.setenv(tqp.PAT_ENV_VAR, "ghp_unit_test_token")
    return fake


# ── _load_pat ─────────────────────────────────────────────────────────────────


def test_load_pat_from_env(monkeypatch):
    monkeypatch.setenv(tqp.PAT_ENV_VAR, "ghp_xyz")
    assert tqp._load_pat() == "ghp_xyz"


def test_load_pat_missing_raises(monkeypatch, tmp_path):
    monkeypatch.delenv(tqp.PAT_ENV_VAR, raising=False)
    # Point script-relative .env at a file that doesn't define the var.
    monkeypatch.chdir(tmp_path)
    with pytest.raises(tqp.CanaryError, match=tqp.PAT_ENV_VAR):
        # If a real .env happens to exist in the repo, it could provide a value.
        # Force the env path to a nonexistent file by patching __file__.
        monkeypatch.setattr(tqp, "__file__", str(tmp_path / "fake_script.py"))
        tqp._load_pat()


# ── happy path through main() ─────────────────────────────────────────────────


def test_main_success_runs_full_lifecycle(fake_runner):
    rc = tqp.main(["--org", "WolffM-temporal"])
    assert rc == 0

    sequence = [c[0][:3] for c in fake_runner.calls]
    # 1. POST orgs/.../repos
    assert sequence[0][:2] == ["api", "--method"] and sequence[0][2] == "POST"
    # 2. PUT repos/.../contents/PAT_CANARY.txt
    assert sequence[1][:2] == ["api", "--method"] and sequence[1][2] == "PUT"
    # 3. DELETE repos/...
    assert sequence[2][:2] == ["api", "--method"] and sequence[2][2] == "DELETE"
    # 4. GET repos/... (verify)
    assert sequence[3][0] == "api" and sequence[3][1].startswith("repos/")


def test_main_passes_pat_to_runner(fake_runner):
    tqp.main([])
    pats_used = {c[1] for c in fake_runner.calls}
    assert pats_used == {"ghp_unit_test_token"}


def test_main_fails_when_create_fails(fake_runner):
    fake_runner.fail_step = "create"
    rc = tqp.main([])
    assert rc == 1
    # No commit/delete/verify after the create failure.
    assert len(fake_runner.calls) == 1


def test_main_fails_when_delete_fails(fake_runner):
    fake_runner.fail_step = "delete"
    rc = tqp.main([])
    assert rc == 1
    # create + commit + delete attempt = 3 calls
    assert len(fake_runner.calls) == 3


def test_main_fails_when_verify_finds_repo_still_there(fake_runner):
    fake_runner.fail_step = "verify"
    rc = tqp.main([])
    assert rc == 1


def test_main_keep_skips_delete(fake_runner):
    rc = tqp.main(["--keep"])
    assert rc == 0
    # Only create + commit. No delete, no verify.
    assert len(fake_runner.calls) == 2


def test_main_dry_run_makes_no_calls(fake_runner):
    rc = tqp.main(["--dry-run"])
    assert rc == 0
    assert fake_runner.calls == []


def test_main_missing_pat_returns_2(monkeypatch):
    monkeypatch.delenv(tqp.PAT_ENV_VAR, raising=False)
    monkeypatch.setattr(tqp, "__file__", "/nonexistent/path/script.py")
    rc = tqp.main([])
    assert rc == 2


# ── runner integration: GH_TOKEN env injection ────────────────────────────────


def test_run_gh_injects_pat_as_gh_token(monkeypatch):
    captured: dict = {}

    def fake_subprocess_run(cmd, capture_output, text, env, check):
        captured["cmd"] = cmd
        captured["env"] = env

        class R:
            returncode = 0
            stdout = "{}"
            stderr = ""

        return R()

    monkeypatch.setattr(tqp.subprocess, "run", fake_subprocess_run)
    monkeypatch.setenv("GITHUB_TOKEN", "should_be_stripped")

    code, out, err = tqp._run_gh(["api", "user"], "ghp_real_pat")

    assert code == 0
    assert captured["cmd"][0] == "gh"
    assert captured["env"]["GH_TOKEN"] == "ghp_real_pat"
    assert "GITHUB_TOKEN" not in captured["env"]
