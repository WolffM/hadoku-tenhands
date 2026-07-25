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
    body_lint,
    no_source_touched,
    no_upstream_refs,
    pr_template_compliance,
    submission_judge,
    verification_health,
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


def test_eligibility_fails_when_brief_is_pending(issue, ev):
    _seed_eligibility_clean(ev)
    ev.write_json("01-eligible/issue_brief.json", {"status": "pending"})
    r = eligibility(issue, ev)
    assert r.verdict == "fail" and "no content" in r.reason


def test_eligibility_fails_when_brief_has_no_issue(issue, ev):
    _seed_eligibility_clean(ev)
    ev.write_json("01-eligible/issue_brief.json", {"something": "else"})
    r = eligibility(issue, ev)
    assert r.verdict == "fail" and "no content" in r.reason


# ── input_context_clean ───────────────────────────────────────────────────


def test_input_context_clean_fails_when_brief_empty(issue, ev):
    ev.write_text("02-forked/scrubbed_brief.md", "")
    r = input_context_clean(issue, ev)
    assert r.verdict == "fail" and "empty" in r.reason


def test_input_context_clean_fails_when_brief_whitespace(issue, ev):
    ev.write_text("02-forked/scrubbed_brief.md", "   \n  \n  ")
    r = input_context_clean(issue, ev)
    assert r.verdict == "fail" and "empty" in r.reason


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
    ev.write_text("03-environment/install_log.txt", "returncode=0\nsuccess=True\n--- stdout ---\nInstalled 42 packages\n--- stderr ---\n")
    assert environment_works(issue, ev).verdict == "pass"


def test_environment_works_pass_when_runnable_omitted(issue, ev):
    ev.write_json("03-environment/health.json", {"installable": True})
    ev.write_text("03-environment/install_log.txt", "returncode=0\nsuccess=True\n--- stdout ---\npip install complete\n--- stderr ---\n")
    assert environment_works(issue, ev).verdict == "pass"


def test_environment_works_fails_on_install(issue, ev):
    ev.write_json("03-environment/health.json", {"installable": False})
    assert environment_works(issue, ev).verdict == "fail"


def test_environment_works_fails_on_dev_server(issue, ev):
    ev.write_json("03-environment/health.json", {"installable": True, "runnable": False})
    assert environment_works(issue, ev).verdict == "fail"


def test_environment_works_fails_on_noop_install(issue, ev):
    ev.write_json("03-environment/health.json", {"installable": True})
    ev.write_text("03-environment/install_log.txt", "returncode=0\nsuccess=True\n--- stdout ---\n\n--- stderr ---\n")
    r = environment_works(issue, ev)
    assert r.verdict == "fail" and "no output" in r.reason


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


def test_repro_evidence_present_pass_with_lint_output(issue, ev):
    ev.write_text("04-reproduced/lint_output.txt", "test_signer.py:1:1: F401 'os' imported but unused")
    ev.write_text("04-reproduced/notes.md", _NOTES)
    r = repro_evidence_present(issue, ev)
    assert r.verdict == "pass"
    assert "lint_output.txt" in r.evidence_data["artifacts"]


def test_repro_evidence_present_fails_dir_missing(issue, ev):
    r = repro_evidence_present(issue, ev)
    assert r.verdict == "fail"


def test_repro_evidence_present_passes_with_plain_labels(issue, ev):
    """Copilot often writes section labels WITHOUT the `##` prefix.
    Regression for B16 (v7 airflow aborted on this): the gate must
    accept plain labels as headings."""
    ev.write_text("04-reproduced/test.py", "x")
    ev.write_text(
        "04-reproduced/notes.md",
        "Steps to Reproduce\n1. Run the thing.\n2. It crashes.\n\n"
        "Observed\nStack trace shows " + ("boom " * 30) + "\n\n"
        "Expected\nNo crash, clean shutdown instead.\n",
    )
    r = repro_evidence_present(issue, ev)
    assert r.verdict == "pass", r.reason


