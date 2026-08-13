"""CSV loading into simple row dicts."""

from __future__ import annotations

import csv
from pathlib import Path


def load_rows(path: str | Path) -> list[dict[str, str]]:
    """Read a CSV file into a list of dict rows keyed by header.

    Empty files (or header-only files) yield an empty list.
    """
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def column(rows: list[dict[str, str]], name: str) -> list[str]:
    """Return the values of one column across all rows, in order."""
    return [r[name] for r in rows if name in r]
