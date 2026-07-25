"""verified_evidence_present gate — runs after `verified` state.

Mechanical check that the agent produced verification evidence. In
order of preference:
  1. test_output.txt — explicit passing test log (best)
  2. after.png + diff_from_repro.json — visual regression (for UI bugs)
  3. verify_notes.md — lightweight fallback summarizing what the agent
     did, used when Copilot bundled tests into the fix commits rather
     than committing a standalone test output artifact. The orchestrator
     auto-synthesizes this when harvest pulls source files but no
     test log.

This kills the puppeteer-class failure (agent claimed a fix that
doesn't work) without over-indexing on a specific filename Copilot
only sometimes writes.

See docs/crimson-kitty/gates.md.
"""

from __future__ import annotations

from . import CRIMSON_KITTY, Fail, GateResult, IssueRef, Pass, gate

MIN_VISUAL_DIFF_SCORE = 0.05  # at least 5% pixels different


@gate(pipeline=CRIMSON_KITTY, after="verified", kind="mechanical")
def verified_evidence_present(issue: IssueRef, evidence) -> GateResult:
    verify_dir = evidence.path("06-verified")
    if not verify_dir.exists():
        return Fail("06-verified/ directory missing")

    has_test_output = (verify_dir / "test_output.txt").exists()
    has_after_image = (verify_dir / "after.png").exists()
    has_verify_notes = (verify_dir / "verify_notes.md").exists()

    if not (has_test_output or has_after_image or has_verify_notes):
        return Fail("no test output, after.png, or verify_notes.md produced")

    if has_test_output:
        text = (verify_dir / "test_output.txt").read_text(encoding="utf-8")
        if not text.strip():
            return Fail("test_output.txt is empty")
        # Look for common pass markers; absence is suspicious but not a hard fail
        # since test runners vary.
        if "fail" in text.lower() and "pass" not in text.lower():
            return Fail(
                "test_output.txt contains 'fail' with no 'pass' marker",
                evidence_data={"first_200": text[:200]},
            )
        return Pass(evidence_data={"verification_kind": "test"})

    if has_after_image:
        # Image-based verification: requires a visual diff score
        diff_path = verify_dir / "diff_from_repro.json"
        if not diff_path.exists():
            return Fail("after.png present but diff_from_repro.json missing")
        diff = evidence.read_json("06-verified/diff_from_repro.json")
        score = diff.get("visual_diff_score") if isinstance(diff, dict) else None
        if not isinstance(score, (int, float)):
            return Fail(f"visual_diff_score not numeric: {score!r}")
        if score < MIN_VISUAL_DIFF_SCORE:
            return Fail(
                f"after.png visually identical to before.png (score={score:.3f})",
                evidence_data={"visual_diff_score": score},
            )
        return Pass(evidence_data={"verification_kind": "visual", "visual_diff_score": score})

    # Lightweight fallback: verify_notes.md is present, no stronger
    # artifact. Accept with a marker so downstream consumers know this
    # came from the synthesis path rather than an explicit test run.
    notes = (verify_dir / "verify_notes.md").read_text(encoding="utf-8")
    if len(notes.split()) < 20:
        return Fail(f"verify_notes.md too short: {len(notes.split())} words")
    return Pass(evidence_data={"verification_kind": "synthesized_notes"})