def test_repro_evidence_present_passes_with_bold_labels(issue, ev):
    """Markdown bold (`**Observed**`) is another common style."""
    ev.write_text("04-reproduced/test.py", "x")
    ev.write_text(
        "04-reproduced/notes.md",
        "**Steps to reproduce**\n1. Run the reproduction script.\n\n"
        "**Observed**\n" + ("It broke with an error message. " * 10) + "\n\n"
        "**Expected**\nShould not break under these conditions.\n",
    )
    r = repro_evidence_present(issue, ev)
    assert r.verdict == "pass", r.reason


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


def test_verified_pass_with_verify_notes_md(issue, ev):
    """B20: adopted Copilot PRs bundle tests into fix commits and rarely
    produce a standalone test_output.txt or after.png. The gate now
    accepts verify_notes.md (auto-synthesized by request_verify) as a
    lightweight fallback."""
    ev.write_text(
        "06-verified/verify_notes.md",
        "## Verification basis\n\n"
        "The agent committed tests alongside the fix. The exit_reason "
        "was success and the PR includes test files exercising the new "
        "behavior directly in the diff.",
    )
    r = verified_evidence_present(issue, ev)
    assert r.verdict == "pass"
    assert r.evidence_data["verification_kind"] == "synthesized_notes"


def test_verified_fails_on_short_verify_notes(issue, ev):
    """Even with the lenient fallback, nonsense-short notes must fail."""
    ev.write_text("06-verified/verify_notes.md", "too short")
    r = verified_evidence_present(issue, ev)
    assert r.verdict == "fail"


def test_verified_prefers_test_output_over_verify_notes(issue, ev):
    """If the agent wrote a real test_output.txt AND there's a notes
    fallback, the real artifact wins — we want the strongest evidence
    to be what the gate reports."""
    ev.write_text("06-verified/test_output.txt", "5 passed in 2.1s")
    ev.write_text("06-verified/verify_notes.md", "lots of words " * 10)
    r = verified_evidence_present(issue, ev)
    assert r.verdict == "pass"
    assert r.evidence_data["verification_kind"] == "test"


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


# ── body_lint ─────────────────────────────────────────────────────────────


def test_body_lint_pass_on_clean_body(issue, ev):
    ev.write_text(
        "09-submittable/pr_body.md",
        "## Summary\n\nReal content.\n\n## Fix\n\nMore content.\n",
    )
    assert body_lint(issue, ev).verdict == "pass"


def test_body_lint_fails_on_empty_section(issue, ev):
    # vitest#8107 — Summary header with no content beneath it.
    ev.write_text(
        "09-submittable/pr_body.md",
        "## Summary\n\n## Fix\n\nThe change does X.\n",
    )
    r = body_lint(issue, ev)
    assert r.verdict == "fail" and "empty section" in r.reason


def test_body_lint_fails_on_duplicate_heading(issue, ev):
    # terminal#5366 — two "Steps to reproduce" sections.
    ev.write_text(
        "09-submittable/pr_body.md",
        "## Summary\n\nA.\n\n## Steps to reproduce\n\nB.\n\n"
        "## Steps to reproduce\n\nC.\n",
    )
    r = body_lint(issue, ev)
    assert r.verdict == "fail" and "duplicate heading" in r.reason


def test_body_lint_fails_on_unbalanced_code_fences(issue, ev):
    ev.write_text(
        "09-submittable/pr_body.md",
        "## Summary\n\n```\nopen fence with no close\n",
    )
    r = body_lint(issue, ev)
    assert r.verdict == "fail" and "code fences" in r.reason


# ── no_source_touched ─────────────────────────────────────────────────────


def test_no_source_touched_pass_with_real_source(issue, ev):
    ev.write_text("05-fixed/files_touched.txt", "src/foo.py\ntests/test_foo.py\n")
    assert no_source_touched(issue, ev).verdict == "pass"


def test_no_source_touched_fails_when_only_notes_and_tests(issue, ev):
    # bun#15964 — agent committed only notes.md + a test file, zero source.
    ev.write_text("05-fixed/files_touched.txt", "notes.md\ntests/test_foo.py\n")
    r = no_source_touched(issue, ev)
    assert r.verdict == "fail" and "no source files" in r.reason


def test_no_source_touched_treats_top_level_md_as_source(issue, ev):
    # A genuine README/docs fix should pass — only test files and notes.md
    # are excluded.
    ev.write_text("05-fixed/files_touched.txt", "README.md\n")
    assert no_source_touched(issue, ev).verdict == "pass"


