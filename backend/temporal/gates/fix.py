"""Fix gates — diff_non_empty (mechanical) + relevance (judge).

Both run after the `fixed` state.

`diff_non_empty` is the highest-ROI gate in the pipeline. In the jade-hare
batch it would have killed 6 of the 21% empty PRs by itself. Pure
mechanical: read the diff, refuse if it's empty / suspiciously short /
has no commit SHAs.

`relevance` is one of only two judge-based gates in the entire pipeline.
It calls the local `claude` CLI via judge.py with the relevance_v1.md
rubric. Catches diff-sprawl (touching unrelated files).

See docs/crimson-kitty/gates.md.
"""

from __future__ import annotations

from ..judge import (
    JudgeParseError,
    JudgeUnreachable,
    score as judge_score,
)
from . import CRIMSON_KITTY, Defer, Fail, GateResult, IssueRef, Pass, gate

MIN_DIFF_BYTES = 50
MIN_RELEVANCE_SCORE_PASS = 0.70
MIN_RELEVANCE_SCORE_DEFER = 0.45


@gate(pipeline=CRIMSON_KITTY, after="fixed", kind="mechanical")
def diff_non_empty(issue: IssueRef, evidence) -> GateResult:
    if not evidence.exists("05-fixed/diff.patch"):
        return Fail("05-fixed/diff.patch missing")

    diff = evidence.read_text("05-fixed/diff.patch")
    if not diff.strip():
        return Fail("diff is empty — no commits ahead of base")
    if len(diff) < MIN_DIFF_BYTES:
        return Fail(
            f"diff suspiciously short: {len(diff)} bytes (need ≥{MIN_DIFF_BYTES})",
            evidence_data={"diff_bytes": len(diff)},
        )

    if not evidence.exists("05-fixed/commit_shas.txt"):
        return Fail("05-fixed/commit_shas.txt missing")
    shas = [l for l in evidence.read_text("05-fixed/commit_shas.txt").splitlines() if l.strip()]
    if not shas:
        return Fail("commit_shas.txt is empty")

    return Pass(evidence_data={"diff_bytes": len(diff), "commit_count": len(shas)})


@gate(pipeline=CRIMSON_KITTY, after="fixed", kind="judge")
def relevance(issue: IssueRef, evidence) -> GateResult:
    """Calls the local claude CLI with the relevance_v1.md rubric.

    On JudgeUnreachable / JudgeParseError → Defer with system: prefix so
    the operator inbox can distinguish system failures from real low-quality
    verdicts.
    """
    if not evidence.exists("05-fixed/diff.patch"):
        return Fail("05-fixed/diff.patch missing")
    if not evidence.exists("01-eligible/issue_brief.json"):
        return Fail("01-eligible/issue_brief.json missing (for relevance context)")

    diff = evidence.read_text("05-fixed/diff.patch")
    brief = evidence.read_json("01-eligible/issue_brief.json")
    files_touched = []
    if evidence.exists("05-fixed/files_touched.txt"):
        files_touched = [
            l.strip() for l in evidence.read_text("05-fixed/files_touched.txt").splitlines() if l.strip()
        ]

    issue_obj = brief.get("issue", {}) if isinstance(brief, dict) else {}
    title = issue_obj.get("title", "")
    body = (issue_obj.get("body") or "")[:500]

    payload = (
        f"## Issue summary\n\n"
        f"Title: {title}\n\n"
        f"Body excerpt:\n{body}\n\n"
        f"## Files touched ({len(files_touched)})\n\n"
        + "\n".join(f"- {f}" for f in files_touched[:50])
        + f"\n\n## Diff\n\n```diff\n{diff[:8000]}\n```"
        + ("\n\n[diff truncated]" if len(diff) > 8000 else "")
    )

    rubric = _load_rubric("relevance_v1.md")

    try:
        result = judge_score(rubric, payload)
    except JudgeUnreachable as e:
        return Defer(f"system:judge_unreachable: {e}")
    except JudgeParseError as e:
        return Defer(f"system:judge_parse_error: {e}")

    evidence.write_json(
        "05-fixed/relevance_check.json",
        {
            "verdict": result.verdict,
            "score": result.score,
            "reasoning": result.reasoning,
            "raw": result.raw,
        },
    )

    if result.verdict == "fail" or result.score < MIN_RELEVANCE_SCORE_DEFER:
        return Fail(
            f"relevance too low: {result.score:.2f} — {result.reasoning}",
            score=result.score,
        )
    if result.verdict == "defer" or result.score < MIN_RELEVANCE_SCORE_PASS:
        return Defer(
            f"relevance borderline: {result.score:.2f} — {result.reasoning}",
            score=result.score,
        )
    return Pass(score=result.score)


def _load_rubric(name: str) -> str:
    from pathlib import Path
    rubrics_dir = Path(__file__).parent.parent / "rubrics"
    return (rubrics_dir / name).read_text(encoding="utf-8")
