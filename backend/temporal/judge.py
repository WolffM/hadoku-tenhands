"""LLM judge wrapper — spawns the local `claude` CLI subprocess.

Uses the Claude subscriptions' OAuth tokens (no Anthropic API key, no
per-call billing), drawn from the pool in `claude_tokens.py`: a token that is
out of quota or rejected is benched and the call moves to the next one.

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
    Its subclass `JudgeQuotaExhausted` names the case where the CLI answered
    with a usage/rate-limit message, and carries the reset time.
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
from datetime import datetime

from . import claude_tokens
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


class JudgeQuotaExhausted(JudgeUnreachable):
    """The CLI answered, and the answer was "this account is out of quota".

    A subclass of `JudgeUnreachable`, so every gate that defers on an
    unreachable judge keeps doing exactly that. It exists for the callers that
    must tell "the judge is broken" apart from "the judge is fine and the
    account's usage limit ran out" — chiefly the real-CLI integration test,
    which skips on this (with the reset time) and fails on everything else.

    `resets` is the CLI's own wording of when the limit lifts, e.g.
    "Nov 6, 3pm (America/Los_Angeles)", or None if the message didn't say.
    """

    def __init__(self, message: str, resets: str | None):
        super().__init__(message)
        self.resets = resets


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


def _run_claude(
    args: list[str],
    timeout: int,
    *,
    stdin_text: str | None = None,
    token: claude_tokens.Token | None = None,
) -> subprocess.CompletedProcess:
    """Run the `claude` CLI. Isolated so tests can monkeypatch it.

    `token` is the pool's choice, passed as CLAUDE_CODE_OAUTH_TOKEN. None
    inherits the parent's environment unchanged.

    Pass large prompts via `stdin_text` rather than `-p <prompt>` — on
    Windows, CreateProcess rejects command lines over ~32KB with "The
    command line is too long," which corrupts any score() call whose
    rubric + payload happens to exceed that ceiling (typical for real
    fix diffs).
    """
    env = None
    if token is not None:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(claude_tokens.PREFIX)}
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token.value
    return subprocess.run(
        [CLAUDE_BIN, *args],
        input=stdin_text,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",  # B18: Windows defaults to cp1252 which chokes on `≥` etc
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _failure_detail(result: subprocess.CompletedProcess) -> str:
    """Why a non-zero `claude` run failed, from whichever stream carried it.

    `claude -p` reports its own errors on STDOUT, so quoting stderr alone is how
    a real outage arrives as a bare "canary exit 1:" with nothing after the
    colon. That is exactly what CI showed on 2026-08-25: four consecutive runs
    failed identically, the run passed untouched on retry 45 minutes later, and
    the message had thrown away every clue as to what the CLI had objected to.
    """
    detail = result.stderr.strip() or result.stdout.strip() or "no output on either stream"
    return detail[:200]


def _unreachable(what: str, result: subprocess.CompletedProcess) -> JudgeUnreachable:
    """The exception for a non-zero `claude` exit: quota, or genuinely broken."""
    detail = _failure_detail(result)
    message = f"{what} exit {result.returncode}: {detail}"
    # The quota wording lives with the pool, which benches on it. An expired
    # token, "Credit balance is too low" or an empty answer stay plain
    # `JudgeUnreachable`.
    if claude_tokens.QUOTA_RE.search(detail):
        resets = claude_tokens.RESETS_RE.search(detail)
        return JudgeQuotaExhausted(message, resets.group(1).strip() if resets else None)
    return JudgeUnreachable(message)


# ── Canary ────────────────────────────────────────────────────────────────


def _canary_or_raise(token: claude_tokens.Token | None = None) -> None:
    """Tiny health check before every real judge call.

    Catches quota exhaustion, expired token, missing binary, and host
    network outages — all of which would otherwise fail the real call
    after burning a real prompt.
    """
    try:
        result = _run_claude(
            ["-p", CANARY_PROMPT, "--model", CANARY_MODEL],
            timeout=CANARY_TIMEOUT_S,
            token=token,
        )
    except subprocess.TimeoutExpired as e:
        raise JudgeUnreachable(f"canary timed out after {CANARY_TIMEOUT_S}s") from e
    except FileNotFoundError as e:
        raise JudgeUnreachable(f"claude binary not found: {CLAUDE_BIN}") from e

    if result.returncode != 0:
        raise _unreachable("canary", result)
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


# ── Token pool ────────────────────────────────────────────────────────────


def _on_pool(call):
    """Run `call(token)` on the first usable token, moving on when one is spent.

    A `JudgeUnreachable` that is the token's fault (out of quota, rejected)
    benches it and tries the next; any other failure is raised as it is. When
    every token was already benched before the call, the error says so:
    `JudgeQuotaExhausted` (carrying the earliest reset) if all of them are only
    out of quota.
    """
    pool = claude_tokens.default_pool()

    def exhausted(e: claude_tokens.PoolExhausted) -> JudgeUnreachable:
        if e.quota_only:
            when = (datetime.fromtimestamp(e.earliest).astimezone().isoformat(timespec="minutes")
                    if e.earliest else None)
            return JudgeQuotaExhausted(str(e), when)
        return JudgeUnreachable(str(e))

    try:
        attempts = pool.available() or [None]
    except claude_tokens.PoolExhausted as e:
        raise exhausted(e) from e

    last: JudgeUnreachable | None = None
    for token in attempts:
        try:
            return call(token)
        except JudgeUnreachable as e:
            if pool.bench_if_token_problem(token, str(e)) is None:
                raise
            last = e
    # Every token this call tried was spent. The last one's own error is the
    # most useful thing to raise: it carries the CLI's wording of when the
    # limit lifts, which the pool's summary would only paraphrase.
    assert last is not None
    raise last


def canary_all() -> list[dict]:
    """Canary every configured token. Diagnostic; costs one haiku call each."""
    rows = []
    for token in claude_tokens.load_tokens():
        try:
            _canary_or_raise(token)
            rows.append({"label": token.label, "reachable": True})
        except JudgeError as e:
            rows.append({"label": token.label, "reachable": False,
                         "error_class": type(e).__name__, "error_message": str(e)[:300]})
    return rows


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

    def attempt(token):
        _canary_or_raise(token)
        try:
            # Pass prompt via stdin — real fix diffs blow the ~32KB
            # Windows CreateProcess argv ceiling when sent as `-p <prompt>`.
            result = _run_claude(
                [
                    "-p",
                    "--model", JUDGE_MODEL,
                    "--output-format", "json",
                ],
                timeout=JUDGE_TIMEOUT_S,
                stdin_text=prompt,
                token=token,
            )
        except subprocess.TimeoutExpired as e:
            raise JudgeUnreachable(f"judge call timed out after {JUDGE_TIMEOUT_S}s") from e

        if result.returncode != 0:
            raise _unreachable("judge", result)
        return result

    with _semaphore:
        result = _on_pool(attempt)

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


_TITLE_PROMPT = """You write a single conventional-commit PR title for an open-source contribution.

