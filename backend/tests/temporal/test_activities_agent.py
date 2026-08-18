"""the agent-driven activities (fix, repro, verify, remediate)

Split out of the 2217-line `test_activities.py`, which vibeCompact flagged at
its top size tier. The cut follows the `# ── ... activity ──` banners that
file already carried, so one module covers one activity. Shared `issue` and
`ev` fixtures live in conftest.py.
"""

from __future__ import annotations

import json

import pytest

from temporal.agents.noop import NoopAgent

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
