"""Tests for services/task_board.py — the hadoku-task board client.

The point of this client is that failures are *distinguishable*: CLAIM_HELD
means move on, LEASE_LOST means abort without writing, and a timeout means
we never got a verdict at all. Most of what's below pins that mapping,
because collapsing any two of them makes the runner do the wrong thing
silently.

Transport is injected, so these exercise real request construction and real
response interpretation with no network and no live board.
"""

from __future__ import annotations

import json

import pytest
import requests

from services.task_board import (
    BoardSnapshot,
    ClaimHeld,
    Forbidden,
    LaneChanged,
    LaneInvalid,
    LaneNotEditable,
    LaneUnknown,
    LeaseLost,
    NotesTooLarge,
    RateLimited,
    TaskBoardClient,
    TaskBoardDomainError,
    TaskBoardError,
    TaskBoardUnavailable,
    TaskNotFound,
    VersionConflict,
)


class FakeResponse:
    def __init__(self, status_code: int, payload=None, *, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class Recorder:
    """Injected transport: records calls, replays queued responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError(f"unexpected extra call: {method} {url}")
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    @property
    def last_body(self):
        return self.calls[-1]["json"]


def client(*responses, key="k-123"):
    return TaskBoardClient(
        base_url="https://example.test/task/api",
        user_key=key,
        transport=Recorder(*responses),
    )


BOARD_PAYLOAD = {
    "board": {
        "id": "b1",
        "name": "tenhands",
        "handle": "01J000000000000000000HANDLE",
        "repo": "WolffM/tenhands",
        "mode": "automation",
        "schemaId": "autoland",
        "schemaVersion": 1,
        "access": "contributor",
        "lanes": [
            {"tag": "working", "label": "Working", "order": 3, "editableBy": "agent"},
            {"tag": "planning", "label": "Planning", "order": 0, "editableBy": "agent"},
            {"tag": "approved", "label": "Approved", "order": 2, "editableBy": "user"},
        ],
    },
    "tasks": [
        {"id": "t1", "title": "make coffee theme default", "tag": "approved",
         "notes": "", "metadata": {}, "claimed": False},
        {"id": "t2", "title": "bug-wooshing starts early", "tag": "working",
         "notes": "plan", "metadata": {"wf": "x"}, "claimed": True},
        {"id": "t3", "title": "raw thought", "tag": "", "notes": "",
         "metadata": {}, "claimed": False},
    ],
    "version": 7,
}


# ── auth / plumbing ───────────────────────────────────────────────────────


def test_missing_key_fails_before_any_request():
    """A missing key must fail loudly at the call site, not as a 401 later —
    the remediation (fetch it from the vault) is nothing like an auth bug."""
    c = TaskBoardClient(base_url="https://example.test", user_key="",
                        transport=Recorder())
    with pytest.raises(TaskBoardError, match="HADOKU_TASK_KEY"):
        c.get_board("h")
    assert c._transport.calls == []


def test_sends_user_key_header_and_builds_url():
    c = client(FakeResponse(200, BOARD_PAYLOAD))
    c.get_board("h1")
    call = c._transport.calls[0]
    assert call["url"] == "https://example.test/task/api/boards/h1"
    assert call["headers"]["X-User-Key"] == "k-123"


# ── board read ────────────────────────────────────────────────────────────


def test_get_board_parses_config_lanes_and_tasks():
    c = client(FakeResponse(200, BOARD_PAYLOAD))
    b = c.get_board("h1")
    assert isinstance(b, BoardSnapshot)
    assert (b.repo, b.schema_id, b.schema_version, b.version) == (
        "WolffM/tenhands", "autoland", 1, 7)
    assert [ln.tag for ln in b.lanes] == ["planning", "approved", "working"], \
        "lanes must be sorted by order, not response order"
    assert [ln.is_agent for ln in b.lanes] == [True, False, True]


def test_task_lane_resolves_from_space_separated_tags():
    """Tags are one space-separated string, not an array, so a lane is a
    token within it."""
    c = client(FakeResponse(200, BOARD_PAYLOAD))
    b = c.get_board("h1")
    by_id = {t.id: t for t in b.tasks}
    assert by_id["t1"].lane(b.lanes) == "approved"
    assert by_id["t3"].lane(b.lanes) is None


def test_task_with_two_lane_tags_is_none_not_a_guess():
    """A task carrying two lane tags is malformed — the board raises
    LANE_INVALID on write. Picking one here would hide that."""
    payload = json.loads(json.dumps(BOARD_PAYLOAD))
    payload["tasks"][0]["tag"] = "approved working"
    c = client(FakeResponse(200, payload))
    b = c.get_board("h1")
    assert b.tasks[0].lane(b.lanes) is None


def test_extra_non_lane_tags_do_not_confuse_lane_resolution():
    payload = json.loads(json.dumps(BOARD_PAYLOAD))
    payload["tasks"][0]["tag"] = "urgent approved someday"
    c = client(FakeResponse(200, payload))
    b = c.get_board("h1")
    assert b.tasks[0].lane(b.lanes) == "approved"


def test_tasks_in_and_untagged_and_claim_visibility():
    c = client(FakeResponse(200, BOARD_PAYLOAD))
    b = c.get_board("h1")
    assert [t.id for t in b.tasks_in("approved")] == ["t1"]
    assert [t.id for t in b.untagged()] == ["t3"]
    assert b.any_claim_live() is True


def test_any_claim_live_is_false_when_nothing_is_claimed():
    """Lane membership can't answer this — a task can sit in an agent lane
    with an expired claim, which is why the server sends `claimed`."""
    payload = json.loads(json.dumps(BOARD_PAYLOAD))
    for t in payload["tasks"]:
        t["claimed"] = False
    c = client(FakeResponse(200, payload))
    b = c.get_board("h1")
    assert b.any_claim_live() is False
    assert [t.id for t in b.tasks_in("working")] == ["t2"], \
        "the task is still in the lane; only the claim went away"


# ── claim protocol request shapes ─────────────────────────────────────────


def test_claim_sends_board_in_body():
    """Every agent endpoint needs `board` alongside `taskId` — the design doc
    said `{taskId, lane?}`, the shipped API disagrees."""
    c = client(FakeResponse(200, {"token": "tok-1"}))
    tok = c.claim("h1", "t1", lane="planning", lease_seconds=900)
    assert tok == "tok-1"
    assert c._transport.last_body == {
        "board": "h1", "taskId": "t1", "lane": "planning", "leaseSeconds": 900,
    }


def test_claim_omits_optional_fields_when_unset():
    c = client(FakeResponse(200, {"token": "t"}))
    c.claim("h1", "t1")
    assert c._transport.last_body == {"board": "h1", "taskId": "t1"}


def test_claim_without_token_in_response_is_an_error():
    c = client(FakeResponse(200, {"ok": True}))
    with pytest.raises(TaskBoardError, match="no token"):
        c.claim("h1", "t1")


def test_release_sends_metadata_and_complete():
    c = client(FakeResponse(200, {"released": True}))
    c.release("h1", "t1", "tok", lane="landed", notes="done",
              outcome="merged", metadata={"wf": "abc"}, complete=True,
              if_current_lane="landing")
    assert c._transport.last_body == {
        "board": "h1", "taskId": "t1", "token": "tok", "lane": "landed",
        "notes": "done", "outcome": "merged", "metadata": {"wf": "abc"},
        "complete": True, "ifCurrentLane": "landing",
    }


def test_release_omits_complete_when_false():
    """`complete` archives the task. It must never be sent implicitly."""
    c = client(FakeResponse(200, {}))
    c.release("h1", "t1", "tok", lane="stalled")
    assert "complete" not in c._transport.last_body


def test_release_can_send_empty_notes():
    """`notes=""` is a deliberate clear and must survive; only None omits."""
    c = client(FakeResponse(200, {}))
    c.release("h1", "t1", "tok", notes="")
    assert c._transport.last_body["notes"] == ""


def test_history_and_changes_use_query_params():
    c = client(FakeResponse(200, {"history": [{"outcome": "merged"}]}),
               FakeResponse(200, {"tasks": [], "cursor": "z"}))
    assert c.history("h1", "t1") == [{"outcome": "merged"}]
    assert c._transport.calls[0]["params"] == {"board": "h1", "task": "t1"}
    c.changes(since="2026-07-24T00:00:00Z,t1", limit=50)
    assert c._transport.calls[1]["params"] == {
        "limit": 50, "since": "2026-07-24T00:00:00Z,t1"}


# ── error mapping — the part that matters ─────────────────────────────────


@pytest.mark.parametrize("status,code,exc", [
    (409, "CLAIM_HELD", ClaimHeld),
    (409, "LEASE_LOST", LeaseLost),
    (409, "VERSION_CONFLICT", VersionConflict),
    (409, "LANE_CHANGED", LaneChanged),
    (403, "LANE_NOT_EDITABLE", LaneNotEditable),
    (403, "FORBIDDEN", Forbidden),
    (422, "LANE_UNKNOWN", LaneUnknown),
    (422, "LANE_INVALID", LaneInvalid),
    (404, "TASK_NOT_FOUND", TaskNotFound),
    (413, "NOTES_TOO_LARGE", NotesTooLarge),
    (429, "RATE_LIMITED", RateLimited),
])
def test_documented_codes_map_to_distinct_exceptions(status, code, exc):
    c = client(FakeResponse(status, {"code": code, "error": "nope"}))
    with pytest.raises(exc) as ei:
        c.claim("h1", "t1")
    assert ei.value.code == code
    assert ei.value.status == status


def test_claim_held_and_lease_lost_are_not_interchangeable():
    """Same status, same endpoint family, opposite required behaviour: one
    means try the next task, the other means abort and write nothing."""
    assert not issubclass(ClaimHeld, LeaseLost)
    assert not issubclass(LeaseLost, ClaimHeld)


def test_claim_held_exposes_holder_and_expiry():
    c = client(FakeResponse(409, {
        "code": "CLAIM_HELD", "error": "held",
        "holder": "agent-9", "expiresAt": "2026-07-24T12:00:00Z"}))
    with pytest.raises(ClaimHeld) as ei:
        c.claim("h1", "t1")
    assert ei.value.holder == "agent-9"
    assert ei.value.expires_at == "2026-07-24T12:00:00Z"


def test_rate_limited_exposes_retry_after():
    c = client(FakeResponse(429, {"code": "RATE_LIMITED", "retryAfter": 42}))
    with pytest.raises(RateLimited) as ei:
        c.get_board("h1")
    assert ei.value.retry_after == 42


def test_rate_limited_without_code_still_maps():
    """Older deployments answered 429 with no machine-readable code, and a
    429 we failed to recognise would be retried into a blacklist."""
    c = client(FakeResponse(429, {"error": "Rate limit exceeded",
                                  "retryAfter": 60}))
    with pytest.raises(RateLimited) as ei:
        c.get_board("h1")
    assert ei.value.retry_after == 60


def test_rate_limited_defaults_retry_after_when_absent_or_junk():
    for payload in ({"code": "RATE_LIMITED"},
                    {"code": "RATE_LIMITED", "retryAfter": "soon"}):
        c = client(FakeResponse(429, payload))
        with pytest.raises(RateLimited) as ei:
            c.get_board("h1")
        assert ei.value.retry_after == 60


def test_unmapped_4xx_code_still_raises_a_domain_error():
    """A new code we don't know about must not be mistaken for success or
    for a transport failure."""
    c = client(FakeResponse(418, {"code": "BREWING", "error": "teapot"}))
    with pytest.raises(TaskBoardDomainError) as ei:
        c.get_board("h1")
    assert ei.value.code == "BREWING"
    assert not isinstance(ei.value, TaskBoardUnavailable)


# ── unavailable vs refused ────────────────────────────────────────────────


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_is_unavailable_not_a_verdict(status):
    """The board didn't decide, it fell over. A write may or may not have
    landed, so this must never look like a clean refusal."""
    c = client(FakeResponse(status, {"error": "boom"}))
    with pytest.raises(TaskBoardUnavailable):
        c.release("h1", "t1", "tok", lane="landed")


def test_timeout_is_unavailable():
    c = client(requests.Timeout("slow"))
    with pytest.raises(TaskBoardUnavailable, match="timed out"):
        c.get_board("h1")


def test_connection_error_is_unavailable():
    c = client(requests.ConnectionError("refused"))
    with pytest.raises(TaskBoardUnavailable):
        c.get_board("h1")


def test_unavailable_is_not_a_domain_error():
    """The two branches must stay disjoint: callers switch on them."""
    assert not issubclass(TaskBoardUnavailable, TaskBoardDomainError)
    assert not issubclass(TaskBoardDomainError, TaskBoardUnavailable)


def test_unparseable_success_body_does_not_crash():
    c = client(FakeResponse(200, None, bad_json=True))
    assert c.changes() == {}


def test_unparseable_error_body_still_raises_by_status():
    c = client(FakeResponse(503, None, bad_json=True))
    with pytest.raises(TaskBoardUnavailable):
        c.get_board("h1")


def test_untagged_means_no_lane_tag_not_no_tags():
    """A task the human labelled `urgent` is still raw Inbox capture. An
    earlier version tested "no tags at all", which stranded any hand-labelled
    task: it had no lane, wasn't untagged, and so was invisible to every
    branch of selection."""
    payload = json.loads(json.dumps(BOARD_PAYLOAD))
    payload["tasks"][2]["tag"] = "urgent someday"
    c = client(FakeResponse(200, payload))
    b = c.get_board("h1")
    assert [t.id for t in b.untagged()] == ["t3"]
    assert b.malformed() == []


def test_malformed_is_two_lane_tags_only():
    payload = json.loads(json.dumps(BOARD_PAYLOAD))
    payload["tasks"][0]["tag"] = "approved working"
    payload["tasks"][2]["tag"] = "urgent"
    c = client(FakeResponse(200, payload))
    b = c.get_board("h1")
    assert [t.id for t in b.malformed()] == ["t1"]


def test_lane_tags_exposes_the_ambiguity_lane_hides():
    payload = json.loads(json.dumps(BOARD_PAYLOAD))
    payload["tasks"][0]["tag"] = "approved working"
    c = client(FakeResponse(200, payload))
    b = c.get_board("h1")
    t = b.tasks[0]
    assert t.lane(b.lanes) is None
    assert t.lane_tags(b.lanes) == ["approved", "working"]


def test_archived_tasks_are_excluded_from_every_selector():
    payload = json.loads(json.dumps(BOARD_PAYLOAD))
    payload["tasks"][0]["state"] = "Completed"
    payload["tasks"][1]["state"] = "Deleted"
    c = client(FakeResponse(200, payload))
    b = c.get_board("h1")
    assert [t.id for t in b.active_tasks] == ["t3"]
    assert b.tasks_in("approved") == []
    assert b.any_claim_live() is False, "the claimed task was deleted"


def test_explicit_empty_key_does_not_fall_back_to_the_environment(monkeypatch):
    """Regression, and it only reproduced under the vault wrapper. `or`
    treats an explicit "" as absent, so a client constructed with no
    credential silently authenticated as the real service account whenever
    HADOKU_TASK_KEY happened to be set in the process."""
    monkeypatch.setenv("HADOKU_TASK_KEY", "the-real-service-key")
    c = TaskBoardClient(base_url="https://example.test", user_key="",
                        transport=Recorder())
    with pytest.raises(TaskBoardError, match="HADOKU_TASK_KEY"):
        c.get_board("h")
    assert c._transport.calls == []


def test_key_omitted_entirely_does_read_the_environment(monkeypatch):
    monkeypatch.setenv("HADOKU_TASK_KEY", "from-env")
    c = TaskBoardClient(base_url="https://example.test",
                        transport=Recorder(FakeResponse(200, BOARD_PAYLOAD)))
    c.get_board("h1")
    assert c._transport.calls[0]["headers"]["X-User-Key"] == "from-env"
