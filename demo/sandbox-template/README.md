# demotool

A tiny CSV report utility: parse a CSV, format dates, paginate rows, and
summarise a numeric column.

```bash
pip install -e .[dev]
python -m demotool report samples/sales.csv --page-size 10 --amount-column amount
pytest -q
```

## What it does

- `demotool report <csv>` prints a paginated view of the rows and, with
  `--amount-column`, the total and average of that column.
- Dates are read as ISO (`YYYY-MM-DD`) and shown as `DD/MM/YYYY`.

## Status

This is a small, real project maintained as a demonstration target for an
automated contribution pipeline. Issues labelled `demo` are genuine small bugs
with reproduction steps; contributions (including from coding agents) are
welcome. See `CONTRIBUTING.md`.
