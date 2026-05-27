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
import re

from ..activities.submission import _TREE_STRIP_PATHS, _looks_like_test_file
from ..judge import (
    JudgeParseError,
    JudgeUnreachable,
    score as judge_score,
)
from ..sanitizer import SanitizerError, scan_outputs
from . import Defer, Fail, GateResult, IssueRef, Pass, gate

MIN_SUBMISSION_SCORE_PASS = 0.75
MIN_SUBMISSION_SCORE_DEFER = 0.55

# Tool/infra error fingerprints that should never appear in a Verification
# section. These mean the test command itself couldn't run — the run hasn't
# proven anything and the captured output would gaslight the judge.
_INFRA_ERROR_PATTERNS = (
    "ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL",
    "ERR_PNPM",
    "command not found",
    "Cannot find module",
    "Module not found",
    "No such file or directory",
    "ECONNREFUSED",
    "EACCES",
)

# Path pattern for `body_diff_coherence`. Matches things that look like
# repo-relative paths with an extension (`pkg/api/handlers/foo.go`,
# `src/utils/parse.ts`, `cmd/podman/compose.go`). Avoids matching URLs
# (caller pre-strips `http(s)://` chunks) and bare module imports.
_PATH_IN_PROSE_RE = re.compile(
    r"\b("                                                  # whole-word
    r"(?:[\w.-]+/){1,8}"                                    # one or more dir segments
    r"[\w.-]+"                                              # final segment
    r"\.[A-Za-z0-9]{1,6}"                                   # extension
    r")\b"
)
# URLs that include paths-with-extensions and would otherwise match
# `_PATH_IN_PROSE_RE`. We strip these from the prose before path-extract.
_URL_RE = re.compile(r"https?://\S+")


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


# ── body_lint (mechanical) ────────────────────────────────────────────────


_MD_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


@gate(after="submittable", kind="mechanical")
def body_lint(issue: IssueRef, evidence) -> GateResult:
    """Reject mechanically-malformed PR bodies before the judge sees them.

    Catches three render-bug classes the submission_judge previously had
    to flag as content problems (vitest's empty Summary, terminal's
    duplicate "Steps to reproduce", openlibrary's unclosed/truncated code
    snippet). These are renderer defects, not content judgement — failing
    them here forces a re-render rather than burning a judge call.

    Title truncation isn't checked here — `_build_title` now word-snaps
    with `…` so a title that ends in `…` is intentional, not garbled.
    """
    if not evidence.exists("09-submittable/pr_body.md"):
        return Fail("pr_body.md missing")
    body = evidence.read_text("09-submittable/pr_body.md")

    issues: list[str] = []

    # 1. Unclosed/unbalanced code fences.
    fence_count = body.count("```")
    if fence_count % 2 != 0:
        issues.append(f"unbalanced code fences (found {fence_count} ```)")

    # 2. Scan headings: collect order + bodies between them.
    lines = body.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_head: str | None = None
    current_body: list[str] = []
    for line in lines:
        m = _MD_HEADING_RE.match(line)
        if m:
            if current_head is not None:
                sections.append((current_head, current_body))
            current_head = m.group(1).strip()
            current_body = []
        else:
            current_body.append(line)
    if current_head is not None:
        sections.append((current_head, current_body))

    # 3. Empty sections (header with no non-blank content beneath it).
    for head, content in sections:
        if not any(line.strip() for line in content):
            issues.append(f"empty section under heading '{head}'")

    # 4. Duplicate headings.
    seen: dict[str, int] = {}
    for head, _ in sections:
        seen[head] = seen.get(head, 0) + 1
    for head, count in seen.items():
        if count > 1:
            issues.append(f"duplicate heading '{head}' (appears {count} times)")

    if issues:
        evidence.write_json(
            "09-submittable/body_lint.json",
            {"failures": issues, "section_count": len(sections)},
        )
        return Fail(
            f"PR body has {len(issues)} structural issue(s): {'; '.join(issues[:3])}",
            evidence_data={"failures": issues},
        )
    return Pass(evidence_data={"section_count": len(sections)})


# ── no_source_touched (mechanical) ────────────────────────────────────────


@gate(after="submittable", kind="mechanical")
def no_source_touched(issue: IssueRef, evidence) -> GateResult:
    """Fail when the agent only touched tests / scratch files / nothing.

    Hit by the bun#15964 case: agent committed `notes.md` + a test file
    and nothing else. That's not a scope-creep problem — it's an
    "agent didn't actually implement the fix" problem. Better to catch
    that here than burn a judge call on a PR with zero real change.
    """
    if not evidence.exists("05-fixed/files_touched.txt"):
        return Fail("files_touched.txt missing")

    files = [
        l.strip()
        for l in evidence.read_text("05-fixed/files_touched.txt").splitlines()
        if l.strip()
    ]
    # Strip scratch files we already remove from the PR tree.
    files = [f for f in files if f not in _TREE_STRIP_PATHS]
    non_test = [f for f in files if not _looks_like_test_file(f)]

    if not non_test:
        return Fail(
            "diff only contains test files and/or scratch notes — no source "
            "files were touched. Likely the agent did not implement the fix.",
            evidence_data={
                "files_touched": files,
                "test_only": True,
            },
        )
    return Pass(evidence_data={"non_test_file_count": len(non_test)})


# ── verification_health (mechanical) ──────────────────────────────────────


