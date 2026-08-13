"""Seed test suite.

These cover the happy paths and pass as-is, so the repo is green when seeded.
The three seeded bugs live in edge cases these tests deliberately do NOT
exercise (final partial page, day > 12, empty column) — a coding agent's job
is to reproduce the bug, fix it, and ADD the missing test.
"""

from demotool import dates, paginate, stats
from demotool.parser import column, load_rows


def test_get_page_slices_correctly():
    items = list(range(1, 21))  # 20 items
    assert paginate.get_page(items, 1, 10) == list(range(1, 11))
    assert paginate.get_page(items, 2, 10) == list(range(11, 21))


def test_page_count_exact_multiple():
    # 20 / 10 == 2; floor and ceil agree here, so the bug stays hidden.
    assert paginate.page_count(list(range(20)), 10) == 2


def test_to_display_single_digit_day():
    # Day <= 12, so the MM/DD vs DD/MM swap is not visible here.
    assert dates.to_display("2026-03-05").endswith("/2026")


def test_average_nonempty():
    assert stats.average([2.0, 4.0, 6.0]) == 4.0


def test_total():
    assert stats.total([1.5, 2.5]) == 4.0


def test_load_and_column(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("date,amount\n2026-01-02,10\n2026-01-03,20\n")
    rows = load_rows(p)
    assert len(rows) == 2
    assert column(rows, "amount") == ["10", "20"]
