"""repro gates — run after `reproduced` state.

Two gates fire here:

- repro_evidence_present (mechanical): structural check that the agent
  produced at least one evidence artifact AND a notes.md explaining
  the repro. Does NOT prescribe what form evidence takes — a test,
  screenshot, trace, lint output, or any other file the agent deems
  appropriate.

- repro_actually_reproduced (mechanical): scans notes.md for explicit
  "could not reproduce" / "bug not present" language. If the agent
  declared the issue couldn't be reproduced on current main, defer
  to the operator instead of proceeding to fix. shadcn-ui#7333 and
  tailscale#5160 (2026-05-27 batch) burned full agent sessions
  producing tests-only diffs that downstream relevance caught anyway;
  catching here saves the entire fix → submit path.

Heading detection is lenient: Copilot-authored notes use many
styles — `## Steps to reproduce`, `## Steps to Reproduce`, plain
`Steps to Reproduce`, or `**Steps to Reproduce**`. We just require
each of the three labels to appear as a line of its own (optionally
prefixed by markdown punctuation), case-insensitively.

See docs/crimson-kitty/gates.md.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from . import CRIMSON_KITTY, Defer, Fail, GateResult, IssueRef, Pass, gate

REQUIRED_LABELS = ("Steps to reproduce", "Observed", "Expected")
MIN_NOTES_WORDS = 50

# Files that are always written by the orchestrator, not the agent.
# These don't count as "evidence the agent produced something."
_BOILERPLATE = {"agent_result.json", "notes.md"}


def _find_missing_sections(notes: str) -> list[str]:
    """Return labels from REQUIRED_LABELS that aren't present as a heading.

    A label is "present" when it appears as an entire trimmed line,
    optionally wrapped in `#`, `##`, `**`, or `__`, case-insensitively.
    """
    present: set[str] = set()
    for raw_line in notes.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        # Strip any leading `#` run + space, and any bold wrappers.
        cleaned = re.sub(r"^#+\s*", "", stripped)
        cleaned = cleaned.strip("* _")
        cleaned_lower = cleaned.lower()
        for label in REQUIRED_LABELS:
            if cleaned_lower == label.lower():
                present.add(label)
    return [label for label in REQUIRED_LABELS if label not in present]


@gate(pipeline=CRIMSON_KITTY, after="reproduced", kind="mechanical")
def repro_evidence_present(issue: IssueRef, evidence) -> GateResult:
    repro_dir = evidence.path("04-reproduced")
    if not repro_dir.exists():
        return Fail("04-reproduced/ directory missing")

    # Any non-boilerplate file counts as evidence.
    artifacts = [
        f.name for f in repro_dir.iterdir()
        if f.is_file() and f.name not in _BOILERPLATE
    ]

    if not artifacts:
        return Fail("no evidence artifacts produced")

    notes_path = repro_dir / "notes.md"
    if not notes_path.exists():
        return Fail("notes.md missing - agent must explain the repro")

    notes = notes_path.read_text(encoding="utf-8")
    word_count = len(notes.split())
    if word_count < MIN_NOTES_WORDS:
        return Fail(
            f"notes.md too short: {word_count} words (need >={MIN_NOTES_WORDS})",
            evidence_data={"word_count": word_count},
        )

    missing = _find_missing_sections(notes)
    if missing:
        return Fail(
            f"notes.md missing sections: {missing}",
            evidence_data={"missing_sections": missing},
        )

    return Pass(
        evidence_data={
            "artifacts": artifacts,
            "word_count": word_count,
        },
    )


# Patterns the agent uses when they can't repro on current main. These
# strings (or close variants) appeared in shadcn-ui#7333 and tailscale#5160
# notes.md content (2026-05-27 batch) — the agent ran the repro steps and
# the bug didn't manifest, so they wrote tests + notes but no fix. Catching
# at the repro stage prevents the entire fix→submit waste.
_NO_REPRO_PATTERNS = re.compile(
    r"\b("
    r"could not reproduce"
    r"|couldn't reproduce"
    r"|cannot reproduce"
    r"|can't reproduce"
    r"|unable to reproduce"
    r"|did not reproduce"
    r"|does not reproduce"
    r"|doesn't reproduce"
    r"|no longer reproduces?"
    r"|no longer reproducible"
    r"|not reproducible"
    r"|bug (is )?not present"
    r"|issue (is )?not present"
    r"|issue (may )?already (be )?fixed"
    r"|bug (may )?already (be )?fixed"
    r"|already resolved (in|on) (main|master|trunk|head)"
    r")\b",
    re.IGNORECASE,
)


@gate(pipeline=CRIMSON_KITTY, after="reproduced", kind="mechanical")
def repro_actually_reproduced(issue: IssueRef, evidence) -> GateResult:
    """Defer when notes.md explicitly says the bug didn't reproduce.

    Looks at the Observed/Expected sections (or the whole notes if those
    aren't found) for explicit "could not reproduce" language. If any
    NO_REPRO pattern fires, defer to operator inbox with a "may already
    be fixed in main" message — the operator should triage (close the
    issue, retry on a different version, or accept the agent's
    tests-only diff if appropriate).

    Conservative on purpose: matches phrases, not raw words. "Reproduce
    the bug by…" in the Steps section won't false-trigger.
    """
    notes_path = evidence.path("04-reproduced") / "notes.md"
    if not notes_path.exists():
        # repro_evidence_present already fails this case mechanically.
        return Pass(reason="no notes.md (caught by repro_evidence_present)")

    notes = notes_path.read_text(encoding="utf-8")
    if not notes.strip():
        return Pass(reason="empty notes")

    matches = _NO_REPRO_PATTERNS.findall(notes)
    if not matches:
        return Pass()

    # Pull the first matching SENTENCE for the defer reason so the
    # operator inbox shows them what the agent actually said.
    snippet = ""
    for m in _NO_REPRO_PATTERNS.finditer(notes):
        # Walk backward to a sentence boundary, forward to one.
        start = max(0, m.start() - 120)
        end = min(len(notes), m.end() + 120)
        snippet = notes[start:end].replace("\n", " ").strip()
        # Trim to a single sentence-ish span.
        snippet = re.sub(r"\s+", " ", snippet)[:240]
        break

    return Defer(
        f"agent could not reproduce the bug on current main — "
        f"may already be fixed upstream, or repro requires conditions "
        f"the agent's environment doesn't have. Operator should triage. "
        f"Excerpt: \"…{snippet}…\"",
        evidence_data={"patterns_matched": len(re.findall(_NO_REPRO_PATTERNS, notes))},
    )


# ── repro_scope_match (judge — advisory) ─────────────────────────────────


def _mode() -> str:
    """advisory | enforce. Default advisory — gate runs and persists the
    verdict but always returns Pass, so the operator gets telemetry
    before we flip to a real defer. Mirrors actionability rollout."""
    return os.environ.get("CRIMSON_REPRO_SCOPE_MODE", "advisory").lower()


def _default_judge_score(rubric_md: str, input_payload: str) -> Any:
    from ..judge import score
    return score(rubric_md, input_payload)


def _default_load_scope_rubric() -> str:
    rubric_path = (
        Path(__file__).resolve().parent.parent / "rubrics" / "repro_scope_v1.md"
    )
    return rubric_path.read_text(encoding="utf-8")


def _build_scope_payload(issue_body: str, issue_title: str, notes: str, files: list[str]) -> str:
    parts = [
        "## Issue title",
        "",
        issue_title or "_(missing)_",
        "",
        "## Issue body",
        "",
        (issue_body or "_(missing)_")[:6000],
        "",
        "## Agent's notes.md",
        "",
        notes[:6000] or "_(missing)_",
        "",
        "## Files touched during repro",
        "",
    ]
    if files:
        parts.extend(f"- `{f}`" for f in files[:30])
        if len(files) > 30:
            parts.append(f"- …and {len(files) - 30} more")
    else:
        parts.append("_(none recorded)_")
    return "\n".join(parts)


@gate(pipeline=CRIMSON_KITTY, after="reproduced", kind="judge")
def repro_scope_match(
    issue: IssueRef,
    evidence,
    *,
    judge_score=None,
    load_rubric=None,
) -> GateResult:
    """Judge: does the agent's reproduction match the issue's reported scope?

    Catches the argo-cd#27872-style failure: agent reproduced WITH
    submodules, maintainer's case is WITHOUT. The agent narrows scope
    silently, fixes the narrow case, and the maintainer's actual
    scenario remains broken.

    Default advisory: verdict is logged but always returns Pass so the
    pipeline doesn't gain new defer-by-judge behavior until the rubric
    is calibrated against real cases. Flip to enforce via
    `CRIMSON_REPRO_SCOPE_MODE=enforce`.

    Defensive on any failure: judge unreachable / parse error / missing
    inputs all return Pass (with reason). We never want this gate to
    block a workflow on infra issues.
    """
    judge_score = judge_score or _default_judge_score
    load_rubric = load_rubric or _default_load_scope_rubric

    # Pull inputs from evidence. If anything's missing, pass with reason.
    if not evidence.exists("01-eligible/issue_brief.json"):
        return Pass(reason="scope: issue_brief.json missing")
    brief = evidence.read_json("01-eligible/issue_brief.json")
    issue_obj = brief.get("issue") if isinstance(brief, dict) else None
    if not isinstance(issue_obj, dict):
        return Pass(reason="scope: issue_brief malformed")

    issue_body = (issue_obj.get("body") or "").strip()
    issue_title = (issue_obj.get("title") or "").strip()

    notes_path = evidence.path("04-reproduced") / "notes.md"
    notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""

    repro_dir = evidence.path("04-reproduced")
    files = sorted(
        f.name for f in repro_dir.iterdir() if f.is_file() and f.name not in _BOILERPLATE
    )

    if not issue_body and not notes:
        return Pass(reason="scope: nothing to compare")

    rubric = load_rubric()
    payload = _build_scope_payload(issue_body, issue_title, notes, files)

    try:
        result = judge_score(rubric, payload)
    except Exception as e:
        return Pass(reason=f"scope: judge unreachable ({type(e).__name__})")

    verdict = getattr(result, "verdict", "pass")
    score_val = getattr(result, "score", 0.85)
    reasoning = getattr(result, "reasoning", "")
    raw = getattr(result, "raw", None)
    rubric_evidence = (
        raw.get("evidence") if isinstance(raw, dict) and isinstance(raw.get("evidence"), list) else []
    )

    advisory_data = {
        "mode": _mode(),
        "rubric_verdict": verdict,
        "rubric_score": score_val,
        "rubric_reasoning": reasoning,
        "rubric_evidence": rubric_evidence,
        "files_touched_count": len(files),
    }

    if _mode() != "enforce":
        return Pass(
            reason=f"advisory: rubric said {verdict} ({score_val})",
            evidence_data=advisory_data,
        )

    if verdict == "defer":
        return Defer(
            f"scope mismatch: {reasoning}",
            evidence_data=advisory_data,
        )
    return Pass(evidence_data=advisory_data)
