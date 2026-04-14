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

    dossier = evidence.read_json("01-eligible/dossier.json")
    brief = evidence.read_json("01-eligible/issue_brief.json")
    contrib = evidence.read_json("01-eligible/contributing_check.json")

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

    health = dossier.get("health", {}) if isinstance(dossier, dict) else {}
    activity = health.get("activity_score", 0)
    if isinstance(activity, (int, float)) and activity < 0.3:
        return Fail(
            f"repo activity below threshold: {activity}",
            evidence_data={"activity_score": activity},
        )

    return Pass()
