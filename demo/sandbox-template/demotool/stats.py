"""Numeric column summaries.

BUG (seeded, issue 03): `average` divides by len without guarding the empty
case, so summarising an empty column (or a filtered-to-empty selection)
raises ZeroDivisionError instead of returning a sensible 0.0 / None.
"""

from __future__ import annotations


def to_floats(values: list[str]) -> list[float]:
    """Coerce string cells to floats, skipping blanks."""
    out: list[float] = []
    for v in values:
        v = v.strip()
        if v:
            out.append(float(v))
    return out


def total(values: list[float]) -> float:
    return sum(values)


def average(values: list[float]) -> float:
    """Mean of the values.

    BUG: no empty guard. An empty list raises ZeroDivisionError; it should
    return 0.0 (or None) for an empty column.
    """
    return sum(values) / len(values)
