"""The two guards that make the v3 cutover order-independent.

Both exist because of the same 47-hour outage, from opposite ends:

  - a fleet with no v3 board yet must be a clean no-op, not a red run;
  - a repo-laned board must not be driven against a pre-v3 worker, because
    that fails SILENTLY rather than loudly.

The first is what went wrong. The second is what would have gone wrong next,
if a board had been migrated while hadoku-task was still on v2.
"""

from __future__ import annotations

import pytest
import requests

from services import task_board
from services.task_board import far_side_has_v3


class FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code, self.text = status_code, text


def _patch_get(monkeypatch, result):
    def fake_get(url, **kw):
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(task_board.requests, "get", fake_get)


def test_a_spec_enumerating_the_sentinel_is_v3(monkeypatch):
    _patch_get(monkeypatch, FakeResp(200, '{"enum":["LEASE_LOST","NOTES_CHANGED"]}'))
    assert far_side_has_v3() is True


def test_a_spec_without_it_is_not(monkeypatch):
    """The real pre-deploy shape: their v2 spec, which we probed on 2026-09-18
    and which advertised none of the v3 codes."""
    _patch_get(monkeypatch, FakeResp(200, '{"enum":["LEASE_LOST","LANE_CHANGED"]}'))
    assert far_side_has_v3() is False


@pytest.mark.parametrize("result", [
    FakeResp(500, "boom"),
    FakeResp(404, "gone"),
    requests.ConnectionError("no route"),
    requests.Timeout("slow"),
])
def test_an_unreadable_spec_is_not_evidence_of_anything(monkeypatch, result):
    """`None`, never `False`. A probe that failed must not be read as a
    rollback — that would take the pipeline down for a network blip, which is
    a worse outage than the one this guard prevents."""
    _patch_get(monkeypatch, result)
    assert far_side_has_v3() is None


def test_the_sentinel_is_an_error_code_not_a_field_name():
    """Deliberate: hadoku-task's `openapi-verify` fails their build both ways —
    a code they emit that isn't enumerated, and an enumerated value nothing
    emits — so this string cannot appear in their spec unless the path that
    raises it shipped too. A field name carries no such guarantee.

    It is also NOT `laneKind`, which we invented for our own preset and which
    was never in their spec; probing for that found nothing and told us
    nothing, which is how this sentinel got chosen."""
    assert task_board._V3_SENTINEL == "NOTES_CHANGED"
    assert task_board._V3_SENTINEL in task_board.KNOWN_CODES
