"""repro_evidence_present gate — runs after `reproduced` state.

Mechanical structural check: the agent produced at least one evidence
artifact AND a notes.md explaining the repro. Does NOT prescribe what
form evidence takes — a test, screenshot, trace, lint output, or any
other file the agent deems appropriate. The downstream gates (fix,
verify, submission) catch substantive failures.

See docs/crimson-kitty/gates.md.
"""

from __future__ import annotations

from . import Fail, GateResult, IssueRef, Pass, gate

# notes.md must contain these sections so the operator can audit.
REQUIRED_SECTIONS = ("## Steps to reproduce", "## Observed", "## Expected")
MIN_NOTES_WORDS = 50

# Files that are always written by the orchestrator, not the agent.
# These don't count as "evidence the agent produced something."
_BOILERPLATE = {"agent_result.json", "notes.md"}


@gate(after="reproduced", kind="mechanical")
def repro_evidence_present(issue: IssueRef, evidence) -> GateResult:
    repro_dir = evidence.path("04-reproduced")
    if not repro_dir.exists():
        return Fail("04-reproduced/ directory missing")

    # Any non-boilerplate file counts as evidence.
    artifacts = [
        f.name for f in repro_dir.iterdir()
        if f.is_file() and f.name not in _BOILERPLATE
    ]

    if not artifacts:
        return Fail("no evidence artifacts produced")

    notes_path = repro_dir / "notes.md"
    if not notes_path.exists():
        return Fail("notes.md missing - agent must explain the repro")

    notes = notes_path.read_text(encoding="utf-8")
    word_count = len(notes.split())
    if word_count < MIN_NOTES_WORDS:
        return Fail(
            f"notes.md too short: {word_count} words (need >={MIN_NOTES_WORDS})",
            evidence_data={"word_count": word_count},
        )

    missing = [s for s in REQUIRED_SECTIONS if s not in notes]
    if missing:
        return Fail(
            f"notes.md missing sections: {missing}",
            evidence_data={"missing_sections": missing},
        )

    return Pass(
        evidence_data={
            "artifacts": artifacts,
            "word_count": word_count,
        },
    )
