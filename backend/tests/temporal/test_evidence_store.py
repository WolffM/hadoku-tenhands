"""Unit tests for backend.temporal.evidence.store — Phase 1A.5.

Per the test plan in phase-1-plan.md step 1A.5, these cover:
  1. write_text / read_text round-trip
  2. write_json / read_json round-trip
  3. append_jsonl across multiple calls
  4. record_transition produces valid records
  5. record_gate produces valid records
  6. for_issue path construction with `/` in slug
  7. concurrent JSONL appends from multiple threads don't corrupt
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from temporal.evidence.store import EvidenceStore, _encode_slug


@pytest.fixture
def store(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "issue-1")


def test_write_text_read_text_roundtrip(store: EvidenceStore):
    store.write_text("01-eligible/notes.txt", "hello world\nline 2\n")
    assert store.read_text("01-eligible/notes.txt") == "hello world\nline 2\n"


def test_write_json_read_json_roundtrip(store: EvidenceStore):
    payload = {"a": 1, "nested": {"b": [1, 2, 3]}, "s": "x"}
    store.write_json("05-fixed/relevance_check.json", payload)
    assert store.read_json("05-fixed/relevance_check.json") == payload


def test_append_jsonl_appends_across_calls(store: EvidenceStore):
    for i in range(5):
        store.append_jsonl("events.jsonl", {"i": i, "msg": f"event {i}"})

    records = store.read_jsonl("events.jsonl")
    assert len(records) == 5
    assert [r["i"] for r in records] == [0, 1, 2, 3, 4]


def test_record_transition_writes_valid_jsonl(store: EvidenceStore):
    store.record_transition("eligible", "forked", "all gates passed", "system:gate")
    store.record_transition("forked", "environment_ready", "env up", "system:gate")

    records = store.read_jsonl("transitions.jsonl")
    assert len(records) == 2
    assert records[0]["from"] == "eligible"
    assert records[0]["to"] == "forked"
    assert records[0]["reason"] == "all gates passed"
    assert records[0]["decided_by"] == "system:gate"
    assert "ts" in records[0]


def test_record_gate_writes_valid_jsonl_with_optional_data(store: EvidenceStore):
    store.record_gate("diff_non_empty", "pass")
    store.record_gate(
        "input_context_clean",
        "fail",
        reason="bare upstream slug present: microsoft/markitdown",
        evidence_data={"leaks": ["microsoft/markitdown"]},
    )

    records = store.read_jsonl("gates.jsonl")
    assert len(records) == 2
    assert records[0]["gate"] == "diff_non_empty"
    assert records[0]["verdict"] == "pass"
    assert records[0]["evidence_data"] is None
    assert records[1]["evidence_data"] == {"leaks": ["microsoft/markitdown"]}


def test_for_issue_constructs_path_with_encoded_slug(tmp_path: Path):
    store = EvidenceStore.for_issue(
        "crimson-kitty", "microsoft/markitdown", 183, base=tmp_path
    )
    assert store.root == tmp_path / "crimson-kitty" / "microsoft__markitdown-183"
    assert store.root.exists()


def test_for_issue_handles_multi_segment_slug(tmp_path: Path):
    store = EvidenceStore.for_issue(
        "test-batch", "mermaid-js/mermaid", 4099, base=tmp_path
    )
    assert "mermaid-js__mermaid-4099" in str(store.root)


def test_concurrent_jsonl_appends_do_not_corrupt(store: EvidenceStore):
    NUM_THREADS = 10
    PER_THREAD = 50

    def worker(tid: int):
        for i in range(PER_THREAD):
            store.append_jsonl("events.jsonl", {"tid": tid, "i": i})

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(NUM_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    records = store.read_jsonl("events.jsonl")
    assert len(records) == NUM_THREADS * PER_THREAD
    # Every (tid, i) pair appears exactly once
    pairs = {(r["tid"], r["i"]) for r in records}
    expected = {(t, i) for t in range(NUM_THREADS) for i in range(PER_THREAD)}
    assert pairs == expected
    # Every line is valid JSON (no torn writes)
    raw = store.read_text("events.jsonl")
    for line in raw.splitlines():
        json.loads(line)


# ── extras ────────────────────────────────────────────────────────────────


def test_path_helper_returns_absolute_under_root(store: EvidenceStore):
    p = store.path("05-fixed/diff.patch")
    assert p == store.root / "05-fixed" / "diff.patch"


def test_exists_returns_false_for_missing(store: EvidenceStore):
    assert store.exists("nope") is False
    store.write_text("yes", "ok")
    assert store.exists("yes") is True


def test_read_text_default_when_missing(store: EvidenceStore):
    assert store.read_text("nope", default="fallback") == "fallback"


def test_read_text_raises_when_missing_and_no_default(store: EvidenceStore):
    with pytest.raises(FileNotFoundError):
        store.read_text("missing")


def test_read_jsonl_returns_empty_when_missing(store: EvidenceStore):
    assert store.read_jsonl("never-written.jsonl") == []


def test_encode_slug():
    assert _encode_slug("microsoft/markitdown") == "microsoft__markitdown"
    assert _encode_slug("simple") == "simple"
