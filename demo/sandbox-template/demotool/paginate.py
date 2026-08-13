"""Row pagination.

BUG (seeded, issue 01): `page_count` uses floor division, so when the total
number of rows is not an exact multiple of the page size the final partial
page is not counted. Callers that iterate `range(1, page_count() + 1)` then
never render that last page, silently dropping its rows. `get_page` itself is
correct — which is what makes this quiet: slicing works, the page total is
just one short.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def page_count(items: list[T], page_size: int) -> int:
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    # BUG: floor division drops the final partial page. Should round up, e.g.
    # `-(-len(items) // page_size)` or `math.ceil(len/page_size)`.
    return len(items) // page_size


def get_page(items: list[T], page: int, page_size: int) -> list[T]:
    """Return the 1-indexed `page` of `items` at `page_size` per page."""
    if page < 1:
        raise ValueError("page is 1-indexed and must be >= 1")
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    start = (page - 1) * page_size
    return items[start:start + page_size]
