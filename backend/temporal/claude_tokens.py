"""A pool of Claude subscription OAuth tokens, used in turn.

Every `claude` subprocess tenhands spawns (taskauto's agent, the crimson-kitty
judge) needs a `CLAUDE_CODE_OAUTH_TOKEN`. With one token, one account hitting
its 5-hour or weekly limit — or one revoked token — stops the pipeline until a
human steps in. On 2026-11-14 a dead token stopped taskauto for a day while two
other subscriptions sat idle. So the token is chosen per run from a pool:

* **Where tokens come from.** Every `CLAUDE_OAUTH_TOKEN_<ACCOUNT>` in the
  environment (the vault naming `claude-oauth-helper` already uses, one item per
  subscription, minted with `claude setup-token`), then the single legacy
  `CLAUDE_CODE_OAUTH_TOKEN` if it is set, under the label `default`. A value that
  appears under two names is used once.
* **Choosing.** The first token, in that order, that is not benched.
* **Benching.** A run whose output says the account is out of quota benches
  that token until the reset time the CLI printed (30 minutes when it printed
  none; 5 minutes for a bare 429). A run rejected for authentication benches it
  for `AUTH_BENCH_S` and sends one notification for that token, because a
  revoked token never comes back by waiting. Anything else is the task's
  problem, not the token's, and benches nothing.
* **Memory.** Benches live in a small JSON file (`TASKAUTO_TOKEN_STATE`,
  default `~/.taskauto/claude-tokens.json`), keyed by a fingerprint of the
  token, so the one-shot taskauto process and the long-lived judge worker share
  what they learnt, and a rotated token starts with a clean slate. Losing a
  write to a concurrent writer costs one extra failed call, nothing more.

Token values never appear in logs, exceptions, notifications or the state
file; a token is identified by its label and fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

PREFIX = "CLAUDE_OAUTH_TOKEN_"
LEGACY = "CLAUDE_CODE_OAUTH_TOKEN"

QUOTA = "quota"
AUTH = "auth"

#: How long a quota bench lasts when the CLI did not say when the limit lifts.
QUOTA_FALLBACK_S = 30 * 60
#: A bare 429 with no "limit" wording is a short rate limit, not a used-up plan.
RATE_LIMIT_S = 5 * 60
#: An auth failure does not heal on its own. Re-test it now and then so a token
#: re-authorised in place is picked up again without a restart.
AUTH_BENCH_S = 6 * 3600
#: No reset the CLI could print is further away than a week; anything parsed
#: past this is a misparse, and the fallback is safer.
MAX_BENCH_S = 8 * 24 * 3600


def _default_state_path() -> Path:
    override = os.environ.get("TASKAUTO_TOKEN_STATE")
    return Path(override) if override else Path.home() / ".taskauto" / "claude-tokens.json"


@dataclass(frozen=True)
class Token:
    label: str
    value: str = field(repr=False)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.value.encode()).hexdigest()[:12]

    def __str__(self) -> str:
        return f"{self.label} ({self.fingerprint})"


def load_tokens(env: Mapping[str, str] | None = None) -> list[Token]:
    """Every configured token, in the order they are tried."""
    env = os.environ if env is None else env
    named = sorted(
        (k[len(PREFIX):].lower(), v.strip())
        for k, v in env.items()
        if k.startswith(PREFIX) and len(k) > len(PREFIX) and v and v.strip()
    )
    legacy = (env.get(LEGACY) or "").strip()
    if legacy:
        named.append(("default", legacy))
    seen: set[str] = set()
    tokens = []
    for label, value in named:
        if value in seen:
            continue
        seen.add(value)
        tokens.append(Token(label, value))
    return tokens


# ── reading the CLI's failure text ────────────────────────────────────────

# The CLI's own wording when the account, not the code, is the problem:
#   "You've hit your weekly limit · resets Nov 6, 3pm (America/Los_Angeles)"
#   "5-hour limit reached ∙ resets 3pm"
#   "Claude AI usage limit reached|1762470000"
#   "API Error: 429 {... "type":"rate_limit_error" ...}"
# Deliberately narrow: "Credit balance is too low" or an empty answer are
# things to go fix, and must not bench a token that is fine.
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
        return at if now < at <= now + MAX_BENCH_S else None
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
    return epoch if epoch <= now + MAX_BENCH_S else None


@dataclass(frozen=True)
class Bench:
    kind: str
    until: float
    detail: str


def classify(text: str, now: float) -> Bench | None:
    """Is this failure the token's fault? If so, for how long."""
    if not text:
        return None
    # The CLI's own error is its last word; an agent's long transcript ahead of
    # it can mention "rate limit" or a 401 in the task it was working on.
    text = text[-2000:]
    detail = text.strip()[-300:]
    if QUOTA_RE.search(text):
        reset = parse_reset(text, now)
        if reset is None:
            reset = now + (QUOTA_FALLBACK_S if _PLAN_LIMIT_RE.search(text) else RATE_LIMIT_S)
        return Bench(QUOTA, reset, detail)
    if AUTH_RE.search(text):
        return Bench(AUTH, now + AUTH_BENCH_S, detail)
    return None


