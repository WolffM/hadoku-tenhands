---
title: "Last partial page of a report is never shown"
labels: [bug, demo]
---
## Steps to reproduce

1. `samples/sales.csv` has 25 rows.
2. Run: `python -m demotool report samples/sales.csv --page-size 10`
3. The header prints `page 1 of 2`.
4. Try to view the last rows: `python -m demotool report samples/sales.csv --page 3 --page-size 10`

## Expected

25 rows at 10 per page is 3 pages; page 3 should show rows 21–25, and the
report header should read `page ... of 3`.

## Observed

The header says `of 2`, and any loop over `range(1, page_count() + 1)` stops at
page 2, so rows 21–25 are never rendered. The last partial page is silently
dropped.

Looks like `page_count` in `demotool/paginate.py` uses floor division and
doesn't round up for a partial final page.
