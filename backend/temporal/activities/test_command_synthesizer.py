"""Synthesize 05-fixed/test_command.txt when the agent didn't commit one.

Why this exists: the verify split's premise was that Copilot would commit a
single-line file at `05-fixed/test_command.txt` describing the test it
wrote in the repro phase, and a downstream sandbox runner would execute
it. In practice, Copilot consistently ignores that instruction even when
it's marked REQUIRED — observed across the v4 batch (0% compliance), the
2026-05-08 cli/crewAI Temporal run (0/2), and the 2026-05-08 fresh batch
on TanStack/query + valkey (0/2 so far). With nothing to run, the verify
activity falls back to text-only `verify_notes.md` and cktest-runner
sits idle.

This module fills the gap: when `05-fixed/test_command.txt` is missing,
we infer a reasonable command from:
  - The aggregator-derived language at `01-eligible/health.json`
  - The list of files Copilot touched at `05-fixed/files_touched.txt`

If the synthesizer can't be confident (no test files in the touched set,
unrecognized language, etc.) it leaves the file unwritten and the
existing graceful-no-op path still applies.

The synthesized command may not be perfect — monorepos with scoped
packages, Bazel-driven Python, custom tox configurations etc. all have
edge cases this can't cover. But "reasonable best guess that runs *something*"
is strictly better than "skip verify entirely," and a wrong command's
stdout/stderr is still useful diagnostic output for the reviewer.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import PurePosixPath
from typing import Optional

logger = logging.getLogger(__name__)


# Test-file detection. Order matters: more-specific patterns first so we
# don't mis-classify e.g. `foo.test-d.ts` (TS declaration test) as a
# generic `*.test.ts`.
_TEST_FILE_PATTERNS = [
    # Go: pkg/foo_test.go
    re.compile(r"_test\.go$"),
    # Rust: tests/some_test.rs OR src/lib.rs with #[cfg(test)] (we only
    # detect the explicit-test-file shape since #[cfg(test)] inline
    # tests don't have a per-file selector). `(^|/)` so we match
    # `tests/healer.rs` at the top level too, not just nested.
    re.compile(r"(^|/)tests?/.*\.rs$"),
    # Python: test_foo.py OR foo_test.py OR tests/foo.py
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"_test\.py$"),
    re.compile(r"(^|/)tests?/.*\.py$"),
    # JS/TS: foo.test.ts, foo.spec.ts, foo.test-d.ts (declaration tests)
    re.compile(r"\.test(-d)?\.[mc]?[jt]sx?$"),
    re.compile(r"\.spec\.[mc]?[jt]sx?$"),
    re.compile(r"(^|/)__tests__/.*\.[mc]?[jt]sx?$"),
]


def _is_test_file(path: str) -> bool:
    return any(p.search(path) for p in _TEST_FILE_PATTERNS)


def _read_language(evidence) -> Optional[str]:
    """Return the aggregator's language hint (lowercased) or None.

    Looks at `01-eligible/health.json` which is the aggregator-derived
    snapshot fetched during fork-and-assign. Falls back to None on any
    parse error — caller treats that as "give up, stay silent."
    """
    if not evidence.exists("01-eligible/health.json"):
        return None
    try:
        raw = evidence.read_text("01-eligible/health.json")
        # Some evidence files are double-encoded JSON strings; tolerate both.
        data = json.loads(raw)
        if isinstance(data, str):
            data = json.loads(data)
        lang = data.get("language") if isinstance(data, dict) else None
        return lang.lower() if isinstance(lang, str) else None
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None


def _read_files_touched(evidence) -> list[str]:
    """Return non-empty lines from `05-fixed/files_touched.txt`."""
    if not evidence.exists("05-fixed/files_touched.txt"):
        return []
    raw = evidence.read_text("05-fixed/files_touched.txt", default="") or ""
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _pick_test_file(files: list[str]) -> Optional[str]:
    """Pick the best test-file candidate from the touched set.

    Heuristic: prefer files we can confidently identify as tests. If
    multiple match, prefer the *deepest* path (likely the most
    specific test file rather than a top-level helper). Returns None
    when nothing looks like a test — caller stays silent in that case
    rather than synthesizing a guess that runs the whole suite.
    """
    candidates = [f for f in files if _is_test_file(f)]
    if not candidates:
        return None
    # Deepest path (most slashes) wins; ties broken by reverse alpha so
    # newer-numbered tests sort last (e.g. test_v2 over test_v1).
    candidates.sort(key=lambda p: (p.count("/"), p), reverse=True)
    return candidates[0]


def _build_command(language: str, test_file: str) -> Optional[str]:
    """Map (language, test_file) to a single-line shell command.

    Returns None for languages we don't know how to drive — caller
    leaves test_command.txt unwritten and the verify activity falls
    back to text-only as before.

    Conventions:
      - Always run from the repo root (the sandbox `cd`s into the
        clone before exec).
      - Prefer a single-test-file invocation over the full suite to
        keep wall time + RAM usage in budget for the sandbox host.
      - Use `-v` / equivalent verbose flags so the captured output is
        useful even on a passing test.
    """
    pp = PurePosixPath(test_file)
    parent = pp.parent.as_posix()  # "" if file is at repo root

    # Normalize language synonyms — the aggregator's language field
    # uses display-cased values like "TypeScript" / "Go" / "C".
    lang = (language or "").lower()

    if lang == "go":
        # Run the package containing the test file. -run "" matches all
        # tests; we can't reliably pick the specific TestName without
        # parsing the file.
        pkg = f"./{parent}/..." if parent and parent != "." else "./..."
        return f"go test {pkg} -v"

    if lang == "python":
        return f"pytest {test_file} -v"

    if lang in ("typescript", "javascript"):
        # Default to pnpm (most modern repos). The runner's allowlist
        # accepts pnpm/npm/yarn — if the repo uses npm/yarn instead,
        # the pnpm command will fail-fast with "lockfile mismatch"
        # and the reviewer sees the diagnostic in test_output.txt.
        # Slight refinement: pnpm vitest run <file> for vitest projects
        # is more reliable than `pnpm test` (which sometimes opens
        # interactive UI). Plain `pnpm test` is the safer fallback —
        # most package.json `test` scripts do the right thing.
        return f"pnpm test {test_file}"

    if lang == "rust":
        # cargo test doesn't take a file path directly; the closest
        # we can do is `--test <test_target>` with the file stem,
        # which works for tests in `tests/<name>.rs` (integration
        # tests). Inline `#[cfg(test)]` tests need the package name
        # which we don't have here.
        stem = pp.stem
        return f"cargo test --test {stem} -- --nocapture"

    # Anything else (C, Java, Ruby, …) — we don't have a confident
    # default. Return None and let verify fall back.
    return None


def synthesize_test_command_if_missing(evidence) -> Optional[str]:
    """If `05-fixed/test_command.txt` is absent, synthesize one and write it.

    Returns the synthesized command (also written to evidence) on success,
    or None if we couldn't / didn't need to synthesize. Idempotent: a
    pre-existing command file is left alone.

    Called by `run_test_command` immediately before the
    `if not evidence.exists("05-fixed/test_command.txt")` check, so the
    rest of the activity works unchanged when synthesis succeeds.
    """
    if evidence.exists("05-fixed/test_command.txt"):
        # Copilot wrote one — respect it.
        return None

    language = _read_language(evidence)
    if not language:
        logger.info("test-command synth: no language at 01-eligible/health.json — skip")
        return None

    files = _read_files_touched(evidence)
    if not files:
        logger.info("test-command synth: no files_touched.txt — skip")
        return None

    test_file = _pick_test_file(files)
    if not test_file:
        logger.info(
            "test-command synth: no test-shaped file in %d touched files — skip "
            "(language=%s, files=%s)",
            len(files), language, files[:5],
        )
        return None

    command = _build_command(language, test_file)
    if not command:
        logger.info(
            "test-command synth: no command template for language=%s — skip",
            language,
        )
        return None

    evidence.write_text("05-fixed/test_command.txt", command + "\n")
    logger.info(
        "test-command synth: wrote %r (language=%s, test_file=%s)",
        command, language, test_file,
    )
    return command