# ── verification_health ───────────────────────────────────────────────────


def test_verification_health_pass_on_no_test_output(issue, ev):
    # No test_output.txt → synth was skipped → trivially healthy.
    assert verification_health(issue, ev).verdict == "pass"


def test_verification_health_pass_on_clean_output(issue, ev):
    ev.write_text(
        "06-verified/test_output.txt",
        "PASS  src/foo.test.ts\n  ✓ widget renders\n\nTests: 1 passed",
    )
    assert verification_health(issue, ev).verdict == "pass"


def test_verification_health_fails_on_pnpm_recursive_error(issue, ev):
    # vitest#8107 — the exact infra error pattern that gaslit the judge.
    ev.write_text(
        "06-verified/test_output.txt",
        "ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL  packages/vitest@3.0.0 test: ...\n",
    )
    r = verification_health(issue, ev)
    assert r.verdict == "fail" and "infrastructure error" in r.reason


def test_verification_health_fails_on_module_not_found(issue, ev):
    ev.write_text("06-verified/test_output.txt", "Error: Cannot find module 'foo'\n")
    r = verification_health(issue, ev)
    assert r.verdict == "fail"


def test_verification_health_passes_on_test_failures_not_infra(issue, ev):
    # Genuine test failures aren't this gate's job — that's a judge call.
    ev.write_text(
        "06-verified/test_output.txt",
        "FAIL  src/foo.test.ts\n  ✕ widget renders\n\nTests: 1 failed",
    )
    assert verification_health(issue, ev).verdict == "pass"


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


def test_submission_judge_payload_strips_notes_md(monkeypatch, issue, ev):
    """2026-05-21: the judge payload's 'Fix summary' listed notes.md (3
    files) while the PR body's 'Files changed' stripped it (2 files). The
    judge correctly flagged the 2-vs-3 mismatch. The payload must apply
    the same _TREE_STRIP_PATHS filter so both counts agree."""
    ev.write_text("09-submittable/pr_title.txt", "Fix x")
    ev.write_text(
        "09-submittable/pr_body.md",
        "## Summary\n\nFixed it.\n\n## Fix\n\nFiles changed (2):\n\n- `a.py`\n- `b.py`\n",
    )
    ev.write_text("05-fixed/files_touched.txt", "a.py\nb.py\nnotes.md\n")
    ev.write_text("05-fixed/diff.patch", "diff " * 50)
    ev.write_text("05-fixed/commit_shas.txt", "abc\n")

    captured = {}
    from temporal import judge as j

    def capture(rubric, payload):
        captured["payload"] = payload
        return j.JudgeResult(verdict="pass", score=0.9, reasoning="ok", raw={})

    monkeypatch.setattr("temporal.gates.submission.judge_score", capture)
    submission_judge(issue, ev)

    payload = captured["payload"]
    assert "files touched: 2" in payload
    assert "notes.md" not in payload


# ── Pipeline namespacing ──────────────────────────────────────────────────


