"""Unit tests for backend.temporal.gates — Phase 1C.

One test file per gate would balloon to 11 files. Bundling them here and
splitting later if a gate gets deep enough to warrant its own file.

Coverage per the test plan in phase-1-plan.md:
  - eligibility (4 cases: pass + 3 fails)
  - input_context_clean (4 cases: pass + 3 leak forms)
  - environment_works (3 cases)
  - repro_evidence_present (5 cases incl. notes word count + sections)
  - diff_non_empty (4 cases incl. all 6 jade-hare empty-PR fixtures)
  - relevance (mocked judge: pass + defer + fail + JudgeUnreachable + JudgeParseError)
  - verified_evidence_present (test path + visual path + invalid)
  - remediation_complete (3 cases)
  - no_upstream_refs (clean + leaky)
  - pr_template_compliance (no template + missing section + clean)
  - submission_judge (mocked judge: pass + defer + fail + system errors)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from temporal.evidence.store import EvidenceStore
from temporal.gates import IssueRef
from temporal.gates.eligibility import eligibility
from temporal.gates.environment import environment_works
from temporal.gates.fix import diff_non_empty, relevance
from temporal.gates.input_context_clean import input_context_clean
from temporal.gates.remediation import remediation_complete
from temporal.gates.repro import repro_evidence_present
from temporal.gates.submission import (
    no_upstream_refs,
    pr_template_compliance,
    submission_judge,
)
from temporal.gates.verify import verified_evidence_present


@pytest.fixture
def issue() -> IssueRef:
    return IssueRef(
        fork_slug="WolffM/markitdown",
        upstream_slug="microsoft/markitdown",
        upstream_number=183,
    )


@pytest.fixture
def ev(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "issue")


# ── eligibility ───────────────────────────────────────────────────────────


def _seed_eligibility_clean(ev: EvidenceStore):
    ev.write_json("01-eligible/dossier.json", {"sections": []})
    ev.write_json("01-eligible/health.json", {"maintainerHealthScore": 80})
    ev.write_json("01-eligible/issue_brief.json", {"issue": {"state": "open", "assignee": None, "title": "x", "body": "y"}})
    ev.write_json("01-eligible/contributing_check.json", {"ai_policy": "unknown", "dco_required": False, "license_check_required": False})


def test_eligibility_pass(issue, ev):
    _seed_eligibility_clean(ev)
    assert eligibility(issue, ev).verdict == "pass"


def test_eligibility_fails_on_ai_banned(issue, ev):
    _seed_eligibility_clean(ev)
    ev.write_json("01-eligible/contributing_check.json", {"ai_policy": "banned", "dco_required": False, "license_check_required": False})
    r = eligibility(issue, ev)
    assert r.verdict == "fail" and "ban" in r.reason.lower()


def test_eligibility_fails_when_already_assigned(issue, ev):
    _seed_eligibility_clean(ev)
    ev.write_json("01-eligible/issue_brief.json", {"issue": {"state": "open", "assignee": "alice", "title": "x", "body": "y"}})
    r = eligibility(issue, ev)
    assert r.verdict == "fail" and "assigned" in r.reason


def test_eligibility_fails_on_low_activity(issue, ev):
    _seed_eligibility_clean(ev)
    ev.write_json("01-eligible/health.json", {"maintainerHealthScore": 5})
    r = eligibility(issue, ev)
    assert r.verdict == "fail" and "activity" in r.reason


def test_eligibility_fails_when_dossier_missing(issue, ev):
    r = eligibility(issue, ev)
    assert r.verdict == "fail" and "dossier" in r.reason


# ── input_context_clean ───────────────────────────────────────────────────


def test_input_context_clean_pass(issue, ev):
    ev.write_text("02-forked/scrubbed_brief.md", "Generic prose with no upstream refs.")
    assert input_context_clean(issue, ev).verdict == "pass"


@pytest.mark.parametrize("brief, fragment", [
    ("see https://github.com/microsoft/markitdown/issues/183", "url"),
    ("see microsoft/markitdown#183", "short_ref"),
    ("from microsoft/markitdown", "bare_slug"),
    ("Fixes #183", "keyword_ref"),
])
def test_input_context_clean_fails_on_leak(issue, ev, brief, fragment):
    ev.write_text("02-forked/scrubbed_brief.md", brief)
    r = input_context_clean(issue, ev)
    assert r.verdict == "fail"
    assert fragment in (r.evidence_data or {}).get("leak_kinds", [])


def test_input_context_clean_missing_file(issue, ev):
    r = input_context_clean(issue, ev)
    assert r.verdict == "fail" and "missing" in r.reason


# ── environment_works ─────────────────────────────────────────────────────


def test_environment_works_pass(issue, ev):
    ev.write_json("03-environment/health.json", {"installable": True, "runnable": True})
    assert environment_works(issue, ev).verdict == "pass"


def test_environment_works_pass_when_runnable_omitted(issue, ev):
    ev.write_json("03-environment/health.json", {"installable": True})
    assert environment_works(issue, ev).verdict == "pass"


def test_environment_works_fails_on_install(issue, ev):
    ev.write_json("03-environment/health.json", {"installable": False})
    assert environment_works(issue, ev).verdict == "fail"


def test_environment_works_fails_on_dev_server(issue, ev):
    ev.write_json("03-environment/health.json", {"installable": True, "runnable": False})
    assert environment_works(issue, ev).verdict == "fail"


# ── repro_evidence_present ────────────────────────────────────────────────


_NOTES = (
    "## Steps to reproduce\n\n"
    "1. Open the example file in the editor\n"
    "2. Navigate to the merged-cells worksheet\n"
    "3. Click the convert button at the top of the page\n"
    "4. Observe the broken output in the converter pane\n\n"
    "## Observed\n\n"
    "The button crashes the application with a null pointer exception in the cell coalescing path.\n\n"
    "## Expected\n\n"
    "The button should open the dialog and convert the worksheet without crashing the application.\n"
)


def test_repro_evidence_present_pass_with_test(issue, ev):
    ev.write_text("04-reproduced/test.py", "def test_x(): pass")
    ev.write_text("04-reproduced/notes.md", _NOTES)
    assert repro_evidence_present(issue, ev).verdict == "pass"


def test_repro_evidence_present_fails_no_artifact(issue, ev):
    ev.write_text("04-reproduced/notes.md", _NOTES)
    r = repro_evidence_present(issue, ev)
    assert r.verdict == "fail"


def test_repro_evidence_present_fails_short_notes(issue, ev):
    ev.write_text("04-reproduced/test.py", "x")
    ev.write_text("04-reproduced/notes.md", "too short")
    r = repro_evidence_present(issue, ev)
    assert r.verdict == "fail" and "too short" in r.reason


def test_repro_evidence_present_fails_missing_section(issue, ev):
    ev.write_text("04-reproduced/test.py", "x")
    ev.write_text(
        "04-reproduced/notes.md",
        "## Steps to reproduce\n\nlots of words " * 10,
    )
    r = repro_evidence_present(issue, ev)
    assert r.verdict == "fail" and "Observed" in r.reason


def test_repro_evidence_present_fails_dir_missing(issue, ev):
    r = repro_evidence_present(issue, ev)
    assert r.verdict == "fail"


# ── diff_non_empty (with jade-hare-style empty-PR fixtures) ───────────────


_EMPTY_PR_FIXTURES = [
    "",                               # truly empty
    "   \n  \n",                      # whitespace-only
    "diff --git",                     # under min byte threshold
]


def _seed_fix(ev, diff: str, shas: list[str]):
    ev.write_text("05-fixed/diff.patch", diff)
    ev.write_text("05-fixed/commit_shas.txt", "\n".join(shas) + "\n" if shas else "")


def test_diff_non_empty_pass(issue, ev):
    _seed_fix(ev, "diff --git a/x b/x\n@@ -1 +1 @@\n-old\n+new line of meaningful change\n", ["abc123"])
    r = diff_non_empty(issue, ev)
    assert r.verdict == "pass"


@pytest.mark.parametrize("diff", _EMPTY_PR_FIXTURES)
def test_diff_non_empty_kills_jade_hare_class(issue, ev, diff):
    _seed_fix(ev, diff, ["abc123"])
    assert diff_non_empty(issue, ev).verdict == "fail"


def test_diff_non_empty_fails_on_no_commits(issue, ev):
    _seed_fix(ev, "diff --git a/x b/x\n@@ -1 +1 @@\n-old\n+new long enough line\n", [])
    assert diff_non_empty(issue, ev).verdict == "fail"


def test_diff_non_empty_fails_when_files_missing(issue, ev):
    r = diff_non_empty(issue, ev)
    assert r.verdict == "fail"


# ── relevance (mocked judge) ──────────────────────────────────────────────


def _seed_relevance(ev):
    ev.write_text("05-fixed/diff.patch", "diff --git a/x b/x\n@@\n-a\n+b\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_json("01-eligible/issue_brief.json", {"issue": {"title": "x", "body": "y"}})


def test_relevance_pass(monkeypatch, issue, ev):
    _seed_relevance(ev)
    from temporal import judge as j
    monkeypatch.setattr(
        "temporal.gates.fix.judge_score",
        lambda rubric, payload: j.JudgeResult(verdict="pass", score=0.9, reasoning="good", raw={}),
    )
    r = relevance(issue, ev)
    assert r.verdict == "pass"
    assert r.score == 0.9


def test_relevance_defer_borderline(monkeypatch, issue, ev):
    _seed_relevance(ev)
    from temporal import judge as j
    monkeypatch.setattr(
        "temporal.gates.fix.judge_score",
        lambda rubric, payload: j.JudgeResult(verdict="defer", score=0.55, reasoning="borderline", raw={}),
    )
    r = relevance(issue, ev)
    assert r.verdict == "defer"


def test_relevance_fail_low(monkeypatch, issue, ev):
    _seed_relevance(ev)
    from temporal import judge as j
    monkeypatch.setattr(
        "temporal.gates.fix.judge_score",
        lambda rubric, payload: j.JudgeResult(verdict="fail", score=0.2, reasoning="sprawl", raw={}),
    )
    r = relevance(issue, ev)
    assert r.verdict == "fail"


def test_relevance_defer_on_judge_unreachable(monkeypatch, issue, ev):
    _seed_relevance(ev)
    from temporal import judge as j

    def boom(rubric, payload):
        raise j.JudgeUnreachable("canary failed")

    monkeypatch.setattr("temporal.gates.fix.judge_score", boom)
    r = relevance(issue, ev)
    assert r.verdict == "defer" and "system:judge_unreachable" in r.reason


def test_relevance_defer_on_parse_error(monkeypatch, issue, ev):
    _seed_relevance(ev)
    from temporal import judge as j

    def boom(rubric, payload):
        raise j.JudgeParseError("no fenced block")

    monkeypatch.setattr("temporal.gates.fix.judge_score", boom)
    r = relevance(issue, ev)
    assert r.verdict == "defer" and "system:judge_parse_error" in r.reason


# ── verified_evidence_present ─────────────────────────────────────────────


def test_verified_pass_with_test(issue, ev):
    ev.write_text("06-verified/test_output.txt", "10 passed in 1.5s")
    assert verified_evidence_present(issue, ev).verdict == "pass"


def test_verified_pass_with_visual_diff(issue, ev):
    ev.write_bytes("06-verified/after.png", b"\x89PNG\r\n")
    ev.write_json("06-verified/diff_from_repro.json", {"visual_diff_score": 0.42})
    r = verified_evidence_present(issue, ev)
    assert r.verdict == "pass"


def test_verified_fails_on_visually_identical(issue, ev):
    ev.write_bytes("06-verified/after.png", b"\x89PNG\r\n")
    ev.write_json("06-verified/diff_from_repro.json", {"visual_diff_score": 0.001})
    r = verified_evidence_present(issue, ev)
    assert r.verdict == "fail"


def test_verified_fails_no_artifact(issue, ev):
    ev.path("06-verified").mkdir(parents=True, exist_ok=True)
    r = verified_evidence_present(issue, ev)
    assert r.verdict == "fail"


def test_verified_fails_dir_missing(issue, ev):
    r = verified_evidence_present(issue, ev)
    assert r.verdict == "fail"


# ── remediation_complete ──────────────────────────────────────────────────


def test_remediation_pass_when_no_blockers(issue, ev):
    ev.write_json("07-reviewed/comments.json", [
        {"id": "c1", "severity": "nit", "body": "minor"},
    ])
    ev.write_json("08-remediated/resolved_comments.json", {})
    assert remediation_complete(issue, ev).verdict == "pass"


def test_remediation_pass_when_all_blockers_resolved(issue, ev):
    ev.write_json("07-reviewed/comments.json", [
        {"id": "c1", "severity": "blocking", "body": "fix this"},
        {"id": "c2", "severity": "blocking", "body": "and this"},
    ])
    ev.write_json("08-remediated/resolved_comments.json", {"c1": "fixed", "c2": "fixed"})
    assert remediation_complete(issue, ev).verdict == "pass"


def test_remediation_fails_when_blocker_unresolved(issue, ev):
    ev.write_json("07-reviewed/comments.json", [
        {"id": "c1", "severity": "blocking", "body": "fix this"},
        {"id": "c2", "severity": "blocking", "body": "and this"},
    ])
    ev.write_json("08-remediated/resolved_comments.json", {"c1": "fixed"})
    r = remediation_complete(issue, ev)
    assert r.verdict == "fail" and "unresolved" in r.reason


# ── no_upstream_refs ──────────────────────────────────────────────────────


def test_no_upstream_refs_pass(issue, ev):
    ev.write_text("09-submittable/pr_title.txt", "Fix XLSX merged-cell handling")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nClean body.\n")
    assert no_upstream_refs(issue, ev).verdict == "pass"


def test_no_upstream_refs_catches_url_in_body(issue, ev):
    ev.write_text("09-submittable/pr_title.txt", "Fix XLSX")
    ev.write_text(
        "09-submittable/pr_body.md",
        "See https://github.com/microsoft/markitdown/issues/183",
    )
    r = no_upstream_refs(issue, ev)
    assert r.verdict == "fail"


def test_no_upstream_refs_catches_commit_message_leak(issue, ev):
    ev.write_text("09-submittable/pr_title.txt", "Clean")
    ev.write_text("09-submittable/pr_body.md", "Clean")
    ev.write_json("05-fixed/commits.json", [
        {"sha": "abc", "message": "Fixes microsoft/markitdown#183"},
    ])
    r = no_upstream_refs(issue, ev)
    assert r.verdict == "fail"


# ── pr_template_compliance ────────────────────────────────────────────────


def test_pr_template_compliance_pass_when_no_template(issue, ev):
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFixes thing.\n")
    assert pr_template_compliance(issue, ev).verdict == "pass"


def test_pr_template_compliance_pass_when_all_sections_present(issue, ev):
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix.\n\n## Test plan\n\nTested.\n")
    ev.write_json("09-submittable/template.json", {
        "sections": [
            {"heading": "## Summary", "required": True},
            {"heading": "## Test plan", "required": True},
        ],
    })
    assert pr_template_compliance(issue, ev).verdict == "pass"


def test_pr_template_compliance_fails_on_missing_section(issue, ev):
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFix.\n")
    ev.write_json("09-submittable/template.json", {
        "sections": [
            {"heading": "## Summary", "required": True},
            {"heading": "## Test plan", "required": True},
        ],
    })
    r = pr_template_compliance(issue, ev)
    assert r.verdict == "fail" and "Test plan" in r.reason


# ── submission_judge ──────────────────────────────────────────────────────


def _seed_submission(ev):
    ev.write_text("09-submittable/pr_title.txt", "Fix x")
    ev.write_text("09-submittable/pr_body.md", "## Summary\n\nFixed it.\n")
    ev.write_text("05-fixed/files_touched.txt", "src/x.py\n")
    ev.write_text("05-fixed/diff.patch", "diff " * 50)
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")


def test_submission_judge_pass(monkeypatch, issue, ev):
    _seed_submission(ev)
    from temporal import judge as j
    monkeypatch.setattr(
        "temporal.gates.submission.judge_score",
        lambda rubric, payload: j.JudgeResult(verdict="pass", score=0.92, reasoning="defensible", raw={}),
    )
    assert submission_judge(issue, ev).verdict == "pass"


def test_submission_judge_defer_borderline(monkeypatch, issue, ev):
    _seed_submission(ev)
    from temporal import judge as j
    monkeypatch.setattr(
        "temporal.gates.submission.judge_score",
        lambda rubric, payload: j.JudgeResult(verdict="defer", score=0.65, reasoning="thin", raw={}),
    )
    assert submission_judge(issue, ev).verdict == "defer"


def test_submission_judge_fails_low_score(monkeypatch, issue, ev):
    _seed_submission(ev)
    from temporal import judge as j
    monkeypatch.setattr(
        "temporal.gates.submission.judge_score",
        lambda rubric, payload: j.JudgeResult(verdict="fail", score=0.18, reasoning="slop", raw={}),
    )
    assert submission_judge(issue, ev).verdict == "fail"


def test_submission_judge_defers_on_unreachable(monkeypatch, issue, ev):
    _seed_submission(ev)
    from temporal import judge as j

    def boom(rubric, payload):
        raise j.JudgeUnreachable("canary failed")

    monkeypatch.setattr("temporal.gates.submission.judge_score", boom)
    r = submission_judge(issue, ev)
    assert r.verdict == "defer" and "system:judge_unreachable" in r.reason
