"""Command-line entry point: `python -m demotool report ...`."""

from __future__ import annotations

import argparse
import sys

from . import dates, paginate, stats
from .parser import column, load_rows


def _cmd_report(args: argparse.Namespace) -> int:
    rows = load_rows(args.csv)
    pages = paginate.page_count(rows, args.page_size)
    page_rows = paginate.get_page(rows, args.page, args.page_size)

    print(f"Report: {args.csv}  (page {args.page} of {pages})")
    for r in page_rows:
        when = dates.to_display(r[args.date_column]) if args.date_column in r else ""
        print(f"  {when}  " + "  ".join(f"{k}={v}" for k, v in r.items()))

    if args.amount_column:
        amounts = stats.to_floats(column(rows, args.amount_column))
        print(f"total {args.amount_column}: {stats.total(amounts):.2f}")
        print(f"average {args.amount_column}: {stats.average(amounts):.2f}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="demotool")
    sub = p.add_subparsers(dest="command", required=True)

    rep = sub.add_parser("report", help="print a paginated report of a CSV")
    rep.add_argument("csv")
    rep.add_argument("--page", type=int, default=1)
    rep.add_argument("--page-size", type=int, default=10)
    rep.add_argument("--date-column", default="date")
    rep.add_argument("--amount-column", default="")
    rep.set_defaults(func=_cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
