"""repro_evidence_present gate — runs after `reproduced` state.

Mechanical structural check that the agent produced a real repro artifact
(test, screenshot, or trace) AND a notes.md with required sections + word
count. Replaces the judge-based `repro_quality` gate (dropped in F1).

This gate kills the puppeteer-class failure: agent claimed a fix without
ever actually reproducing the bug.

See docs/crimson-kitty/gates.md.
"""

from __future__ import annotations

from . import Fail, GateResult, IssueRef, Pass, gate

REQUIRED_SECTIONS = ("## Steps to reproduce", "## Observed", "## Expected")
MIN_NOTES_WORDS = 50


@gate(after="reproduced", kind="mechanical")
def repro_evidence_present(issue: IssueRef, evidence) -> GateResult:
    repro_dir = evidence.path("04-reproduced")
    if not repro_dir.exists():
        return Fail("04-reproduced/ directory missing")

    has_test = any(repro_dir.glob("test.*"))
    has_image = (repro_dir / "before.png").exists()
    has_trace = (repro_dir / "trace.zip").exists()

    if not (has_test or has_image or has_trace):
        return Fail("no test, screenshot, or trace produced")

    notes_path = repro_dir / "notes.md"
    if not notes_path.exists():
        return Fail("notes.md missing — agent must explain the repro")

    notes = notes_path.read_text(encoding="utf-8")
    word_count = len(notes.split())
    if word_count < MIN_NOTES_WORDS:
        return Fail(
            f"notes.md too short: {word_count} words (need ≥{MIN_NOTES_WORDS})",
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
            "has_test": has_test,
            "has_image": has_image,
            "has_trace": has_trace,
            "word_count": word_count,
        },
    )
