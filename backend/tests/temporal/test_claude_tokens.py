"""Tests for temporal/claude_tokens.py — the Claude OAuth token pool."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from temporal import claude_tokens as CT

# 2026-11-15 12:00 in Los Angeles.
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
WEEKLY = "You've hit your weekly limit · resets Nov 18, 3pm (America/Los_Angeles)"
AUTH_401 = "Failed to authenticate. API Error: 401 OAuth access token has been revoked."


def pool(tmp_path, tokens, now=NOW, notified=None):
    return CT.TokenPool(tokens, state_path=tmp_path / "state.json", now=lambda: now,
                        notify=(lambda t, d: notified.append((t, d))) if notified is not None
                        else (lambda t, d: None))


A, B, C = CT.Token("james", "tok-a"), CT.Token("matth", "tok-b"), CT.Token("matth2", "tok-c")


# ── where tokens come from ────────────────────────────────────────────────


def test_named_tokens_come_first_then_the_legacy_one():
    env = {"CLAUDE_OAUTH_TOKEN_MATTH2": "c", "CLAUDE_OAUTH_TOKEN_JAMES": "a",
           "CLAUDE_CODE_OAUTH_TOKEN": "legacy", "OTHER": "x"}
    assert [t.label for t in CT.load_tokens(env)] == ["james", "matth2", "default"]


def test_a_value_under_two_names_is_one_token():
    """The legacy item and a named one will hold the same value during the move."""
    env = {"CLAUDE_OAUTH_TOKEN_MATTH": "same", "CLAUDE_CODE_OAUTH_TOKEN": "same"}
    assert [t.label for t in CT.load_tokens(env)] == ["matth"]


def test_blank_values_and_a_bare_prefix_are_ignored():
    env = {"CLAUDE_OAUTH_TOKEN_A": "  ", "CLAUDE_OAUTH_TOKEN_": "x",
           "CLAUDE_CODE_OAUTH_TOKEN": ""}
    assert CT.load_tokens(env) == []


def test_a_token_never_shows_its_value():
    t = CT.Token("matth", "sk-ant-oat01-secret")
    assert "secret" not in repr(t) and "secret" not in str(t)


# ── reading the CLI's failure text ────────────────────────────────────────


def test_a_weekly_limit_benches_until_the_printed_reset():
    b = CT.classify(WEEKLY, NOW)
    assert b.kind == CT.QUOTA
    assert b.until == datetime(2026, 11, 18, 15, 0,
                               tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()


def test_a_time_already_past_today_means_tomorrow():
    b = CT.classify("5-hour limit reached ∙ resets 9am (America/Los_Angeles)", NOW)
    assert b.until == datetime(2026, 11, 16, 9, 0,
                               tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()


def test_the_epoch_form_is_read_exactly():
    at = int(NOW) + 3600
    assert CT.classify(f"Claude AI usage limit reached|{at}", NOW).until == at


def test_a_limit_with_no_reset_falls_back_to_half_an_hour():
    assert CT.classify("Claude AI usage limit reached", NOW).until == NOW + CT.QUOTA_FALLBACK_S


def test_a_bare_429_is_a_short_rate_limit():
    b = CT.classify('API Error: 429 {"type":"rate_limit_error"}', NOW)
    assert (b.kind, b.until) == (CT.QUOTA, NOW + CT.RATE_LIMIT_S)


def test_an_unreadable_zone_falls_back_rather_than_guessing():
    b = CT.classify("hit your weekly limit · resets Nov 18, 3pm (Mars/Olympus)", NOW)
    assert b.until == NOW + CT.QUOTA_FALLBACK_S


@pytest.mark.parametrize("text", [
    AUTH_401,
    "Invalid API key · Please run /login",
    "OAuth token has expired",
])
def test_an_auth_failure_is_the_tokens_fault(text):
    assert CT.classify(text, NOW).kind == CT.AUTH


@pytest.mark.parametrize("text", [
    "Credit balance is too low",
    "error: tests failed",
    "the endpoint returns 401 for anonymous users",
    "",
])
def test_other_failures_bench_nothing(text):
    assert CT.classify(text, NOW) is None


def test_only_the_tail_of_a_long_transcript_is_read():
    """An agent that worked on a rate-limit bug talks about rate limits."""
    text = "fixed the rate_limit handling\n" + "x" * 5000 + "\nerror: build failed"
    assert CT.classify(text, NOW) is None


# ── the pool ──────────────────────────────────────────────────────────────


def test_all_tokens_are_offered_in_order_when_none_is_benched(tmp_path):
    assert pool(tmp_path, [A, B, C]).available() == [A, B, C]


def test_a_benched_token_is_skipped_until_its_reset(tmp_path):
    p = pool(tmp_path, [A, B, C])
    assert p.bench_if_token_problem(A, WEEKLY).kind == CT.QUOTA
    assert p.available() == [B, C]
    later = pool(tmp_path, [A, B, C], now=CT.classify(WEEKLY, NOW).until + 1)
    assert later.available() == [A, B, C]


def test_a_failure_that_is_not_the_tokens_benches_nothing(tmp_path):
    p = pool(tmp_path, [A, B])
    assert p.bench_if_token_problem(A, "error: tests failed") is None
    assert p.available() == [A, B]


def test_benches_are_shared_through_the_state_file(tmp_path):
    """The one-shot taskauto run and the judge worker learn from each other."""
    pool(tmp_path, [A, B]).bench_if_token_problem(A, WEEKLY)
    assert pool(tmp_path, [A, B]).available() == [B]


def test_a_rotated_token_starts_clean(tmp_path):
    """Benches are keyed by the token, not its label."""
    pool(tmp_path, [A, B]).bench_if_token_problem(A, AUTH_401)
    rotated = CT.Token("james", "tok-a-new")
    assert pool(tmp_path, [rotated, B]).available() == [rotated, B]


def test_the_state_file_holds_no_token_values(tmp_path):
    pool(tmp_path, [A]).bench_if_token_problem(A, WEEKLY)
    raw = (tmp_path / "state.json").read_text()
    assert "tok-a" not in raw
    assert json.loads(raw)[A.fingerprint]["label"] == "james"


def test_an_unreadable_state_file_is_an_empty_one(tmp_path):
    (tmp_path / "state.json").write_text("{not json")
    assert pool(tmp_path, [A]).available() == [A]


def test_every_token_benched_for_quota_says_when_the_first_comes_back(tmp_path):
    p = pool(tmp_path, [A, B])
    p.bench_if_token_problem(A, WEEKLY)
    p.bench_if_token_problem(B, "5-hour limit reached ∙ resets 3pm (America/Los_Angeles)")
    with pytest.raises(CT.PoolExhausted) as e:
        p.available()
    assert e.value.quota_only
    assert e.value.earliest == datetime(2026, 11, 15, 15, 0,
                                        tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
    assert "james: quota" in str(e.value) and "matth: quota" in str(e.value)


def test_a_dead_token_in_the_mix_is_not_just_waiting(tmp_path):
    p = pool(tmp_path, [A, B])
    p.bench_if_token_problem(A, WEEKLY)
    p.bench_if_token_problem(B, AUTH_401)
    with pytest.raises(CT.PoolExhausted) as e:
        p.available()
    assert not e.value.quota_only


def test_an_empty_pool_offers_nothing_rather_than_failing(tmp_path):
    assert pool(tmp_path, []).available() == []


def test_a_rejected_token_is_reported_once(tmp_path):
    notified = []
    p = pool(tmp_path, [A, B], notified=notified)
    p.bench_if_token_problem(A, AUTH_401)
    p.bench_if_token_problem(A, AUTH_401)
    assert len(notified) == 1
    title, description = notified[0]
    assert "james" in title and "CLAUDE_OAUTH_TOKEN_JAMES" in description
    assert "tok-a" not in title + description


def test_a_quota_bench_is_not_reported(tmp_path):
    notified = []
    pool(tmp_path, [A], notified=notified).bench_if_token_problem(A, WEEKLY)
    assert notified == []


def test_status_lists_benches_without_values(tmp_path):
    p = pool(tmp_path, [A, B])
    p.bench_if_token_problem(B, AUTH_401)
    rows = p.status()
    assert [(r["label"], r["benched"]) for r in rows] == [("james", None), ("matth", "auth")]
    assert "tok-" not in json.dumps(rows)
