"""LLM judge wrapper — spawns the local `claude` CLI subprocess.

Uses the existing Claude Max subscription via the `CLAUDE_CODE_OAUTH_TOKEN`
env var (no Anthropic API key, no per-call billing). The CLI is installed
once per host; the token is set once per process (loaded from `.env`).

Concurrency: a module-level semaphore caps simultaneous subprocesses at
`MAX_CONCURRENT_JUDGES` (default 3). Each call:
  1. Acquires the semaphore
  2. Runs a tiny canary call against `--model haiku` to verify the CLI
     and credentials are alive (fails fast on quota / auth issues without
     burning a real prompt)
  3. Runs the real prompt with `--output-format json`
  4. Parses the envelope, extracts the fenced JSON the rubric asked for,
     returns a typed `JudgeResult`
  5. Releases the semaphore in `finally`

All exceptions inherit from `JudgeError` so callers can catch the whole
class. The two specific failures the gates need to distinguish:
  - `JudgeUnreachable`: subprocess failed, timed out, or canary failed.
    Gate maps this to `defer` with reason `system:judge_unreachable`.
  - `JudgeParseError`: subprocess returned but output didn't contain valid
    JSON in the expected envelope. Gate maps this to `defer` with reason
    `system:judge_parse_error`.

See docs/crimson-kitty/components.md for deployment details
(CRIMSON_CLAUDE_BIN, canary semantics).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass

from .config import validate_judge_credentials


# ── Tunables ──────────────────────────────────────────────────────────────

MAX_CONCURRENT_JUDGES = int(os.environ.get("CRIMSON_JUDGE_CAP", "3"))
JUDGE_TIMEOUT_S = int(os.environ.get("CRIMSON_JUDGE_TIMEOUT", "120"))
CANARY_TIMEOUT_S = int(os.environ.get("CRIMSON_JUDGE_CANARY_TIMEOUT", "10"))
CANARY_PROMPT = "respond with exactly: OK"
CANARY_MODEL = "haiku"
JUDGE_MODEL = os.environ.get("CRIMSON_JUDGE_MODEL", "haiku")
CLAUDE_BIN = os.environ.get("CRIMSON_CLAUDE_BIN", "claude")

_semaphore = threading.Semaphore(MAX_CONCURRENT_JUDGES)


# ── Exceptions ────────────────────────────────────────────────────────────


class JudgeError(Exception):
    """Base for all judge failures."""


class JudgeUnreachable(JudgeError):
    """The CLI subprocess could not be invoked / canary failed / timed out."""


class JudgeParseError(JudgeError):
    """The CLI returned but the output didn't contain valid JSON in the
    expected envelope (rubric asks for a fenced ```json block)."""


# ── Result ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class JudgeResult:
    verdict: str          # "pass" | "fail" | "defer"
    score: float          # 0.0..1.0
    reasoning: str        # short prose
    raw: dict             # the full parsed JSON the rubric returned


# ── Subprocess seam (monkeypatched in tests) ──────────────────────────────


def _run_claude(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run the `claude` CLI. Isolated so tests can monkeypatch it.

    The OAuth token is inherited from the parent process env (`.env`-loaded
    via dotenv before the worker starts).
    """
    return subprocess.run(
        [CLAUDE_BIN, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


# ── Canary ────────────────────────────────────────────────────────────────


def _canary_or_raise() -> None:
    """Tiny health check before every real judge call.

    Catches quota exhaustion, expired token, missing binary, and host
    network outages — all of which would otherwise fail the real call
    after burning a real prompt.
    """
    try:
        result = _run_claude(
            ["-p", CANARY_PROMPT, "--model", CANARY_MODEL],
            timeout=CANARY_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as e:
        raise JudgeUnreachable(f"canary timed out after {CANARY_TIMEOUT_S}s") from e
    except FileNotFoundError as e:
        raise JudgeUnreachable(f"claude binary not found: {CLAUDE_BIN}") from e

    if result.returncode != 0:
        raise JudgeUnreachable(
            f"canary exit {result.returncode}: {result.stderr.strip()[:200]}"
        )
    if "OK" not in result.stdout:
        raise JudgeUnreachable(
            f"canary returned unexpected output: {result.stdout.strip()[:200]}"
        )


# ── JSON extraction ───────────────────────────────────────────────────────

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


def _extract_json(stdout: str) -> dict:
    """Pull the rubric's JSON envelope out of the CLI's stdout.

    Two acceptable forms (supports both `--output-format json` envelope and
    plain text with a fenced JSON block):

    1. CLI envelope: `{"result": "<text containing fenced json>", ...}`
       We parse the envelope, then extract the fenced block from `result`.

    2. Plain text: stdout is just the rubric's text response containing a
       single fenced ```json block.

    The rubric MUST instruct the model to emit exactly one fenced
    ```json``` block containing the structured verdict.
    """
    if not stdout or not stdout.strip():
        raise JudgeParseError("claude returned empty stdout")

    text = stdout

    # Form 1: `--output-format json` wraps everything in an envelope.
    try:
        envelope = json.loads(stdout)
        if isinstance(envelope, dict) and "result" in envelope:
            text = envelope["result"]
            if not isinstance(text, str):
                raise JudgeParseError(
                    f"envelope.result is not a string: {type(text).__name__}"
                )
    except json.JSONDecodeError:
        # Not the envelope form — fall through to plain-text extraction.
        pass

    matches = _FENCED_JSON_RE.findall(text)
    if not matches:
        raise JudgeParseError(
            f"no fenced ```json block in output (first 200 chars): {text[:200]!r}"
        )
    if len(matches) > 1:
        raise JudgeParseError(
            "multiple fenced ```json blocks; expected exactly one"
        )

    try:
        parsed = json.loads(matches[0])
    except json.JSONDecodeError as e:
        raise JudgeParseError(f"fenced JSON block is not valid JSON: {e}") from e

    if not isinstance(parsed, dict):
        raise JudgeParseError(
            f"fenced JSON must be an object, got {type(parsed).__name__}"
        )
    return parsed


def _coerce_result(parsed: dict) -> JudgeResult:
    """Validate the rubric's required fields and pack into JudgeResult."""
    verdict = parsed.get("verdict")
    if verdict not in ("pass", "fail", "defer"):
        raise JudgeParseError(f"invalid verdict: {verdict!r}")

    raw_score = parsed.get("score")
    try:
        score_f = float(raw_score)
    except (TypeError, ValueError) as e:
        raise JudgeParseError(f"invalid score: {raw_score!r}") from e
    if not 0.0 <= score_f <= 1.0:
        raise JudgeParseError(f"score out of [0,1] range: {score_f}")

    reasoning = parsed.get("reasoning", "")
    if not isinstance(reasoning, str):
        raise JudgeParseError(f"reasoning must be string, got {type(reasoning).__name__}")

    return JudgeResult(verdict=verdict, score=score_f, reasoning=reasoning, raw=parsed)


# ── Public API ────────────────────────────────────────────────────────────


def score(rubric_md: str, input_payload: str) -> JudgeResult:
    """Run the judge against a rubric + input payload.

    The rubric is the markdown text of `relevance_v1.md` or
    `submission_v1.md`. The input payload is the structured data the rubric
    asks the judge to score (e.g. a diff, a PR body).

    Raises `JudgeUnreachable` if the CLI / canary fails.
    Raises `JudgeParseError` if the output isn't parseable.
    Returns a `JudgeResult` on success.
    """
    validate_judge_credentials()  # raises MissingConfigError

    prompt = _compose_prompt(rubric_md, input_payload)

    with _semaphore:
        _canary_or_raise()

        try:
            result = _run_claude(
                [
                    "-p", prompt,
                    "--model", JUDGE_MODEL,
                    "--output-format", "json",
                ],
                timeout=JUDGE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as e:
            raise JudgeUnreachable(f"judge call timed out after {JUDGE_TIMEOUT_S}s") from e

        if result.returncode != 0:
            raise JudgeUnreachable(
                f"judge exit {result.returncode}: {result.stderr.strip()[:200]}"
            )

        parsed = _extract_json(result.stdout)
        return _coerce_result(parsed)


def _compose_prompt(rubric_md: str, input_payload: str) -> str:
    """Glue rubric and payload into the prompt sent to claude."""
    return (
        f"{rubric_md}\n\n"
        f"---\n\n"
        f"## Input to score\n\n"
        f"{input_payload}\n\n"
        f"---\n\n"
        f"Respond with exactly one fenced ```json block containing your verdict, "
        f"score, and reasoning per the rubric above. No prose outside the block."
    )
