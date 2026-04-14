"""Submission gates — run after `submittable` state.

Three gates fire here:
  - no_upstream_refs (mechanical): the output sanitizer's gate face. Reads
    PR title, body, and commit messages and refuses any real upstream ref.
    Defense-in-depth against the cross-reference leak class.
  - pr_template_compliance (mechanical): verifies the rendered PR body
    has every required section the upstream PR template asked for.
  - submission_judge (judge): final human-defensibility check via the
    submission_v1.md rubric. The second and final judge call in the
    pipeline.

See docs/crimson-kitty/gates.md.
"""

from __future__ import annotations

import json

from ..judge import (
    JudgeParseError,
    JudgeUnreachable,
    score as judge_score,
)
from ..sanitizer import SanitizerError, scan_outputs
from . import Defer, Fail, GateResult, IssueRef, Pass, gate

MIN_SUBMISSION_SCORE_PASS = 0.75
MIN_SUBMISSION_SCORE_DEFER = 0.55


# ── no_upstream_refs ──────────────────────────────────────────────────────


@gate(after="submittable", kind="mechanical")
def no_upstream_refs(issue: IssueRef, evidence) -> GateResult:
    """Output sanitizer wrapped as a gate.

    Reads the proposed PR title, body, and commit messages from evidence
    and runs `sanitizer.scan_outputs`. Hallucinated refs (numbers that
    don't match the recorded issue) pass through; only real upstream refs
    are blocked.
    """
    if not evidence.exists("09-submittable/pr_title.txt"):
        return Fail("09-submittable/pr_title.txt missing")
    if not evidence.exists("09-submittable/pr_body.md"):
        return Fail("09-submittable/pr_body.md missing")

    title = evidence.read_text("09-submittable/pr_title.txt")
    body = evidence.read_text("09-submittable/pr_body.md")

    commits: list[dict] = []
    if evidence.exists("05-fixed/commits.json"):
        c = evidence.read_json("05-fixed/commits.json")
        if isinstance(c, list):
            commits = [x for x in c if isinstance(x, dict)]

    try:
        scan_outputs(
            pr_title=title,
            pr_body=body,
            commit_messages=commits,
            upstream_slug=issue.upstream_slug,
            issue_number=issue.upstream_number,
        )
    except SanitizerError as e:
        evidence.write_json(
            "09-submittable/sanitizer_scan.json",
            {
                "leak_count": len(e.leaks),
                "leak_kinds": sorted({l.kind for l in e.leaks}),
                "leaks": [
                    {"kind": l.kind, "matched": l.matched, "source": l.source}
                    for l in e.leaks[:20]
                ],
            },
        )
        return Fail(
            f"output sanitizer found {len(e.leaks)} upstream ref(s)",
            evidence_data={"leak_count": len(e.leaks)},
        )

    evidence.write_json("09-submittable/sanitizer_scan.json", {"leak_count": 0})
    return Pass()


# ── pr_template_compliance ────────────────────────────────────────────────


@gate(after="submittable", kind="mechanical")
def pr_template_compliance(issue: IssueRef, evidence) -> GateResult:
    """Verify the rendered PR body has every required section from the
    upstream PR template (fetched from the aggregator at activity time)."""
    if not evidence.exists("09-submittable/pr_body.md"):
        return Fail("09-submittable/pr_body.md missing")
    if not evidence.exists("09-submittable/template.json"):
        # No template fetched → upstream has no PR template → trivially
        # compliant.
        return Pass(reason="upstream has no PR template")

    body = evidence.read_text("09-submittable/pr_body.md")
    template = evidence.read_json("09-submittable/template.json")
    if not isinstance(template, dict):
        return Fail(f"template.json not an object: {type(template).__name__}")

    sections = template.get("sections") or []
    if not isinstance(sections, list):
        sections = []

    missing = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        if not section.get("required"):
            continue
        heading = section.get("heading") or ""
        if not heading:
            continue
        if heading not in body:
            missing.append(heading)

    if missing:
        return Fail(
            f"PR body missing required sections: {missing}",
            evidence_data={"missing_sections": missing},
        )

    evidence.write_json(
        "09-submittable/template_compliance.json",
        {"required_sections": [s.get("heading") for s in sections if s.get("required")], "missing": []},
    )
    return Pass()


# ── submission_judge ──────────────────────────────────────────────────────


@gate(after="submittable", kind="judge")
def submission_judge(issue: IssueRef, evidence) -> GateResult:
    """Final human-defensibility check via the submission_v1.md rubric."""
    if not evidence.exists("09-submittable/pr_title.txt"):
        return Fail("pr_title.txt missing")
    if not evidence.exists("09-submittable/pr_body.md"):
        return Fail("pr_body.md missing")

    title = evidence.read_text("09-submittable/pr_title.txt")
    body = evidence.read_text("09-submittable/pr_body.md")

    files_touched = []
    if evidence.exists("05-fixed/files_touched.txt"):
        files_touched = [
            l.strip() for l in evidence.read_text("05-fixed/files_touched.txt").splitlines() if l.strip()
        ]

    diff_bytes = 0
    if evidence.exists("05-fixed/diff.patch"):
        diff_bytes = len(evidence.read_text("05-fixed/diff.patch"))

    commit_count = 0
    if evidence.exists("05-fixed/commit_shas.txt"):
        commit_count = len([
            l for l in evidence.read_text("05-fixed/commit_shas.txt").splitlines() if l.strip()
        ])

    payload = (
        f"## PR title\n\n{title}\n\n"
        f"## PR body\n\n{body}\n\n"
        f"## Fix summary\n\n"
        f"- files touched: {len(files_touched)}\n"
        + "\n".join(f"  - {f}" for f in files_touched[:30])
        + f"\n- diff bytes: {diff_bytes}\n"
        + f"- commit count: {commit_count}\n"
    )

    rubric = _load_rubric("submission_v1.md")

    try:
        result = judge_score(rubric, payload)
    except JudgeUnreachable as e:
        return Defer(f"system:judge_unreachable: {e}")
    except JudgeParseError as e:
        return Defer(f"system:judge_parse_error: {e}")

    evidence.write_json(
        "09-submittable/submission_judge.json",
        {
            "verdict": result.verdict,
            "score": result.score,
            "reasoning": result.reasoning,
            "raw": result.raw,
        },
    )

    if result.verdict == "fail" or result.score < MIN_SUBMISSION_SCORE_DEFER:
        return Fail(
            f"submission quality too low: {result.score:.2f} — {result.reasoning}",
            score=result.score,
        )
    if result.verdict == "defer" or result.score < MIN_SUBMISSION_SCORE_PASS:
        return Defer(
            f"submission borderline: {result.score:.2f} — {result.reasoning}",
            score=result.score,
        )
    return Pass(score=result.score)


def _load_rubric(name: str) -> str:
    from pathlib import Path
    rubrics_dir = Path(__file__).parent.parent / "rubrics"
    return (rubrics_dir / name).read_text(encoding="utf-8")
