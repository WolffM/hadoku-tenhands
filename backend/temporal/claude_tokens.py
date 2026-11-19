"""Claude Code tokens, leased from crossposter.

Every `claude` subprocess tenhands spawns (taskauto's agent, the crimson-kitty
judge, the CI judge test) needs a `CLAUDE_CODE_OAUTH_TOKEN`. tenhands does not
hold one. crossposter is the account authority (its plan
`docs/planning/account-authority-2026-11-19.md`, step 1d; #115): it decides
which Claude Code account is active, from Anthropic's own verdict and the
operator's override, and lends that account's token.

* **One lease per run.** `LeaseClient.lease()` is `POST
  /crossposter/claude-code/lease` with tenhands' service key, answering
  `{lease_id, account, vault_item, token, expires_at}`. A lease is used for one
  run and dropped; nothing is cached, so nothing outlives `expires_at`.
* **The outcome goes back.** After the run, `report()` posts `ok`,
  `rate_limited` or `unauthorized` (or `error` for a failure that is neither).
  A 429 or a 401 benches the account in crossposter, which re-decides the active
  account at once and says which one in its answer. When that is an account this
  run has not tried, the caller may go again on a new lease. tenhands keeps no
  bench of its own and no timer: crossposter's answer is the signal.
* **No fallback.** When crossposter cannot lease (unreachable, the allow list
  refuses tenhands, no account usable) the run fails with crossposter's reason.
  It never falls back to a token from the environment.

Token values never appear in logs, exceptions or `repr`; a lease is identified
by its account and lease id.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

logger = logging.getLogger(__name__)

#: Where crossposter is reached: through the edge, at service tier, behind the
#: `crossposter-claude-code-lease` allow list (hadoku_site a585e7421).
DEFAULT_BASE_URL = "https://hadoku.me/crossposter"
LEASE_PATH = "/claude-code/lease"
OUTCOME_PATH = "/claude-code/lease/outcome"
HTTP_TIMEOUT_S = 15
#: Cloudflare refuses urllib/requests' default User-Agent (error code 1010).
USER_AGENT = "hadoku-tenhands/claude-lease"

OK = "ok"
RATE_LIMITED = "rate_limited"
UNAUTHORIZED = "unauthorized"
ERROR = "error"

#: No reset the CLI could print is further away than a week; anything parsed
#: past this is a misparse.
MAX_RESET_S = 8 * 24 * 3600


# ── reading the CLI's failure text ────────────────────────────────────────

# The CLI's own wording when the account, not the code, is the problem:
#   "You've hit your weekly limit · resets Nov 6, 3pm (America/Los_Angeles)"
#   "5-hour limit reached ∙ resets 3pm"
#   "Claude AI usage limit reached|1762470000"
#   "API Error: 429 {... "type":"rate_limit_error" ...}"
# Deliberately narrow: "Credit balance is too low" or an empty answer are
# things to go fix, and must not bench an account that is fine.
QUOTA_RE = re.compile(
    r"hit your (?:\w+[- ])*limit|limit reached|usage limit|rate[ _]limit",
    re.IGNORECASE,
)
_PLAN_LIMIT_RE = re.compile(r"hit your (?:\w+[- ])*limit|limit reached|usage limit",
                            re.IGNORECASE)
RESETS_RE = re.compile(r"\bresets\s+(?:at\s+)?([^\n]+)", re.IGNORECASE)
_EPOCH_RE = re.compile(r"limit reached\|(\d{10})\b", re.IGNORECASE)

# 2026-08-08: `Failed to authenticate. API Error: 401 OAuth access token has
# been revoked.` — on stdout, exit 1, in ~3s.
AUTH_RE = re.compile(
    r"failed to authenticate|api error: 401\b|oauth (?:access )?token has (?:been revoked|expired)"
    r"|invalid (?:api key|bearer token)|please run /login",
    re.IGNORECASE,
)

_RESET_TIME_RE = re.compile(
    r"^(?:(?P<mon>[A-Za-z]{3})[a-z]*\s+(?P<day>\d{1,2}),?\s+(?:at\s+)?)?"
    r"(?P<hour>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ampm>am|pm)"
    r"(?:\s*\((?P<tz>[^)]+)\))?",
    re.IGNORECASE,
)
_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def parse_reset(text: str, now: float) -> float | None:
    """When the CLI says the limit lifts, as an epoch, or None if it didn't say.

    Handles the epoch form (`limit reached|1762470000`) and the human one
    (`resets 3pm`, `resets 11:30pm (UTC)`, `resets Nov 6, 3pm (America/Los_Angeles)`).
    A time with no date is the next such time; a date with no year is the next
    such date. A time with no zone is read as the host's local time.
    """
    m = _EPOCH_RE.search(text)
    if m:
        at = float(m.group(1))
        return at if now < at <= now + MAX_RESET_S else None
    m = RESETS_RE.search(text)
    if not m:
        return None
    t = _RESET_TIME_RE.match(m.group(1).strip())
    if not t:
        return None
    tz = None
    if t.group("tz"):
        try:
            tz = ZoneInfo(t.group("tz").strip())
        except (ZoneInfoNotFoundError, ValueError):
            return None
    base = datetime.fromtimestamp(now, tz) if tz else datetime.fromtimestamp(now).astimezone()
    hour = int(t.group("hour")) % 12 + (12 if t.group("ampm").lower() == "pm" else 0)
    minute = int(t.group("min") or 0)
    if t.group("mon"):
        month = _MONTHS.get(t.group("mon").lower()[:3])
        if month is None:
            return None
        try:
            at = base.replace(month=month, day=int(t.group("day")), hour=hour,
                              minute=minute, second=0, microsecond=0)
            if at.timestamp() <= now:
                at = at.replace(year=at.year + 1)
        except ValueError:
            return None
    else:
        at = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at.timestamp() <= now:
            at += timedelta(days=1)
    epoch = at.timestamp()
    return epoch if epoch <= now + MAX_RESET_S else None


@dataclass(frozen=True)
class Failure:
    """A run that failed because of its account, not its task."""

    outcome: str  # RATE_LIMITED or UNAUTHORIZED
    resets: float | None  # when the CLI said the limit lifts (epoch), if it did
    detail: str


def classify(text: str, now: float) -> Failure | None:
    """Is this failure the account's fault? If so, which outcome to report."""
    if not text:
        return None
    # The CLI's own error is its last word; an agent's long transcript ahead of
    # it can mention "rate limit" or a 401 in the task it was working on.
    text = text[-2000:]
    detail = text.strip()[-300:]
    if QUOTA_RE.search(text):
        return Failure(RATE_LIMITED, parse_reset(text, now), detail)
    if AUTH_RE.search(text):
        return Failure(UNAUTHORIZED, None, detail)
    return None


