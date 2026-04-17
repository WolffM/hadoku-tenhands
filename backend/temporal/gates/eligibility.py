"""Eligibility gate — runs after `eligible` state.

Reads the dossier + brief + contributing-check that the eligibility
activity wrote to evidence. Refuses hostile repos (AI-banned), already-
claimed issues, and abandoned repos.

See docs/crimson-kitty/gates.md `eligibility` section.
"""

from __future__ import annotations

from . import Defer, Fail, GateResult, IssueRef, Pass, gate


@gate(after="eligible", kind="mechanical")
def eligibility(issue: IssueRef, evidence) -> GateResult:
    if not evidence.exists("01-eligible/dossier.json"):
        return Fail("01-eligible/dossier.json missing")
    if not evidence.exists("01-eligible/issue_brief.json"):
        return Fail("01-eligible/issue_brief.json missing")
    if not evidence.exists("01-eligible/contributing_check.json"):
        return Fail("01-eligible/contributing_check.json missing")

    brief = evidence.read_json("01-eligible/issue_brief.json")
    contrib = evidence.read_json("01-eligible/contributing_check.json")

    # Reject if the aggregator returned a stub instead of real brief data.
    # {"status": "pending"} means the issue hasn't been indexed — there's
    # nothing for the agent to work from.
    if brief.get("status") == "pending" or not brief.get("issue"):
        return Fail(
            "issue brief has no content (aggregator returned pending/empty)",
            evidence_data={"brief_keys": list(brief.keys()) if isinstance(brief, dict) else []},
        )

    if contrib.get("ai_policy") == "banned":
        return Fail(
            "repo CONTRIBUTING.md bans AI-generated PRs",
            evidence_data={"ai_policy": "banned"},
        )

    issue_obj = brief.get("issue", {}) if isinstance(brief, dict) else {}
    if issue_obj.get("assignee"):
        return Fail(
            f"issue already assigned to {issue_obj['assignee']}",
            evidence_data={"assignee": issue_obj["assignee"]},
        )
    if issue_obj.get("state") and issue_obj["state"] != "open":
        return Fail(f"issue state is {issue_obj['state']}, not open")

    health = evidence.read_json("01-eligible/health.json") if evidence.exists("01-eligible/health.json") else {}
    activity = health.get("maintainerHealthScore", 0)
    if isinstance(activity, (int, float)) and activity < 10:
        return Fail(
            f"repo activity below threshold: {activity}",
            evidence_data={"activity_score": activity},
        )

    return Pass()
