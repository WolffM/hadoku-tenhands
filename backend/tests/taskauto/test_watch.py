"""Tests for temporal/taskauto/watch.py.

The safety net. Its job is to be *suspicious*: an unknown must never read as
healthy, and a 200 that says nothing must never read as a working service.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from temporal.taskauto.watch import ProdWatcher, Reverter, WatchResult

HEALTHY = '{"status":"healthy","apiVersion":"2.0.0"}'
SPA = "<!DOCTYPE html><html>the frontend shell</html>"


class Clock:
    """Monotonic time the tests control, so windows are instant."""

    def __init__(self):
        self.t = 0.0

    def sleep(self, s):
        self.t += s


def watcher(runs=None, https=None, monkeypatch=None):
    clock = Clock()
    run_q = list(runs or [])
    http_q = list(https or [])

    def run(args):
        return run_q.pop(0) if run_q else (True, "[]")

    def http(url):
        if not http_q:
            return 200, HEALTHY
        nxt = http_q.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    w = ProdWatcher(run=run, http=http, sleep=clock.sleep)
    if monkeypatch:
        monkeypatch.setattr("temporal.taskauto.watch.time.monotonic",
                            lambda: clock.t)
    return w


def gh(*runs):
    return (True, json.dumps(list(runs)))


DONE_OK = gh({"status": "completed", "conclusion": "success"})
DONE_BAD = gh({"status": "completed", "conclusion": "failure"})


# ── deploy ────────────────────────────────────────────────────────────────


def test_a_successful_deploy_is_reported(monkeypatch):
    w = watcher(runs=[DONE_OK], monkeypatch=monkeypatch)
    assert w.deploy_conclusion("o/r", "sha") == "success"


def test_a_failed_deploy_is_reported(monkeypatch):
    w = watcher(runs=[DONE_BAD], monkeypatch=monkeypatch)
    assert w.deploy_conclusion("o/r", "sha") == "failure"


def test_the_worst_conclusion_wins(monkeypatch):
    """Both pm2 services deploy from one push; one failing is a failure."""
    w = watcher(runs=[gh({"status": "completed", "conclusion": "success"},
                         {"status": "completed", "conclusion": "failure"})],
                monkeypatch=monkeypatch)
    assert w.deploy_conclusion("o/r", "sha") == "failure"


def test_skipped_and_neutral_do_not_count_as_failure(monkeypatch):
    w = watcher(runs=[gh({"status": "completed", "conclusion": "skipped"},
                         {"status": "completed", "conclusion": "success"})],
                monkeypatch=monkeypatch)
    assert w.deploy_conclusion("o/r", "sha") == "success"


def test_it_waits_for_in_progress_runs(monkeypatch):
    w = watcher(runs=[gh({"status": "in_progress", "conclusion": None}),
                      DONE_OK], monkeypatch=monkeypatch)
    assert w.deploy_conclusion("o/r", "sha") == "success"


def test_no_run_at_all_is_not_success(monkeypatch):
    """'I never saw it deploy' must not read as 'it deployed fine'."""
    w = watcher(runs=[(True, "[]")] * 200, monkeypatch=monkeypatch)
    assert w.deploy_conclusion("o/r", "sha", timeout_s=60) == ""


def test_a_run_that_never_completes_times_out(monkeypatch):
    w = watcher(runs=[gh({"status": "in_progress", "conclusion": None})] * 200,
                monkeypatch=monkeypatch)
    assert w.deploy_conclusion("o/r", "sha", timeout_s=60) == "timeout"


# ── health ────────────────────────────────────────────────────────────────


def test_healthy_across_the_window(monkeypatch):
    w = watcher(https=[(200, HEALTHY)] * 50, monkeypatch=monkeypatch)
    ok, samples = w.sample_health("u", '"status":"healthy"', window_s=60)
    assert ok and samples and all(s == "ok" for s in samples)


def test_a_200_with_the_wrong_body_is_not_healthy(monkeypatch):
    """The real trap: /tenhands/health through the edge returns 200 with the
    SPA shell whether or not the backend is alive. A status-code-only check
    would call a dead service healthy."""
    w = watcher(https=[(200, SPA)], monkeypatch=monkeypatch)
    ok, samples = w.sample_health("u", '"status":"healthy"', window_s=60)
    assert ok is False
    assert "lacks" in samples[-1]


def test_a_non_200_fails(monkeypatch):
    w = watcher(https=[(502, "bad gateway")], monkeypatch=monkeypatch)
    ok, samples = w.sample_health("u", '"status":"healthy"', window_s=60)
    assert ok is False and "502" in samples[-1]


def test_unreachable_fails_rather_than_being_ignored(monkeypatch):
    w = watcher(https=[ConnectionError("refused")], monkeypatch=monkeypatch)
    ok, samples = w.sample_health("u", '"status":"healthy"', window_s=60)
    assert ok is False and "unreachable" in samples[-1]


def test_a_late_failure_inside_the_window_is_caught(monkeypatch):
    """A service that restarts cleanly and falls over thirty seconds later
    is exactly what a single final probe misses."""
    w = watcher(https=[(200, HEALTHY), (200, HEALTHY), (500, "boom")],
                monkeypatch=monkeypatch)
    ok, samples = w.sample_health("u", '"status":"healthy"', window_s=120,
                                  poll_s=20)
    assert ok is False and "500" in samples[-1]


# ── the combined verdict ──────────────────────────────────────────────────


def test_watch_is_healthy_only_when_both_signals_are(monkeypatch):
    w = watcher(runs=[DONE_OK], https=[(200, HEALTHY)] * 50,
                monkeypatch=monkeypatch)
    r = w.watch("o/r", "sha", health_url="u", window_s=40)
    assert r.healthy and r.should_revert is False


def test_a_failed_deploy_short_circuits_to_revert(monkeypatch):
    w = watcher(runs=[DONE_BAD], monkeypatch=monkeypatch)
    r = w.watch("o/r", "sha", health_url="u", window_s=40)
    assert r.should_revert and "failure" in r.reason


def test_a_missing_deploy_run_means_revert(monkeypatch):
    """Unknown is not healthy."""
    w = watcher(runs=[(True, "[]")] * 200, monkeypatch=monkeypatch)
    r = w.watch("o/r", "sha", health_url="u", window_s=40)
    assert r.should_revert and "cannot confirm" in r.reason


def test_bad_health_after_a_good_deploy_means_revert(monkeypatch):
    w = watcher(runs=[DONE_OK], https=[(200, SPA)], monkeypatch=monkeypatch)
    r = w.watch("o/r", "sha", health_url="u", window_s=40)
    assert r.should_revert and "health check failed" in r.reason


# ── revert ────────────────────────────────────────────────────────────────


class FakeGit:
    def __init__(self, fail=()):
        self.fail = fail
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        joined = " ".join(args)

        class R:
            ok = not any(f in joined for f in self.fail)
            out = "revsha123\n"
            err = "nope"
        return R()

    def ran(self, pat):
        return [c for c in self.calls if pat in " ".join(c)]


def test_revert_branches_from_current_main_and_pushes():
    g = FakeGit()
    sha = Reverter(run=g).revert(Path("/co"), "deadbeefcafe")
    assert g.ran("fetch origin main")
    assert g.ran("revert --no-edit")
    assert g.ran("push origin HEAD:main")
    assert sha == "revsha123"


def test_revert_never_force_pushes():
    """History people may already have pulled stays intact, and the undo is
    itself reviewable."""
    g = FakeGit()
    Reverter(run=g).revert(Path("/co"), "deadbeef")
    assert g.ran("--force-with-lease") == [] and g.ran("push --force") == []


def test_a_plain_commit_falls_back_from_the_merge_parent_flag():
    """`-m 1` is required for a merge and rejected for a plain commit."""
    g = FakeGit(fail=("revert --no-edit -m 1",))
    Reverter(run=g).revert(Path("/co"), "deadbeef")
    assert len(g.ran("revert --no-edit")) == 2


def test_a_revert_that_cannot_be_produced_raises_loudly():
    # Match the command, not the branch name — the working branch is called
    # `revert-<sha>`, so a bare "revert" pattern fails the checkout instead.
    g = FakeGit(fail=("revert --no-edit",))
    with pytest.raises(RuntimeError, match="could not revert"):
        Reverter(run=g).revert(Path("/co"), "deadbeef")


def test_a_revert_that_cannot_be_pushed_raises_loudly():
    """Silently failing here would leave prod broken while reporting that it
    had been fixed."""
    g = FakeGit(fail=("push",))
    with pytest.raises(RuntimeError, match="push failed"):
        Reverter(run=g).revert(Path("/co"), "deadbeef")