Given the issue title, brief description, and a summary of the diff, output exactly one fenced ```json block:

```json
{"title": "type(scope): imperative description"}
```

Rules for the title string:
- ≤72 characters total
- Conventional Commits format: `type(scope): description` (scope optional but encouraged when the diff is localized)
- type ∈ {fix, feat, chore, refactor, docs, test, perf, build}
- Lowercase except code symbols and proper nouns
- No trailing punctuation, no ellipsis
- Imperative voice ("clean working tree", not "cleans/cleaned")
- Describe WHAT THE CHANGE DOES, not what the bug WAS
- Do NOT copy the issue title verbatim — the issue title describes the bug; the PR title describes the fix.

Respond with exactly one fenced ```json block. No prose outside the block."""


def generate_title(issue_title: str, fix_summary: str, files_touched: list[str]) -> str:
    """Generate a fresh, conventional-commit-style PR title via haiku.

    Replaces the prior behavior of copying the issue title verbatim
    (which often had `[Bug]` prefixes, was too long, and described the
    bug rather than the fix — see argo-cd#28030 where the title ended
    in `…`). Falls through `JudgeUnreachable` / `JudgeParseError` so
    callers can apply their own fallback.
    """
    validate_judge_credentials()

    files_block = "\n".join(f"- {f}" for f in (files_touched or [])[:30])
    if len(files_touched or []) > 30:
        files_block += f"\n- (+{len(files_touched) - 30} more)"

    payload = (
        f"## Issue title\n{issue_title}\n\n"
        f"## Files touched\n{files_block or '_(none recorded)_'}\n\n"
        f"## Fix summary\n{(fix_summary or '').strip()[:1200] or '_(none recorded)_'}\n"
    )

    prompt = f"{_TITLE_PROMPT}\n\n---\n\n## Input\n\n{payload}"

    def attempt(token):
        _canary_or_raise(token)
        try:
            result = _run_claude(
                ["-p", "--model", JUDGE_MODEL, "--output-format", "json"],
                timeout=JUDGE_TIMEOUT_S,
                stdin_text=prompt,
                token=token,
            )
        except subprocess.TimeoutExpired as e:
            raise JudgeUnreachable(f"title judge timed out after {JUDGE_TIMEOUT_S}s") from e
        if result.returncode != 0:
            raise _unreachable("title judge", result)
        return result

    with _semaphore:
        result = _on_pool(attempt)

    parsed = _extract_json(result.stdout)
    title = parsed.get("title") if isinstance(parsed, dict) else None
    if not isinstance(title, str) or not title.strip():
        raise JudgeParseError(f"title judge: expected 'title' string, got {type(title).__name__}")
    return title.strip()