# ── the pool ──────────────────────────────────────────────────────────────


class PoolExhausted(RuntimeError):
    """Every configured token is benched."""

    def __init__(self, message: str, *, quota_only: bool, earliest: float | None):
        super().__init__(message)
        self.quota_only = quota_only
        self.earliest = earliest


def _default_notify(title: str, description: str) -> None:
    from helpers.notifications import COLOR_ERROR, send_discord_notification
    send_discord_notification(title, description, COLOR_ERROR)


_lock = threading.Lock()


class TokenPool:
    def __init__(self, tokens: list[Token], *, state_path: Path | None = None,
                 now: Callable[[], float] = time.time,
                 notify: Callable[[str, str], None] | None = None):
        self.tokens = tokens
        self.state_path = state_path or _default_state_path()
        self.now = now
        self.notify = notify or _default_notify

    # state file

    def _read(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            logger.warning("token bench file %s unreadable (%s); starting empty",
                           self.state_path, e)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.state_path.parent, prefix=".claude-tokens.")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=1, sort_keys=True)
            os.replace(tmp, self.state_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _benches(self) -> dict[str, Bench]:
        now = self.now()
        out = {}
        for fp, row in self._read().items():
            try:
                b = Bench(row["kind"], float(row["until"]), row.get("detail", ""))
            except (KeyError, TypeError, ValueError):
                continue
            if b.until > now:
                out[fp] = b
        return out

    # public

    def available(self) -> list[Token]:
        """Tokens to try, in order. Raises PoolExhausted when every one is benched.

        An empty pool returns []: there is nothing to choose, and the caller
        runs once with whatever its environment holds, so the CLI reports the
        missing credential in its own words.
        """
        if not self.tokens:
            return []
        benches = self._benches()
        free = [t for t in self.tokens if t.fingerprint not in benches]
        if free:
            return free
        held = [benches[t.fingerprint] for t in self.tokens]
        parts = [
            f"{t.label}: {b.kind} until "
            f"{datetime.fromtimestamp(b.until).astimezone().isoformat(timespec='minutes')}"
            for t, b in zip(self.tokens, held)
        ]
        raise PoolExhausted(
            "every Claude token is benched — " + "; ".join(parts),
            quota_only=all(b.kind == QUOTA for b in held),
            earliest=min(b.until for b in held),
        )

    def bench_if_token_problem(self, token: Token | None, failure_text: str) -> Bench | None:
        """Bench `token` if `failure_text` is its fault. Returns the bench, or None."""
        if token is None:
            return None
        bench = classify(failure_text, self.now())
        if bench is None:
            return None
        with _lock:
            data = self._read()
            previous = data.get(token.fingerprint, {})
            data[token.fingerprint] = {"label": token.label, "kind": bench.kind,
                                       "until": bench.until, "detail": bench.detail}
            self._write(data)
        logger.warning("Claude token %s benched (%s) until %s: %s", token, bench.kind,
                       datetime.fromtimestamp(bench.until).astimezone().isoformat(timespec="minutes"),
                       bench.detail[:200])
        if bench.kind == AUTH and previous.get("kind") != AUTH:
            try:
                self.notify(
                    f"Claude token `{token.label}` rejected",
                    f"tenhands benched Claude OAuth token `{token.label}` "
                    f"({token.fingerprint}) after an authentication failure and is "
                    f"carrying on with the others. Replace it: `rotate-secret "
                    f"{PREFIX}{token.label.upper()}`.\n\n> {bench.detail[:300]}",
                )
            except Exception:
                logger.exception("could not send the rejected-token notification")
        return bench

    def status(self) -> list[dict]:
        """Each token's label, fingerprint and bench, for diagnostics. No values."""
        benches = self._benches()
        rows = []
        for t in self.tokens:
            b = benches.get(t.fingerprint)
            rows.append({
                "label": t.label,
                "fingerprint": t.fingerprint,
                "benched": b.kind if b else None,
                "benched_until": (datetime.fromtimestamp(b.until).astimezone()
                                  .isoformat(timespec="minutes") if b else None),
            })
        return rows


def default_pool() -> TokenPool:
    """The pool as the environment configures it right now."""
    return TokenPool(load_tokens())
