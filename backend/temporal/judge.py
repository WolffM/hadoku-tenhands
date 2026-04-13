"""LLM judge for `judge`-kind gates.

Spawns a local `claude` CLI subprocess (decision Q5/F1). Uses the operator's
existing Claude Max subscription — no Anthropic API key required.

## Design constraints (from F1)

1. **Minimal usage**: the entire pipeline calls this judge AT MOST TWICE
   per issue (relevance after fixed, submission_judge after submittable).
   Don't add new judge gates without explicit operator approval.

2. **Semaphore**: cap=3 concurrent judge subprocesses across the worker
   process, regardless of how many issues are in flight. The Max
   subscription rate-limits us, not the local machine.

3. **Canary check** before every real judge call:
   `claude -p "respond with OK" --model haiku --output-format json`
   with 10s timeout. If the canary fails, the gate immediately defers
   to inbox with `system:judge_unreachable`. Don't attempt the real
   call when we know auth/quota is broken.

4. **JSON output**: use `--output-format json` if available. The CLI
   emits markdown plus warnings/tool-use noise on stdout otherwise.

5. **Parse safety**: wrap parsing in try/catch. Any exception →
   defer to inbox with `system:judge_parse_error`, NOT a crash.

6. **Production install**: `npm install -g @anthropic-ai/claude-code@<pinned>`
   added to the `vibedispatch-temporal` pm2 setup script. Auth runs
   once on the prod host (see `docs/runbooks/claude-cli-prod-auth.md`).

## Pseudocode

    import json
    import subprocess
    import threading
    from pathlib import Path
    from dataclasses import dataclass

    RUBRICS_DIR = Path(__file__).parent / "rubrics"
    JUDGE_SEMAPHORE = threading.Semaphore(3)
    CANARY_TIMEOUT_S = 10
    JUDGE_TIMEOUT_S  = 120

    class JudgeUnreachable(Exception):
        '''Raised when canary check fails — gate should defer.'''

    class JudgeParseError(Exception):
        '''Raised when output cannot be parsed — gate should defer.'''

    @dataclass
    class JudgeResult:
        score: float
        reasoning: str

    def score(payload: dict, rubric: str) -> JudgeResult:
        with JUDGE_SEMAPHORE:
            _canary_or_raise()                         # raises JudgeUnreachable
            return _real_call(payload, rubric)         # raises JudgeParseError

    def _canary_or_raise() -> None:
        try:
            r = subprocess.run(
                ["claude", "-p", "respond with OK",
                 "--model", "haiku",
                 "--output-format", "json",
                 "--permission-mode", "bypassPermissions"],
                capture_output=True, text=True,
                timeout=CANARY_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as e:
            raise JudgeUnreachable("canary timeout") from e
        if r.returncode != 0:
            raise JudgeUnreachable(f"canary exit {r.returncode}: {r.stderr[:200]}")

    def _real_call(payload: dict, rubric: str) -> JudgeResult:
        rubric_text = (RUBRICS_DIR / f"{rubric}.md").read_text()
        prompt = _build_prompt(rubric_text, payload)
        try:
            r = subprocess.run(
                ["claude", "-p", prompt,
                 "--model", "haiku",
                 "--output-format", "json",
                 "--permission-mode", "bypassPermissions"],
                capture_output=True, text=True,
                timeout=JUDGE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as e:
            raise JudgeParseError("judge timeout") from e
        if r.returncode != 0:
            raise JudgeParseError(f"judge exit {r.returncode}: {r.stderr[:200]}")
        try:
            parsed = _extract_json(r.stdout)
            return JudgeResult(
                score=float(parsed["score"]),
                reasoning=parsed["reasoning"],
            )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            raise JudgeParseError(f"could not parse judge response: {e}") from e

    def _extract_json(stdout: str) -> dict:
        # When --output-format json works, the CLI returns a JSON envelope
        # with a `result` field containing the model's text. The model
        # itself is instructed to reply with a fenced ```json block.
        envelope = json.loads(stdout)
        text = envelope.get("result", envelope.get("content", ""))
        # Find the fenced JSON block in the model's text.
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not match:
            raise JudgeParseError("no fenced JSON block in model response")
        return json.loads(match.group(1))

## Gate integration

Gates call `score()` and translate exceptions into GateResult:

    @gate(after="submittable", kind="judge")
    def submission_judge(evidence) -> GateResult:
        try:
            r = score(payload, rubric="submission_v1")
        except JudgeUnreachable as e:
            return Defer("submission_judge", f"system:judge_unreachable: {e}")
        except JudgeParseError as e:
            return Defer("submission_judge", f"system:judge_parse_error: {e}")
        if r.score < 0.6:
            return Defer("submission_judge", f"low quality (score={r.score:.2f})")
        return Pass("submission_judge", score=r.score)

## Rubrics directory

    backend/temporal/rubrics/
        relevance_v1.md       — used by gates/fix.py::relevance
        submission_v1.md      — used by gates/submission.py::submission_judge

That's the entire judge surface. Two rubrics, two gates, two calls per issue.
"""