class TestPipelineNamespacing:
    """Two pipelines share one process and one registry, and their state
    names collide (`fixed` exists in both). Without a namespace,
    crimson-kitty's submission gates would run against a hadoku-task
    task that has no upstream at all. These tests are the guard."""

    def test_run_gates_ignores_gates_from_another_pipeline(self, issue, ev):
        """The core cross-fire case: same state name, different pipeline."""
        from temporal.gates import (
            CRIMSON_KITTY, TASK_AUTOMATION, isolated_registry,
            gate, Pass, run_gates,
        )

        with isolated_registry():
            fired = []

            @gate(pipeline=CRIMSON_KITTY, after="fixed", kind="mechanical")
            def crimson_only(issue, evidence):
                fired.append("crimson")
                return Pass()

            @gate(pipeline=TASK_AUTOMATION, after="fixed", kind="mechanical")
            def taskauto_only(issue, evidence):
                fired.append("taskauto")
                return Pass()

            results = run_gates("fixed", issue, ev, pipeline=CRIMSON_KITTY)
            assert fired == ["crimson"]
            assert [r.name for r in results] == ["crimson_only"]

            fired.clear()
            results = run_gates("fixed", issue, ev, pipeline=TASK_AUTOMATION)
            assert fired == ["taskauto"]
            assert [r.name for r in results] == ["taskauto_only"]

    def test_unknown_pipeline_runs_nothing(self, issue, ev):
        """A typo in a pipeline name must be inert, never a silent
        fall-through to somebody else's gates."""
        from temporal.gates import (
            CRIMSON_KITTY, isolated_registry, gate, Pass, run_gates,
        )

        with isolated_registry():
            @gate(pipeline=CRIMSON_KITTY, after="fixed", kind="mechanical")
            def crimson_only(issue, evidence):
                return Pass()

            assert run_gates("fixed", issue, ev, pipeline="crimson-kitteh") == []

    def test_pipeline_is_required_on_gate(self):
        """No default: a new gate that forgets the argument must fail loudly
        at import time rather than register into the wrong pipeline."""
        from temporal.gates import gate

        with pytest.raises(TypeError):
            gate(after="fixed", kind="mechanical")

    def test_pipeline_is_required_on_run_gates(self, issue, ev):
        from temporal.gates import run_gates

        with pytest.raises(TypeError):
            run_gates("fixed", issue, ev)

    def test_registry_snapshot_filters_and_reports_pipeline(self, issue, ev):
        from temporal.gates import (
            CRIMSON_KITTY, TASK_AUTOMATION, isolated_registry,
            gate, Pass, registry_snapshot,
        )

        with isolated_registry():
            @gate(pipeline=CRIMSON_KITTY, after="fixed", kind="mechanical")
            def a(issue, evidence):
                return Pass()

            @gate(pipeline=TASK_AUTOMATION, after="fixed", kind="judge")
            def b(issue, evidence):
                return Pass()

            assert registry_snapshot() == [
                (CRIMSON_KITTY, "fixed", "mechanical", "a"),
                (TASK_AUTOMATION, "fixed", "judge", "b"),
            ]
            assert registry_snapshot(CRIMSON_KITTY) == [
                (CRIMSON_KITTY, "fixed", "mechanical", "a"),
            ]

    def test_every_real_gate_declares_a_known_pipeline(self):
        """Guards against a typo'd pipeline string in a real gate module,
        which would make that gate silently never run."""
        from temporal.gates import (
            CRIMSON_KITTY, TASK_AUTOMATION, registry_snapshot,
        )
        from temporal.gates import (  # noqa: F401  — populates the registry
            actionability, eligibility, environment, fix,
            input_context_clean, remediation, repro, submission, verify,
        )

        known = {CRIMSON_KITTY, TASK_AUTOMATION}
        snap = registry_snapshot()
        assert snap, "registry is empty — gate modules failed to import"
        unknown = {p for p, _, _, _ in snap} - known
        assert not unknown, f"gates registered under unknown pipeline(s): {unknown}"

    def test_crimson_kitty_registry_is_unchanged_by_namespacing(self):
        """The namespacing change is meant to be mechanical. Every gate that
        existed before it must still be registered, under crimson-kitty,
        after the same state."""
        from temporal.gates import CRIMSON_KITTY, registry_snapshot
        from temporal.gates import (  # noqa: F401
            actionability, eligibility, environment, fix,
            input_context_clean, remediation, repro, submission, verify,
        )

        got = {(after, name) for p, after, _, name in registry_snapshot(CRIMSON_KITTY)}
        expected = {
            ("eligible", "actionability"),
            ("eligible", "eligibility"),
            ("environment_ready", "environment_works"),
            ("fixed", "diff_non_empty"),
            ("fixed", "relevance"),
            ("forked", "input_context_clean"),
            ("remediated", "remediation_complete"),
            ("reproduced", "repro_evidence_present"),
            ("reproduced", "repro_actually_reproduced"),
            ("reproduced", "repro_scope_match"),
            ("submittable", "no_upstream_refs"),
            ("submittable", "pr_template_compliance"),
            ("submittable", "body_lint"),
            ("submittable", "no_source_touched"),
            ("submittable", "verification_health"),
            ("submittable", "body_diff_coherence"),
            ("submittable", "submission_judge"),
            ("verified", "verified_evidence_present"),
        }
        assert got == expected, (
            f"registry drift — lost: {expected - got}, gained: {got - expected}"
        )


