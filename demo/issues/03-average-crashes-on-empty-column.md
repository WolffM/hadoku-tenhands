---
title: "average() raises ZeroDivisionError on an empty column"
labels: [bug, demo]
---
## Steps to reproduce

1. In a Python shell:
   ```python
   from demotool import stats
   stats.average([])
   ```
   or run a report whose amount column is present but entirely blank.

## Expected

Summarising an empty column should return `0.0` (or `None`) — an empty
selection is a normal case, not an error.

## Observed

`ZeroDivisionError: division by zero` is raised from
`demotool/stats.py:average`, because it divides by `len(values)` with no guard
for the empty list.
