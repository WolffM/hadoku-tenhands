"""remediation_complete gate — runs after `remediated` state.

Mechanical check that all blocking review comments were addressed in the
remediation diff. Reads the comment list from `07-reviewed/comments.json`
and the resolution map from `08-remediated/resolved_comments.json`, then
verifies every blocker has a resolution.

See docs/crimson-kitty/gates.md.
"""

from __future__ import annotations

from . import Fail, GateResult, IssueRef, Pass, gate


@gate(after="remediated", kind="mechanical")
def remediation_complete(issue: IssueRef, evidence) -> GateResult:
    if not evidence.exists("07-reviewed/comments.json"):
        return Fail("07-reviewed/comments.json missing")
    if not evidence.exists("08-remediated/resolved_comments.json"):
        return Fail("08-remediated/resolved_comments.json missing")

    comments = evidence.read_json("07-reviewed/comments.json")
    resolved = evidence.read_json("08-remediated/resolved_comments.json")

    if not isinstance(comments, list):
        return Fail(f"comments.json is not a list: {type(comments).__name__}")
    if not isinstance(resolved, dict):
        return Fail(f"resolved_comments.json is not a dict: {type(resolved).__name__}")

    blockers = [
        c for c in comments
        if isinstance(c, dict) and (c.get("severity") or "").lower() == "blocking"
    ]
    if not blockers:
        return Pass(evidence_data={"blocker_count": 0})

    unresolved = []
    for c in blockers:
        comment_id = str(c.get("id") or c.get("comment_id") or "")
        if not comment_id:
            unresolved.append({"reason": "comment missing id", "comment": c})
            continue
        if comment_id not in resolved:
            unresolved.append({"id": comment_id, "body": c.get("body", "")[:80]})

    if unresolved:
        return Fail(
            f"{len(unresolved)} blocking comment(s) unresolved",
            evidence_data={"unresolved": unresolved[:10]},
        )

    return Pass(evidence_data={"resolved_count": len(blockers)})
