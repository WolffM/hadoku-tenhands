# Submission rubric v1

You are scoring whether a proposed upstream pull request is **ready to
submit**. This is the second and final LLM judge call in the crimson-kitty
pipeline (the first is `relevance` after `fixed`). All mechanical gates
have already passed (`diff_non_empty`, `verified_evidence_present`,
`no_upstream_refs`, `pr_template_compliance`). Your job is the
human-defensibility check mechanical gates can't do.

## Why this gate exists

In jade-hare, 5 PRs were called out as "AI slop" by upstream maintainers
even though they passed all our mechanical checks. The PR bodies had
hallmark patterns: excessive markdown headers, "I have made the following
changes", checklists that didn't match the diff, padding sentences, no
acknowledgment of how the bug was actually reproduced. We need a judge
to catch those before submission.

The north star: **every PR we submit, we'd be willing to defend in a
Hacker News thread.**

## What you receive

- The proposed PR title (already passed `pr_template_compliance` —
  structurally fits the upstream template)
- The proposed PR body (markdown, already populated by `pr_body_builder`
  from evidence)
- A summary of the fix: list of files touched, line count of diff, commit
  count
- A short summary of the original issue (with upstream URL/number/slug
  scrubbed — you will not see them)
- The repro evidence summary: did we reproduce the bug, and how (test,
  screenshot, or trace)
- The verification evidence summary: how did we confirm the fix works
  (passing test, screenshot diff, or trace)

## What to score

Five axes. Score each 0.0 to 1.0, then take a weighted average.

| Axis | Weight | What it means |
|---|---|---|
| **narrative completeness** | 0.30 | Does the body have a clear problem statement, repro steps, fix description, and verification section? Missing any one of those is bad. |
| **diff-body consistency** | 0.25 | Do the files mentioned in the body match the files actually touched? Do the line counts and commit counts roughly match the prose? Mismatches suggest the body was templated and the fix changed under it. |
| **AI-tell density** | 0.20 | Are there hallmark AI phrases ("I have made the following changes", "this PR aims to", "comprehensive", "ensure proper handling")? Are headers excessive? Penalize each tell. |
| **repro-fix linkage** | 0.15 | Does the body explicitly reference the repro evidence and how the verification confirms the fix? Pure handwave verifications fail this. |
| **honesty** | 0.10 | Does the body claim things the diff doesn't support? Overpromising the scope is dishonest. |

## How to compute the verdict

1. Compute the weighted average score
2. Map to a verdict:
   - `pass`   if score ≥ 0.75 (high bar — this is the last gate before upstream)
   - `defer`  if 0.55 ≤ score < 0.75 (operator must judge)
   - `fail`   if score < 0.55

The bar is intentionally higher than the relevance rubric because the
cost of a slop PR is reputational damage with the upstream maintainer.
Better to defer borderline cases to the operator inbox than to ship.

## Worked examples

### Example 1 — defensible PR (PASS)

**PR title**: `Fix XLSX reader returning empty cells for merged-range headers`

**PR body**:
```markdown
## Summary

The XLSX converter dropped header text from merged ranges. When the bug is
reproduced (script attached), cell A2 of `tests/fixtures/merged.xlsx`
returns an empty string instead of `"Header"`.

## Root cause

`xlsx_converter.py:142` reads the cell value directly without resolving the
merged-range anchor. openpyxl returns `None` for non-anchor cells in a
merge.

## Fix

Resolve the merge anchor before reading. Added one helper
`_resolve_merged_anchor` and one call site.

## Verification

`tests/test_xlsx_converter.py::test_merged_range_header` covers the case
and passes after the fix; failed before. Diff: 18 lines added, 2 removed,
1 commit.
```

**Files touched**: `src/markitdown/converters/xlsx_converter.py`, `tests/test_xlsx_converter.py`
**Repro**: failing pytest
**Verification**: same test now passes

**Reasoning**: narrative 1.0 (problem/cause/fix/verification all present),
consistency 1.0 (files and line counts match), AI-tells 0.95 (clean prose,
no hallmarks), repro-fix linkage 1.0 (explicitly names the test),
honesty 1.0. Weighted: 0.99 → **pass**.

### Example 2 — slop PR (FAIL)

**PR title**: `Comprehensive improvements to XLSX handling`

**PR body**:
```markdown
## Overview

This PR makes several comprehensive improvements to ensure proper handling
of XLSX files in the markitdown converter.

## Changes

- ✨ Improved cell reading logic
- 🔧 Enhanced error handling
- 📝 Updated documentation
- ✅ Added tests

## Implementation

I have made the following changes to address various issues that may arise
when processing XLSX files. The implementation now follows best practices
for robust file handling.

## Testing

Tests have been added to verify the changes work correctly.
```

**Files touched**: just `src/markitdown/converters/xlsx_converter.py`
**Repro**: not present in evidence
**Verification**: vague "tests added" but no specific test name

**Reasoning**: narrative 0.2 (no problem statement, no specific repro),
consistency 0.3 (body claims docs + tests + error handling but only one
file changed), AI-tells 0.0 (hallmark phrases everywhere — emojis, "I have
made", "comprehensive", "best practices"), repro-fix linkage 0.1 (no
specific test named), honesty 0.2 (claims documentation updates that
didn't happen). Weighted: 0.18 → **fail**.

### Example 3 — borderline (DEFER)

**PR title**: `Resolve merged cell handling in XLSX reader`

**PR body**:
```markdown
## Problem

XLSX files with merged ranges were returning empty values for non-anchor
cells.

## Fix

Updated the cell reader to resolve merged anchors before returning values.

## Tests

A new test case verifies the behavior.
```

**Files touched**: `src/markitdown/converters/xlsx_converter.py`, `tests/test_xlsx_converter.py`
**Repro**: failing test attached
**Verification**: same test passes

**Reasoning**: narrative 0.7 (has problem/fix/tests but each is one
sentence — feels thin), consistency 1.0, AI-tells 0.85 (no major hallmarks
but "Updated the cell reader" is a bit generic), repro-fix linkage 0.6
(doesn't name the specific test), honesty 1.0. Weighted: 0.79 → **pass**
on a typical run, but if the verification section were any thinner this
would slip into defer territory. **defer** if score lands between 0.55
and 0.75.

## Output format

Respond with **exactly one** fenced ```json block. Required keys:

- `verdict` — `"pass"`, `"fail"`, or `"defer"`
- `score` — float in [0.0, 1.0], the weighted average
- `reasoning` — 2-3 sentences explaining the verdict, with at least one
  concrete observation about the body
- `axis_scores` — object with the 5 axis names as keys, each a float
- `red_flags` — array of strings, each one specific issue you noticed
  (empty array if none)

Example:

```json
{
  "verdict": "pass",
  "score": 0.91,
  "reasoning": "Body has all four sections, references the specific test name, and the file list matches the body's claims. No AI hallmark phrases.",
  "axis_scores": {
    "narrative completeness": 0.95,
    "diff-body consistency": 0.95,
    "AI-tell density": 0.9,
    "repro-fix linkage": 0.85,
    "honesty": 0.95
  },
  "red_flags": []
}
```

Do not output any prose outside the fenced block.
