---
title: "Report dates render as MM/DD/YYYY instead of DD/MM/YYYY"
labels: [bug, demo]
---
## Steps to reproduce

1. Run: `python -m demotool report samples/sales.csv --page-size 5`
2. Look at the `date` shown for the row dated `2026-01-14` in the CSV.

## Expected

The README and the report state dates are shown as `DD/MM/YYYY`, so
`2026-01-14` should render as `14/01/2026`.

## Observed

It renders as `01/14/2026` — month and day are swapped. For days ≤ 12 this is
invisible, which is why it slipped through, but any day > 12 shows it clearly.

The formatter in `demotool/dates.py` (`to_display`) emits month first despite
promising day first.