@gate(after="submittable", kind="mechanical")
def verification_health(issue: IssueRef, evidence) -> GateResult:
    """Block when the captured test output advertises a tool failure as
    verification evidence.

    vitest#8107 had `ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL` in its captured
    output — pnpm's spawn-the-test-runner step itself failed, so the
    run-test-command run proved nothing. Letting that through forced the
    judge to wade through a broken verification block; cheaper to fail
    here and force a real verification (or accept that this issue can't
    be auto-verified at all).

    Genuine test failures (`FAIL: test_foo`) are NOT caught here — those
    are content judgements for the judge, not mechanical errors.
    """
    path = "06-verified/test_output.txt"
    if not evidence.exists(path):
        return Pass(reason="no test output captured (synth skipped)")
    text = evidence.read_text(path)
    if not text.strip():
        return Pass(reason="test output is empty")

    matched = [p for p in _INFRA_ERROR_PATTERNS if p.lower() in text.lower()]
    if matched:
        return Fail(
            f"captured test output contains infrastructure error(s): "
            f"{', '.join(matched[:3])}. The test command itself didn't run, "
            f"so the Verification section would gaslight reviewers.",
            evidence_data={"matched_patterns": matched},
        )
    return Pass()


# ── body_diff_coherence (mechanical) ──────────────────────────────────────


@gate(after="submittable", kind="mechanical")
def body_diff_coherence(issue: IssueRef, evidence) -> GateResult:
    """Block when the PR body's prose claims to fix files the diff didn't touch.

    Today's defer pattern (2026-05-27 batch): podman#26383's body
    described fixing `cmd/podman/compose.go` (forcibly setting
    `DOCKER_BUILDKIT=0`), but the actually-touched files were in
    `pkg/api/handlers/` and `pkg/api/server/`. submission_judge caught
    this as a 0.65 borderline. Doing it mechanically up front saves the
    judge call and gives a clearer signal to the operator.

    Heuristic: extract paths-with-extensions from the body's prose
    sections (ignoring the structured `Files changed:` bullet list,
    which is built from files_touched and tautologically matches).
    For each path mentioned in prose, require either an exact match in
    files_touched OR a basename match. If neither, the body is claiming
    a file the diff didn't touch.

    Reverse direction (files touched but not mentioned in prose) is
    NOT a failure — the agent may have omitted explaining every file
    edit and that's the submission_judge's call, not a mechanical
    contradiction.
    """
    if not evidence.exists("09-submittable/pr_body.md"):
        return Fail("pr_body.md missing")
    if not evidence.exists("05-fixed/files_touched.txt"):
        return Pass(reason="no files_touched.txt to compare against")

    body = evidence.read_text("09-submittable/pr_body.md")
    files_touched = [
        l.strip()
        for l in evidence.read_text("05-fixed/files_touched.txt").splitlines()
        if l.strip()
    ]
    files_touched = [f for f in files_touched if f not in _TREE_STRIP_PATHS]
    if not files_touched:
        return Pass(reason="no source files touched")

    # Carve out the structured `Files changed:` bullet list — those are
    # rendered from files_touched and tautologically match.
    prose = body
    files_changed_match = re.search(
        r"\n(?:Files changed[^\n]*:)\n",
        body,
    )
    if files_changed_match:
        # Drop from the "Files changed:" header to the next blank line +
        # next heading (whichever comes first).
        start = files_changed_match.start()
        tail = body[files_changed_match.end():]
        next_heading = re.search(r"\n##\s", tail)
        end = files_changed_match.end() + (next_heading.start() if next_heading else len(tail))
        prose = body[:start] + body[end:]
    # Strip URLs so e.g. `https://example.com/path/to/x.html` doesn't
    # show up as a "claimed file".
    prose = _URL_RE.sub("", prose)

    # Strip fenced code blocks — paths in code snippets are usually
    # examples / imports / type names, not claims about what the PR
    # touched.
    prose = re.sub(r"```.*?```", "", prose, flags=re.DOTALL)
    # Inline backticks: keep the content (often the path itself), just
    # remove the backtick characters.
    prose = prose.replace("`", "")

    mentioned: list[str] = list({m.group(1) for m in _PATH_IN_PROSE_RE.finditer(prose)})

    if not mentioned:
        return Pass(reason="no file paths mentioned in prose")

    touched_set = set(files_touched)
    touched_basenames = {f.rsplit("/", 1)[-1] for f in files_touched}

    unmatched = [
        m for m in mentioned
        if m not in touched_set
        and m.rsplit("/", 1)[-1] not in touched_basenames
    ]

    if unmatched:
        # Keep the failure surfacing concrete: list up to 3 of the worst
        # offenders so the operator can spot-check.
        return Fail(
            f"PR body mentions {len(unmatched)} file(s) the diff didn't touch: "
            f"{', '.join(unmatched[:3])}"
            + (f" (+{len(unmatched)-3} more)" if len(unmatched) > 3 else "")
            + ". The body and the diff disagree about what changed.",
            evidence_data={
                "mentioned_in_prose": mentioned,
                "files_touched": files_touched,
                "unmatched": unmatched,
            },
        )

    return Pass(evidence_data={"mentioned_count": len(mentioned)})


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

    # Filter scratch files stripped from the operator PR tree (notes.md)
    # so the judge's "Fix summary" file count matches the PR body's
    # "Files changed" count. _render_default applies the same filter; the
    # judge previously read the raw list, so it saw "3 files" against the
    # body's "2 files" and (correctly) flagged the mismatch.
    files_touched = []
    if evidence.exists("05-fixed/files_touched.txt"):
        files_touched = [
            l.strip() for l in evidence.read_text("05-fixed/files_touched.txt").splitlines()
            if l.strip() and l.strip() not in _TREE_STRIP_PATHS
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
