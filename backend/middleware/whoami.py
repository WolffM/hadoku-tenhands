"""Resolve a hadoku ``X-User-Key`` to a tier via ``/session/whoami``.

TenHands is a Flask app behind the ``dispatch.hadoku.me`` cloudflared tunnel.
Its dashboard calls the API **directly** at the tunnel origin (cross-origin
from ``hadoku.me/tenhands``), so requests do not carry a trustworthy
``X-Edge-Auth`` stamp — the edge-stamp pattern used by the CF Workers doesn't
apply. Instead we **delegate**, exactly like the other tunnel backends
(``hadoku-scrape``, ``personal-dataplatform``, ``watchpart2``): take whatever
``X-User-Key`` is present and ask the platform's authoritative whoami endpoint
what tier it represents. This works on ANY inbound path — service keys aren't
self-describing, and TenHands holds no key arrays of its own.

Cached per key for ``CACHE_TTL_S`` (a minute) so a request burst from one
caller doesn't trigger a whoami round-trip per request, but a revoked or
re-tiered key stops working quickly. A whoami failure (network error, non-200,
malformed JSON) resolves to ``public`` and is **not** cached — so a flapping
whoami recovers on the next call instead of pinning the caller at public for a
minute.

For hermetic tests, setting the ``WHOAMI_TEST_OVERRIDES`` env var to a JSON
``{key: tier}`` map short-circuits the network entirely. Production never sets
this. Ported from ``hadoku_scrape/api/middleware/whoami.py``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from threading import Lock

WHOAMI_URL = os.environ.get("TENHANDS_WHOAMI_URL", "https://hadoku.me/session/whoami")
# Cloudflare's bot detection blocks the default Python-urllib UA with 1010,
# which would silently demote every authenticated caller to public. Identify
# ourselves honestly so we both get through the filter and stay greppable in
# the access logs.
USER_AGENT = "hadoku-tenhands/1.0 (+https://hadoku.me/tenhands)"
CACHE_TTL_S = 60.0
CACHE_PRUNE_THRESHOLD = 256
REQUEST_TIMEOUT_S = 5.0

# The hadoku tier ladder, LOW to HIGH. Mirrors TIER_RANK in
# @wolffm/worker-utils, which this runtime cannot import.
#
# A tier missing here is NOT rejected loudly — `_classify` below rewrites it to
# "public", so the caller authenticates at the edge and then silently receives
# the anonymous view: no 401, no 403, no log line. `wife` (2026-08-04) ranks
# above service and was exactly that case. Keep it complete.
_VALID_TIERS = ("admin", "wife", "service", "friend", "public")

_cache: dict[str, tuple[str, float]] = {}
_cache_lock = Lock()


def tier_rank(tier: str) -> int:
    """Privilege rank for a tier: higher = more privileged.

    admin=4, wife=3, service=2, friend=1, public=0. An unknown tier ranks as
    public (0) — the same fail-closed default `_classify` applies, so a tier the
    ladder doesn't know can never out-rank a real one.
    """
    try:
        return len(_VALID_TIERS) - 1 - _VALID_TIERS.index(tier)
    except ValueError:
        return 0


def _get_test_overrides() -> dict[str, str] | None:
    raw = os.environ.get("WHOAMI_TEST_OVERRIDES")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return {
        k: v
        for k, v in parsed.items()
        if isinstance(k, str) and isinstance(v, str) and v in _VALID_TIERS
    }


def _fetch_tier_from_whoami(key: str) -> str | None:
    """One-shot HTTP call. Returns the resolved tier, ``public`` when whoami
    explicitly says the key is invalid, or ``None`` on any transient failure
    (caller should treat as public-but-don't-cache so the next call retries)."""
    req = urllib.request.Request(
        WHOAMI_URL,
        headers={"X-User-Key": key, "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as r:
            if r.status != 200:
                return None
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("valid"):
        return "public"
    user_type = data.get("userType")
    return user_type if user_type in _VALID_TIERS else "public"


def _prune_expired(now: float) -> None:
    expired = [k for k, (_, exp) in _cache.items() if exp <= now]
    for k in expired:
        _cache.pop(k, None)


def resolve_tier_from_key(key: str | None) -> str:
    """Classify a raw ``X-User-Key``. Empty/missing key → ``public``."""
    if not key:
        return "public"

    overrides = _get_test_overrides()
    if overrides is not None:
        return overrides.get(key, "public")

    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            tier, expires_at = hit
            if expires_at > now:
                return tier

    fetched = _fetch_tier_from_whoami(key)
    if fetched is None:
        return "public"

    with _cache_lock:
        _cache[key] = (fetched, now + CACHE_TTL_S)
        if len(_cache) > CACHE_PRUNE_THRESHOLD:
            _prune_expired(now)

    return fetched


def clear_cache() -> None:
    """Drop all cached tier results. For tests."""
    with _cache_lock:
        _cache.clear()
