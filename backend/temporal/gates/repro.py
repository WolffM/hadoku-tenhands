"""repro_evidence_present gate — runs after `reproduced` state.

Mechanical structural check: the agent produced at least one evidence
artifact AND a notes.md explaining the repro. Does NOT prescribe what
form evidence takes — a test, screenshot, trace, lint output, or any
other file the agent deems appropriate. The downstream gates (fix,
verify, submission) catch substantive failures.

Heading detection is lenient: Copilot-authored notes use many
styles — `## Steps to reproduce`, `## Steps to Reproduce`, plain
`Steps to Reproduce`, or `**Steps to Reproduce**`. We just require
each of the three labels to appear as a line of its own (optionally
prefixed by markdown punctuation), case-insensitively.

See docs/crimson-kitty/gates.md.
"""

from __future__ import annotations

import re

from . import Fail, GateResult, IssueRef, Pass, gate

REQUIRED_LABELS = ("Steps to reproduce", "Observed", "Expected")
MIN_NOTES_WORDS = 50

# Files that are always written by the orchestrator, not the agent.
# These don't count as "evidence the agent produced something."
_BOILERPLATE = {"agent_result.json", "notes.md"}


def _find_missing_sections(notes: str) -> list[str]:
    """Return labels from REQUIRED_LABELS that aren't present as a heading.

    A label is "present" when it appears as an entire trimmed line,
    optionally wrapped in `#`, `##`, `**`, or `__`, case-insensitively.
    """
    present: set[str] = set()
    for raw_line in notes.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        # Strip any leading `#` run + space, and any bold wrappers.
        cleaned = re.sub(r"^#+\s*", "", stripped)
        cleaned = cleaned.strip("* _")
        cleaned_lower = cleaned.lower()
        for label in REQUIRED_LABELS:
            if cleaned_lower == label.lower():
                present.add(label)
    return [label for label in REQUIRED_LABELS if label not in present]


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

    missing = _find_missing_sections(notes)
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