# ── M0(c): uniform gate-decision telemetry ────────────────────────────────


class TestUniformGateDecisionTelemetry:
    """Every gate result must be mirrored to gate_decisions/<name>.json so
    funnel analysis is a one-line read per gate. Telemetry must never
    block the gate runner."""

    def test_run_gates_writes_decision_per_gate(self, issue, ev):
        from temporal.gates import (
            CRIMSON_KITTY, isolated_registry, gate, Pass, Fail, run_gates,
        )

        with isolated_registry():
            @gate(pipeline=CRIMSON_KITTY, after="x", kind="mechanical")
            def passes(issue, evidence):
                return Pass("looks good")

            @gate(pipeline=CRIMSON_KITTY, after="x", kind="mechanical")
            def fails(issue, evidence):
                return Fail("nope", score=0.1)

            results = run_gates("x", issue, ev, pipeline=CRIMSON_KITTY)
            assert {r.verdict for r in results} == {"pass", "fail"}

            pass_record = ev.read_json("gate_decisions/passes.json")
            assert pass_record["verdict"] == "pass"
            assert pass_record["reason"] == "looks good"
            assert pass_record["kind"] == "mechanical"
            assert pass_record["at"]  # ISO timestamp present

            fail_record = ev.read_json("gate_decisions/fails.json")
            assert fail_record["verdict"] == "fail"
            assert fail_record["score"] == 0.1

    def test_run_gates_writes_decision_for_crashed_gate(self, issue, ev):
        """A gate that raises an exception still gets a decision file
        with the system:gate_crashed reason so the funnel attribution
        is preserved."""
        from temporal.gates import (
            CRIMSON_KITTY, isolated_registry, gate, run_gates,
        )

        with isolated_registry():
            @gate(pipeline=CRIMSON_KITTY, after="y", kind="mechanical")
            def explodes(issue, evidence):
                raise RuntimeError("boom")

            results = run_gates("y", issue, ev, pipeline=CRIMSON_KITTY)
            assert len(results) == 1
            assert results[0].verdict == "defer"

            record = ev.read_json("gate_decisions/explodes.json")
            assert record["verdict"] == "defer"
            assert "system:gate_crashed" in record["reason"]
            assert "RuntimeError" in record["reason"]

    def test_run_gates_does_not_block_on_disk_failure(self, issue):
        """If evidence.write_json raises (e.g. disk full, permission),
        the gate result must still propagate via the return list.
        Telemetry is observation, not enforcement."""
        from temporal.gates import (
            CRIMSON_KITTY, isolated_registry, gate, Pass, run_gates,
        )

        class FlakyEvidence:
            def write_json(self, path, payload):
                raise OSError("disk full")

        with isolated_registry():
            @gate(pipeline=CRIMSON_KITTY, after="z", kind="mechanical")
            def passes(issue, evidence):
                return Pass("still works")

            results = run_gates("z", issue, FlakyEvidence(), pipeline=CRIMSON_KITTY)
            assert len(results) == 1
            assert results[0].verdict == "pass"

    def test_run_gates_overwrites_prior_decision(self, issue, ev):
        """Re-running a gate after a remediation cycle must overwrite the
        prior decision file rather than append. The decision file holds
        the LATEST verdict; the historical trail lives in gates.jsonl."""
        from temporal.gates import (
            CRIMSON_KITTY, isolated_registry, gate, Pass, Fail, run_gates,
        )

        verdict_seq = ["fail", "pass"]

        with isolated_registry():
            @gate(pipeline=CRIMSON_KITTY, after="rerun", kind="mechanical")
            def cycles(issue, evidence):
                v = verdict_seq.pop(0)
                return Fail("first try") if v == "fail" else Pass("retry ok")

            run_gates("rerun", issue, ev, pipeline=CRIMSON_KITTY)
            first = ev.read_json("gate_decisions/cycles.json")
            assert first["verdict"] == "fail"

            run_gates("rerun", issue, ev, pipeline=CRIMSON_KITTY)
            second = ev.read_json("gate_decisions/cycles.json")
            assert second["verdict"] == "pass"
            assert second["reason"] == "retry ok"
