"""Tests for temporal/claude_tokens.py: the lease client and the CLI's failure text."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from temporal import claude_tokens as CT

# 2026-11-15 12:00 in Los Angeles.
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
WEEKLY = "You've hit your weekly limit · resets Nov 18, 3pm (America/Los_Angeles)"
AUTH_401 = "Failed to authenticate. API Error: 401 OAuth access token has been revoked."


# ── reading the CLI's failure text ────────────────────────────────────────


def test_a_weekly_limit_is_rate_limited_until_the_printed_reset():
    b = CT.classify(WEEKLY, NOW)
    assert b.outcome == CT.RATE_LIMITED
    assert b.resets == datetime(2026, 11, 18, 15, 0,
                               tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()


def test_a_time_already_past_today_means_tomorrow():
    b = CT.classify("5-hour limit reached ∙ resets 9am (America/Los_Angeles)", NOW)
    assert b.resets == datetime(2026, 11, 16, 9, 0,
                               tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()


def test_the_epoch_form_is_read_exactly():
    at = int(NOW) + 3600
    assert CT.classify(f"Claude AI usage limit reached|{at}", NOW).resets == at


def test_a_limit_with_no_reset_has_none():
    b = CT.classify("Claude AI usage limit reached", NOW)
    assert (b.outcome, b.resets) == (CT.RATE_LIMITED, None)


def test_a_bare_429_is_rate_limited():
    b = CT.classify('API Error: 429 {"type":"rate_limit_error"}', NOW)
    assert (b.outcome, b.resets) == (CT.RATE_LIMITED, None)


def test_an_unreadable_zone_is_no_reset_rather_than_a_guess():
    b = CT.classify("hit your weekly limit · resets Nov 18, 3pm (Mars/Olympus)", NOW)
    assert b.resets is None


@pytest.mark.parametrize("text", [
    AUTH_401,
    "Invalid API key · Please run /login",
    "OAuth token has expired",
])
def test_an_auth_failure_is_unauthorized(text):
    assert CT.classify(text, NOW).outcome == CT.UNAUTHORIZED


@pytest.mark.parametrize("text", [
    "Credit balance is too low",
    "error: tests failed",
    "the endpoint returns 401 for anonymous users",
    "",
])
def test_other_failures_are_not_the_accounts(text):
    assert CT.classify(text, NOW) is None


def test_only_the_tail_of_a_long_transcript_is_read():
    """An agent that worked on a rate-limit bug talks about rate limits."""
    text = "fixed the rate_limit handling\n" + "x" * 5000 + "\nerror: build failed"
    assert CT.classify(text, NOW) is None


# ── the lease client, against a crossposter on a real socket ─────────────


def test_a_lease_is_the_active_accounts_token(crossposter):
    lease = CT.LeaseClient.from_env().lease()
    assert (lease.account, lease.token) == ("matth2", "tok-matth2")
    assert lease.lease_id == crossposter.leases[0]["lease_id"]
    # Cloudflare refuses requests' default agent with error 1010.
    assert crossposter.user_agents == [CT.USER_AGENT]


def test_a_lease_never_shows_its_token(crossposter):
    lease = CT.LeaseClient.from_env().lease()
    assert "tok-matth2" not in repr(lease) and "tok-matth2" not in str(lease)


def test_a_rate_limited_outcome_moves_crossposter_to_the_next_account(crossposter):
    client = CT.LeaseClient.from_env()
    lease = client.lease()
    answer = client.report(lease, CT.RATE_LIMITED)
    assert answer["benched"] is True
    assert CT.next_account(answer, {"matth2"}) == "matth"
    assert client.lease().account == "matth"
    assert crossposter.outcomes == [{"account": "matth2", "outcome": "rate_limited"}]


def test_next_account_is_none_when_crossposter_points_back_or_nowhere():
    assert CT.next_account({"active": "matth"}, {"matth"}) is None
    assert CT.next_account({"active": None}, set()) is None
    assert CT.next_account(None, set()) is None


def test_not_on_the_allow_list_names_the_grant(crossposter):
    crossposter.refuse = 403
    with pytest.raises(CT.LeaseUnavailable, match="crossposter-claude-code-lease") as e:
        CT.LeaseClient.from_env().lease()
    assert e.value.quota_only is False


def test_every_account_rate_limited_is_quota_only(crossposter):
    crossposter.benched = {a: "benched: HTTP 429 on lease x" for a in crossposter.accounts}
    with pytest.raises(CT.LeaseUnavailable, match="HTTP 503") as e:
        CT.LeaseClient.from_env().lease()
    assert e.value.quota_only is True


def test_a_dead_account_among_spent_ones_is_not_just_waiting(crossposter):
    crossposter.benched = {"matth2": "spent: usage limit reached until x",
                           "matth": "dead: HTTP 401", "james": "spent: usage limit reached until x"}
    with pytest.raises(CT.LeaseUnavailable) as e:
        CT.LeaseClient.from_env().lease()
    assert e.value.quota_only is False


def test_unreachable_crossposter_fails_and_says_where(monkeypatch):
    monkeypatch.setenv("HADOKU_SERVICE_KEY", "k")
    with pytest.raises(CT.LeaseUnavailable, match="unreachable at http://127.0.0.1:9"):
        CT.LeaseClient.from_env().lease()


def test_no_service_key_is_no_lease(monkeypatch):
    monkeypatch.delenv("HADOKU_SERVICE_KEY", raising=False)
    with pytest.raises(CT.LeaseUnavailable, match="HADOKU_SERVICE_KEY"):
        CT.LeaseClient.from_env()


def test_a_report_that_does_not_arrive_is_logged_not_raised(crossposter, caplog):
    client = CT.LeaseClient.from_env()
    lease = client.lease()
    crossposter.stop()
    assert client.report(lease, CT.OK) is None
    assert "could not report ok" in caplog.text
    assert "tok-matth2" not in caplog.text
    crossposter.start()  # the fixture's teardown stops it again
