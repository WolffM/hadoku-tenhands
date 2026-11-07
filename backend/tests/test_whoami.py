"""Tests for the tier ladder in ``middleware/whoami.py``: ``_VALID_TIERS``,
``tier_rank``, and the ``assert_floor`` boot guard.

Companion to ``test_auth_gate.py``, which exercises the gate end to end;
these tests pin the ladder itself so a future edit that drops or misorders a
tier is caught here rather than discovered as a live gate bug.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from middleware.whoami import _VALID_TIERS, assert_floor, tier_rank

_BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_valid_tiers_is_the_complete_ladder():
    # LOW to HIGH would be the opposite of how this tuple is declared — it's
    # declared HIGH to LOW, and tier_rank's arithmetic depends on that order.
    assert _VALID_TIERS == ("admin", "wife", "service", "friend", "member", "public")


@pytest.mark.parametrize("tier,expected_rank", [
    ("admin", 5),
    ("wife", 4),
    ("service", 3),
    ("friend", 2),
    ("member", 1),
    ("public", 0),
])
def test_tier_rank_of_every_known_tier(tier, expected_rank):
    assert tier_rank(tier) == expected_rank


@pytest.mark.parametrize("bad", ["", "bogus", "Member", "members", "superuser"])
def test_tier_rank_of_an_unknown_name_is_public(bad):
    assert tier_rank(bad) == tier_rank("public") == 0


# ---- assert_floor: the boot guard for a hardcoded floor constant ----


@pytest.mark.parametrize("tier", ["admin", "wife", "service", "friend", "member"])
def test_assert_floor_accepts_every_tier_above_public(tier):
    assert assert_floor(tier) == tier


@pytest.mark.parametrize("bad", ["public", "", "Member", "members", "superuser"])
def test_assert_floor_refuses_public_and_unknown_names(bad):
    with pytest.raises(ValueError, match="not a tier floor"):
        assert_floor(bad)


def test_assert_floor_error_names_the_bad_value():
    with pytest.raises(ValueError, match=r"'bogus-floor'"):
        assert_floor("bogus-floor")


# ---- A real boot-refusal, in a child process ----
#
# app.py calls `assert_floor` at MODULE level for both `_READ_MIN_TIER` and
# `_WRITE_MIN_TIER` — the same shape used here — so a bad floor value raises
# at import time, not on first request. This proves that shape actually
# refuses to finish importing, via a real `import`, in a fresh interpreter
# (not just a direct function call in-process).


def _run_module_level_assert(tier: str) -> subprocess.CompletedProcess:
    script = (
        "import sys; sys.path.insert(0, %r); "
        "from middleware.whoami import assert_floor; "
        "FLOOR = assert_floor(%r); "
        "print('booted with floor', FLOOR)"
    ) % (str(_BACKEND_DIR), tier)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_boot_refuses_an_unknown_floor():
    result = _run_module_level_assert("bogus-floor")
    assert result.returncode != 0
    assert "ValueError" in result.stderr
    assert "bogus-floor" in result.stderr


def test_boot_refuses_public_as_a_floor():
    result = _run_module_level_assert("public")
    assert result.returncode != 0
    assert "ValueError" in result.stderr


def test_boot_succeeds_with_a_real_floor():
    result = _run_module_level_assert("friend")
    assert result.returncode == 0, result.stderr
    assert "booted with floor friend" in result.stdout


def test_app_module_level_floors_are_set_correctly():
    """Sanity: the actual constants app.py computes at import time."""
    import app as _app

    assert _app._READ_MIN_TIER == "friend"
    assert _app._WRITE_MIN_TIER == "service"
