"""Tests for the test-command synthesizer.

Covers the language × test-file fallback that fills in 05-fixed/test_command.txt
when Copilot doesn't commit one (the common case).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from temporal.activities.test_command_synthesizer import (
    synthesize_test_command_if_missing,
    _is_test_file,
    _pick_test_file,
    _build_command,
)
from temporal.evidence.store import EvidenceStore


@pytest.fixture
def ev(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "issue")


def _setup(ev, *, language: str | None, files_touched: list[str] | None,
           existing_command: str | None = None):
    """Fill in the evidence inputs the synthesizer reads."""
    if language is not None:
        ev.write_text("01-eligible/health.json",
                      json.dumps({"language": language, "slug": "x/y"}))
    if files_touched is not None:
        ev.write_text("05-fixed/files_touched.txt",
                      "\n".join(files_touched) + "\n")
    if existing_command is not None:
        ev.write_text("05-fixed/test_command.txt", existing_command)


def test_existing_command_is_left_alone(ev):
    """If Copilot did commit a command, the synthesizer respects it."""
    _setup(ev, language="Python",
           files_touched=["tests/test_foo.py"],
           existing_command="pytest tests/test_foo.py -v\n")

    result = synthesize_test_command_if_missing(ev)
    assert result is None
    assert ev.read_text("05-fixed/test_command.txt") == "pytest tests/test_foo.py -v\n"


def test_python_synthesis(ev):
    """pytest invocation pointing at the touched test file."""
    _setup(ev, language="Python",
           files_touched=["src/foo.py", "tests/test_foo.py"])

    cmd = synthesize_test_command_if_missing(ev)
    assert cmd == "pytest tests/test_foo.py -v"
    assert ev.exists("05-fixed/test_command.txt")
    assert ev.read_text("05-fixed/test_command.txt").strip() == cmd


def test_go_synthesis_uses_package_path(ev):
    """go test runs the package containing the test file (Go has no
    direct way to point go test at a single file)."""
    _setup(ev, language="Go",
           files_touched=["middleware/logger/logger.go",
                          "middleware/logger/bytes_sent_test.go"])

    cmd = synthesize_test_command_if_missing(ev)
    assert cmd == "go test ./middleware/logger/... -v"


def test_go_synthesis_at_repo_root(ev):
    """A test file at repo root falls back to ./... rather than a
    malformed `./.../...` path."""
    _setup(ev, language="Go", files_touched=["main.go", "main_test.go"])

    cmd = synthesize_test_command_if_missing(ev)
    assert cmd == "go test ./... -v"


def test_typescript_synthesis_pnpm_test(ev):
    """TS/JS goes via pnpm test by default."""
    _setup(ev, language="TypeScript",
           files_touched=[
               "packages/vue-query/src/queryOptions.ts",
               "packages/vue-query/src/__tests__/queryOptions.test-d.ts",
           ])

    cmd = synthesize_test_command_if_missing(ev)
    assert cmd == "pnpm test packages/vue-query/src/__tests__/queryOptions.test-d.ts"


def test_javascript_synthesis_uses_pnpm(ev):
    """JS gets the same pnpm fallback as TS."""
    _setup(ev, language="JavaScript",
           files_touched=["lib/parser.js", "test/parser.test.js"])

    cmd = synthesize_test_command_if_missing(ev)
    assert cmd == "pnpm test test/parser.test.js"


def test_rust_synthesis_uses_test_target(ev):
    """Rust uses --test <stem> for integration tests in tests/."""
    _setup(ev, language="Rust",
           files_touched=["src/lib.rs", "tests/healer_dfs.rs"])

    cmd = synthesize_test_command_if_missing(ev)
    assert cmd == "cargo test --test healer_dfs -- --nocapture"


def test_no_test_file_in_touched_files_skips(ev):
    """If Copilot only touched source files (no test file), we have no
    candidate to point the test runner at — stay silent."""
    _setup(ev, language="Python", files_touched=["src/foo.py", "src/bar.py"])

    result = synthesize_test_command_if_missing(ev)
    assert result is None
    assert not ev.exists("05-fixed/test_command.txt")


def test_unknown_language_skips(ev):
    """Languages we don't have a template for stay silent so verify
    falls back to text-only rather than running garbage."""
    _setup(ev, language="C", files_touched=["src/foo.c", "tests/test_foo.c"])

    result = synthesize_test_command_if_missing(ev)
    assert result is None
    assert not ev.exists("05-fixed/test_command.txt")


def test_missing_language_health_json_skips(ev):
    """No 01-eligible/health.json → no synthesis (matches the original
    'no test_command.txt → ok=False' graceful path)."""
    _setup(ev, language=None, files_touched=["tests/test_foo.py"])

    result = synthesize_test_command_if_missing(ev)
    assert result is None
    assert not ev.exists("05-fixed/test_command.txt")


def test_missing_files_touched_skips(ev):
    """No files_touched.txt → no synthesis."""
    _setup(ev, language="Python", files_touched=None)

    result = synthesize_test_command_if_missing(ev)
    assert result is None
    assert not ev.exists("05-fixed/test_command.txt")


def test_double_encoded_health_json_is_tolerated(ev):
    """Some evidence-write paths double-encode JSON as a string. The
    synthesizer should peel that back rather than failing."""
    inner = json.dumps({"language": "Python", "slug": "x/y"})
    ev.write_text("01-eligible/health.json", json.dumps(inner))
    ev.write_text("05-fixed/files_touched.txt", "tests/test_foo.py\n")

    cmd = synthesize_test_command_if_missing(ev)
    assert cmd == "pytest tests/test_foo.py -v"


def test_picks_deepest_test_path_when_multiple(ev):
    """Multiple test files in the touched set → prefer the deepest path
    (most likely the specific new test rather than a top-level helper)."""
    _setup(ev, language="Python",
           files_touched=[
               "test_top.py",
               "tests/test_mid.py",
               "src/integrations/zigbee/tests/test_deep.py",
           ])

    cmd = synthesize_test_command_if_missing(ev)
    assert "test_deep.py" in cmd
    assert "test_top.py" not in cmd


# ---- _is_test_file unit tests ----

@pytest.mark.parametrize("path", [
    "tests/test_foo.py",
    "test_foo.py",
    "src/foo_test.py",
    "tests/foo.py",
    "pkg/foo_test.go",
    "src/__tests__/foo.test.ts",
    "src/foo.test.ts",
    "src/foo.test-d.ts",
    "src/foo.spec.tsx",
    "src/foo.spec.mjs",
    "tests/healer.rs",
])
def test_is_test_file_matches_known_shapes(path):
    assert _is_test_file(path) is True


@pytest.mark.parametrize("path", [
    "src/foo.py",
    "src/foo.go",
    "lib/index.ts",
    "src/lib.rs",
    "package.json",
    "README.md",
    "notes.md",
])
def test_is_test_file_rejects_non_tests(path):
    assert _is_test_file(path) is False


def test_pick_test_file_returns_none_for_no_candidates():
    assert _pick_test_file(["src/foo.py", "README.md"]) is None


def test_build_command_unknown_language_returns_none():
    assert _build_command("Cobol", "tests/test_foo.cbl") is None
    assert _build_command("", "tests/test_foo.py") is None
