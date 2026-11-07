"""Resolve a hadoku ``X-User-Key`` to a tier via ``/session/whoami``.

TenHands is a Flask app behind the ``dispatch.hadoku.me`` cloudflared tunnel.
Its dashboard calls the API **directly** at the tunnel origin (cross-origin
from ``hadoku.me/tenhands``), so requests do not carry a trustworthy
``X-Edge-Auth`` stamp — the edge-stamp pattern used by the CF Workers doesn't
apply. Instead we **delegate**, exactly like the other tunnel backends
(``hadoku-scraper``, ``hadoku-dataplatform``, ``hadoku-watchparty``): take whatever
``X-User-Key`` is present and ask the platform's authoritative whoami endpoint
what tier it represents. This works on ANY inbound path — service keys aren't
self-describing, and TenHands holds no key arrays of its own.

Cached per key for ``CACHE_TTL_S`` (a minute) so a request burst from one
caller doesn't trigger a whoami round-trip per request, but a revoked or
re-tiered key stops working quickly. A whoami failure (network error, non-200,
malformed JSON) resolves to ``public`` and is **not** cached — so a flapping
whoami recovers on the next call instead of pinning the caller at public for a
minute.

Every lookup also asks whether the key is on ``tenhands-write``, the access
list this server checks itself (hadoku_site
``workers/edge-router/src/access-lists.ts``, ``checkedBy``): service tier is
every service key in the fleet, and the list names who may operate the
pipeline. Membership rides the same cached call.

For hermetic tests, setting the ``WHOAMI_TEST_OVERRIDES`` env var to a JSON
map short-circuits the network entirely. A value is a tier (a caller on the
list) or ``{"tier": t, "member": false}`` (one that is not). Production never
sets this. Ported from ``hadoku_scrape/api/middleware/whoami.py``.
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
# The app-checked access list whoami answers membership of. Managed by name
# from hadoku_site: `python3 scripts/administration.py access-list add
# tenhands-write <name>`.
WRITE_LIST = "tenhands-write"
CACHE_TTL_S = 60.0
CACHE_PRUNE_THRESHOLD = 256
REQUEST_TIMEOUT_S = 5.0

# The hadoku tier ladder, LOW to HIGH. Mirrors TIER_RANK in
# @wolffm/worker-utils, which this runtime cannot import.
#
# A tier missing here is NOT rejected loudly — `_classify` below rewrites it to
# "public", so the caller authenticates at the edge and then silently receives
# the anonymous view: no 401, no 403, no log line. `wife` (2026-08-04) ranks
# above service and was exactly that case, and `member` (2026-10-28) was
# another. Keep it complete.
_VALID_TIERS = ("admin", "wife", "service", "friend", "member", "public")

# key → ((tier, on WRITE_LIST), expiry)
_cache: dict[str, tuple[tuple[str, bool], float]] = {}
_cache_lock = Lock()


def tier_rank(tier: str) -> int:
    """Privilege rank for a tier: higher = more privileged.

    admin=5, wife=4, service=3, friend=2, member=1, public=0. An unknown tier
    ranks as public (0) — the same fail-closed default `_classify` applies, so
    a tier the ladder doesn't know can never out-rank a real one.
    """
    try:
        return len(_VALID_TIERS) - 1 - _VALID_TIERS.index(tier)
    except ValueError:
        return 0


def assert_floor(tier: str) -> str:
    """A tier floor used as a gate's requirement must be a real, non-public
    tier this build knows about.

    `tier_rank` ranks an unknown name — or a typo — the same as ``public``
    (0), so a floor value that isn't a recognised, above-public tier would
    silently fail open rather than raise. Call this at import time for any
    hardcoded floor constant, so a future edit to the ladder or the constant
    is caught at boot rather than discovered later.
    """
    if tier == "public" or tier not in _VALID_TIERS:
        known = ", ".join(t for t in _VALID_TIERS if t != "public")
        raise ValueError(f"{tier!r} is not a tier floor this build knows (one of {known})")
    return tier


def _get_test_overrides() -> dict[str, tuple[str, bool]] | None:
    raw = os.environ.get("WHOAMI_TEST_OVERRIDES")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    out: dict[str, tuple[str, bool]] = {}
    for k, v in parsed.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, str) and v in _VALID_TIERS:
            out[k] = (v, True)
        elif isinstance(v, dict) and v.get("tier") in _VALID_TIERS:
            out[k] = (v["tier"], v.get("member") is True)
    return out


def _fetch_from_whoami(key: str) -> tuple[str, bool] | None:
    """One-shot HTTP call. Returns (tier, on WRITE_LIST), ``("public", False)``
    when whoami explicitly says the key is invalid, or ``None`` on any transient
    failure (caller should treat as public-but-don't-cache so the next call
    retries)."""
    req = urllib.request.Request(
        f"{WHOAMI_URL}?list={WRITE_LIST}",
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
        return ("public", False)
    user_type = data.get("userType")
    tier = user_type if user_type in _VALID_TIERS else "public"
    listed = data.get("list")
    member = (
        isinstance(listed, dict)
        and listed.get("id") == WRITE_LIST
        and listed.get("member") is True
    )
    return (tier, member)


def _prune_expired(now: float) -> None:
    expired = [k for k, (_, exp) in _cache.items() if exp <= now]
    for k in expired:
        _cache.pop(k, None)


def resolve_caller(key: str | None) -> tuple[str, bool]:
    """Classify a raw ``X-User-Key``: (tier, on ``tenhands-write``). Empty or
    missing key → ``("public", False)``."""
    if not key:
        return ("public", False)

    overrides = _get_test_overrides()
    if overrides is not None:
        return overrides.get(key, ("public", False))

    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            caller, expires_at = hit
            if expires_at > now:
                return caller

    fetched = _fetch_from_whoami(key)
    if fetched is None:
        return ("public", False)

    with _cache_lock:
        _cache[key] = (fetched, now + CACHE_TTL_S)
        if len(_cache) > CACHE_PRUNE_THRESHOLD:
            _prune_expired(now)

    return fetched


def clear_cache() -> None:
    """Drop all cached tier results. For tests."""
    with _cache_lock:
        _cache.clear()


def resolve_tier_from_key(key: str | None) -> str:
    """Classify a raw ``X-User-Key`` by tier alone. Empty/missing key → ``public``."""
    return resolve_caller(key)[0]
