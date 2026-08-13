"""Date parsing/formatting for report output.

BUG (seeded, issue 02): input dates are ISO (YYYY-MM-DD) but the display
formatter emits month/day in the wrong order for its stated format. It claims
to produce DD/MM/YYYY yet writes MM/DD/YYYY, so any day <= 12 looks plausible
and only days > 12 (or a caller checking the month) reveal the swap.
"""

from __future__ import annotations

from datetime import date, datetime


def parse_iso(value: str) -> date:
    """Parse an ISO-8601 date string (YYYY-MM-DD)."""
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def to_display(value: str) -> str:
    """Format an ISO date string as DD/MM/YYYY for the report."""
    d = parse_iso(value)
    # BUG: the docstring and report header promise DD/MM/YYYY, but this emits
    # MM/DD/YYYY. Should be f"{d.day:02d}/{d.month:02d}/{d.year}".
    return f"{d.month:02d}/{d.day:02d}/{d.year}"
