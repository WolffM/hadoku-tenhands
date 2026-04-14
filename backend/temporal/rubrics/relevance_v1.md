# Relevance rubric v1

You are scoring whether a code diff is **relevant** to the issue it claims
to fix. This is one of only two LLM judge calls in the entire crimson-kitty
pipeline — be conservative. Mechanical gates (`diff_non_empty`,
`files_touched`) have already passed. Your job is the semantic check
mechanical gates can't do.

## Why this gate exists

In the jade-hare batch, the `microsoft/markitdown` PR mixed an unrelated
import-cleanup with the actual fix. The diff was non-empty and the files
matched, but most of the changes had nothing to do with the bug. Mechanical
checks couldn't catch it. This rubric does.

## What you receive

- A short summary of the issue (title + first 500 chars of body, with the
  upstream URL/number/slug **already scrubbed** — do not look for them, and
  do not invent any)
- The list of files the diff touches
- The full diff (truncated at 8000 chars; if longer, you'll see a
  `[diff truncated]` marker)

## What to score

Five axes. Score each 0.0 to 1.0, then take a weighted average.

| Axis | Weight | What it means |
|---|---|---|
| **on-topic** | 0.35 | Do the touched files plausibly relate to the bug described? E.g. an XLSX cell-coalescing bug should touch xlsx/cell code, not docs. |
| **scope** | 0.25 | Is the change scoped to the bug, or does it sprawl into unrelated cleanup? Reformatting the file is OK; renaming unrelated functions is not. |
| **focus** | 0.20 | Of the lines added/removed, what fraction look like they're addressing the reported behavior vs incidental? Aim for >70% focused. |
| **no-noise** | 0.10 | Are there import re-orderings, whitespace-only changes, unrelated lint fixes? Penalize each. |
| **completeness** | 0.10 | Does the diff actually plausibly fix the bug, or does it just touch the area? A no-op edit in the right file scores low here. |

## How to compute the verdict

1. Compute the weighted average score
2. Map to a verdict:
   - `pass`   if score ≥ 0.70
   - `defer`  if 0.45 ≤ score < 0.70 (operator must judge — borderline)
   - `fail`   if score < 0.45

## Worked examples

### Example 1 — clean fix (PASS)

**Issue summary**: "XLSX reader returns empty cells when the cell has a
merged-range header. Steps: open `merged.xlsx`, expect cell A2 to contain
'Header', got empty string."

**Files touched**:
```
src/markitdown/converters/xlsx_converter.py
tests/test_xlsx_converter.py
```

**Diff (excerpt)**:
```diff
+    if cell.value is None and self._is_merged_range_anchor(cell):
+        cell = self._resolve_merged_anchor(cell)
```

**Reasoning**: on-topic 1.0 (xlsx_converter is exactly the right file),
scope 1.0 (only xlsx code), focus 0.95 (every line addresses the bug),
no-noise 1.0, completeness 0.9. Weighted: 0.97 → **pass**.

### Example 2 — sprawl (FAIL)

**Issue summary**: "DOCX converter strips bullet points from nested lists."

**Files touched**:
```
src/markitdown/converters/docx_converter.py
src/markitdown/converters/pdf_converter.py
src/markitdown/utils/__init__.py
src/markitdown/cli.py
docs/CHANGELOG.md
```

**Diff (excerpt)**:
```diff
- from markitdown.utils import sanitize, format_path
+ from markitdown.utils import format_path, sanitize
... [200 lines of import reordering]
+    # actually fix nested list bullets
+    if li.parent.name == "ul":
+        ...
```

**Reasoning**: on-topic 0.4 (docx is right but pdf/cli/changelog are
unrelated), scope 0.3 (4 of 5 files unrelated), focus 0.2 (>80% is import
reordering), no-noise 0.0 (massive lint sprawl), completeness 0.6. Weighted:
0.32 → **fail**.

### Example 3 — borderline (DEFER)

**Issue summary**: "Image converter OCRs a blank box at the bottom of every
JPEG."

**Files touched**:
```
src/markitdown/converters/image_converter.py
tests/test_image_converter.py
src/markitdown/utils/image_utils.py
```

**Diff (excerpt)**:
```diff
+    # crop EXIF orientation padding
+    img = self._strip_exif_padding(img)
+    return self._ocr(img)
```

**Reasoning**: on-topic 0.85, scope 0.85, focus 0.7, no-noise 1.0,
completeness 0.55 (the fix is plausible but the bug-to-fix link isn't
proven by the diff alone). Weighted: 0.78 → would normally pass, but
completeness < 0.6 makes it borderline. **defer**.

## Output format

Respond with **exactly one** fenced ```json block. Required keys:

- `verdict` — `"pass"`, `"fail"`, or `"defer"`
- `score` — float in [0.0, 1.0], the weighted average
- `reasoning` — 2-3 sentences explaining the verdict
- `axis_scores` — object with the 5 axis names as keys, each a float

Example:

```json
{
  "verdict": "pass",
  "score": 0.92,
  "reasoning": "Diff touches only xlsx_converter.py and its test. All hunks address the merged-range anchor bug. No incidental cleanup.",
  "axis_scores": {
    "on-topic": 1.0,
    "scope": 0.95,
    "focus": 0.9,
    "no-noise": 1.0,
    "completeness": 0.85
  }
}
```

Do not output any prose outside the fenced block.