# ── the lease ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Lease:
    lease_id: str
    account: str
    token: str = field(repr=False)
    expires_at: str

    def __str__(self) -> str:
        return f"{self.account} (lease {self.lease_id[:8]})"


class LeaseUnavailable(RuntimeError):
    """crossposter gave no lease. `quota_only` when every account is only out
    of quota: nothing is broken, the pool is waiting for a reset."""

    def __init__(self, message: str, *, quota_only: bool = False):
        super().__init__(message)
        self.quota_only = quota_only


def _quota_only(detail: object) -> bool:
    """crossposter's 503 lists each account's `why_not`. All of them spent, or
    benched on a 429, is a wait; anything else (dead, no credential) is not."""
    accounts = detail.get("accounts") if isinstance(detail, dict) else None
    if not accounts:
        return False
    return all(
        isinstance(a, dict) and (str(a.get("why_not") or "").startswith("spent")
                                 or "HTTP 429" in str(a.get("why_not") or ""))
        for a in accounts
    )


Post = Callable[..., requests.Response]


class LeaseClient:
    def __init__(self, key: str, base_url: str = DEFAULT_BASE_URL, *, post: Post | None = None):
        self.key = key
        self.base_url = base_url.rstrip("/")
        self._post = post or requests.post

    @classmethod
    def from_env(cls) -> LeaseClient:
        """tenhands' service key (`HADOKU_SERVICE_KEY`) and crossposter's base
        URL (`TENHANDS_CROSSPOSTER_URL`, for a test double)."""
        key = (os.environ.get("HADOKU_SERVICE_KEY") or "").strip()
        if not key:
            raise LeaseUnavailable(
                "HADOKU_SERVICE_KEY is not set, so no Claude token can be leased from "
                "crossposter (the vault item KEY_SERVICE_TENHANDS)")
        return cls(key, os.environ.get("TENHANDS_CROSSPOSTER_URL") or DEFAULT_BASE_URL)

    def _call(self, path: str, body: dict) -> requests.Response:
        return self._post(
            self.base_url + path, json=body, timeout=HTTP_TIMEOUT_S,
            headers={"X-User-Key": self.key, "User-Agent": USER_AGENT},
        )

    def lease(self) -> Lease:
        """The active account's token, for one run. Raises `LeaseUnavailable`."""
        url = self.base_url + LEASE_PATH
        try:
            r = self._call(LEASE_PATH, {})
        except requests.RequestException as e:
            raise LeaseUnavailable(f"crossposter unreachable at {url}: {type(e).__name__}: {e}") from None
        if r.status_code == 200:
            try:
                body = r.json()
                lease = Lease(str(body["lease_id"]), str(body["account"]), str(body["token"]),
                              str(body["expires_at"]))
            except (ValueError, KeyError, TypeError) as e:
                raise LeaseUnavailable(f"crossposter's lease at {url} was unreadable: {type(e).__name__}") from None
            if not lease.token.strip():
                raise LeaseUnavailable(f"crossposter leased {lease} with an empty token")
            logger.info("leased Claude account %s, expires %s", lease, lease.expires_at)
            return lease
        try:
            detail = r.json()
        except ValueError:
            detail = r.text[:300]
        if isinstance(detail, dict) and "detail" in detail:
            detail = detail["detail"]
        hint = {
            403: " (tenhands' service identity is not on the edge allow list "
                 "crossposter-claude-code-lease: command-station → Service grants)",
            503: " (no Claude Code account can be leased)",
        }.get(r.status_code, "")
        raise LeaseUnavailable(f"crossposter refused a lease: HTTP {r.status_code}{hint}: {detail}",
                               quota_only=r.status_code == 503 and _quota_only(detail))

    def report(self, lease: Lease, outcome: str) -> dict | None:
        """Tell crossposter what the run on `lease` got. Returns its answer
        (`{benched, active, ...}`), or None when the report did not arrive,
        which is logged: the run's own result stands either way."""
        try:
            r = self._call(OUTCOME_PATH, {"lease_id": lease.lease_id, "outcome": outcome})
        except requests.RequestException as e:
            logger.warning("could not report %s on Claude lease %s: %s", outcome, lease, e)
            return None
        if r.status_code != 200:
            logger.warning("crossposter answered HTTP %s to %s on Claude lease %s: %s",
                           r.status_code, outcome, lease, r.text[:200])
            return None
        try:
            answer = r.json()
        except ValueError:
            logger.warning("crossposter's answer to %s on lease %s was not JSON", outcome, lease)
            return None
        if answer.get("benched"):
            logger.warning("Claude account %s benched by crossposter (%s); active now: %s",
                           lease.account, outcome, answer.get("active"))
        return answer


def next_account(answer: dict | None, tried: set[str]) -> str | None:
    """The account crossposter made active after an outcome, if it is one this
    run has not tried yet. None means: stop, there is nowhere else to go."""
    active = (answer or {}).get("active")
    return active if active and active not in tried else None
