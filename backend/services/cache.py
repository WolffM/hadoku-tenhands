"""
VibeDispatch Caching Service

File-based caching for API responses to speed up local development and testing.
Caches are stored in .cache/ directory and persist between server restarts.
"""

import hashlib
import json
import os
import time
from functools import wraps
from typing import Any

from flask import jsonify

# Cache configuration
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache")
DEFAULT_TTL = 300  # 5 minutes default
LOCAL_DEV_TTL = 3600  # 1 hour for local development


def _is_local_dev() -> bool:
    """Check if we're in local development mode (evaluated at runtime)."""
    # LOCAL_CACHE=1 or FLASK_ENV=development enables extended caching
    # Also default to local dev mode if running on localhost (no URL_PREFIX override)
    if os.environ.get("LOCAL_CACHE") == "1":
        return True
    if os.environ.get("FLASK_ENV") == "development":
        return True
    # Default to local dev when URL_PREFIX is not set (running locally)
    if not os.environ.get("URL_PREFIX"):
        return True
    return False


def _is_cache_enabled() -> bool:
    """Check if caching is enabled (evaluated at runtime)."""
    return os.environ.get("CACHE_DISABLED") != "1"

# Legacy module-level cache for vibecheck status (kept for backward compatibility)
_vibecheck_cache: dict[str, bool] = {}
_cache_timestamp = 0


def _ensure_cache_dir():
    """Ensure the cache directory exists."""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)


def _get_cache_path(cache_key: str) -> str:
    """Get the file path for a cache key."""
    # Hash the key to create a safe filename
    key_hash = hashlib.md5(cache_key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{key_hash}.json")


def _get_ttl() -> int:
    """Get the appropriate TTL based on environment."""
    return LOCAL_DEV_TTL if _is_local_dev() else DEFAULT_TTL


def get_cached(cache_key: str, ttl: int | None = None) -> Any | None:
    """
    Get a cached value by key.

    Args:
        cache_key: Unique identifier for the cached data
        ttl: Optional TTL override in seconds

    Returns:
        Cached data if valid, None if expired or not found
    """
    if not _is_cache_enabled():
        return None

    _ensure_cache_dir()
    cache_path = _get_cache_path(cache_key)

    if not os.path.exists(cache_path):
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)

        cached_time = cached.get("timestamp", 0)
        effective_ttl = ttl if ttl is not None else _get_ttl()

        if time.time() - cached_time < effective_ttl:
            print(f"[CACHE] HIT: {cache_key} (TTL: {effective_ttl}s)")
            return cached.get("data")
        else:
            print(f"[CACHE] EXPIRED: {cache_key}")
            return None
    except (json.JSONDecodeError, IOError, KeyError):
        return None


def set_cached(cache_key: str, data: Any) -> None:
    """
    Cache a value with the given key.

    Args:
        cache_key: Unique identifier for the cached data
        data: Data to cache (must be JSON serializable)
    """
    if not _is_cache_enabled():
        return

    _ensure_cache_dir()
    cache_path = _get_cache_path(cache_key)

    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": time.time(),
                "key": cache_key,
                "data": data
            }, f, indent=2)
        print(f"[CACHE] SET: {cache_key} (TTL: {_get_ttl()}s)")
    except (IOError, TypeError) as e:
        print(f"[CACHE] ERROR setting {cache_key}: {e}")


def clear_cache(cache_key: str | None = None) -> int:
    """
    Clear cached data.

    Args:
        cache_key: Specific key to clear, or None to clear all

    Returns:
        Number of cache entries cleared
    """
    _ensure_cache_dir()
    cleared = 0

    if cache_key:
        cache_path = _get_cache_path(cache_key)
        if os.path.exists(cache_path):
            os.remove(cache_path)
            cleared = 1
            print(f"[CACHE] CLEARED: {cache_key}")
    else:
        # Clear all cache files
        for filename in os.listdir(CACHE_DIR):
            if filename.endswith(".json"):
                os.remove(os.path.join(CACHE_DIR, filename))
                cleared += 1
        print(f"[CACHE] CLEARED ALL: {cleared} entries")

    return cleared


def get_cache_stats() -> dict:
    """Get cache statistics."""
    _ensure_cache_dir()

    stats = {
        "enabled": _is_cache_enabled(),
        "local_dev": _is_local_dev(),
        "ttl_seconds": _get_ttl(),
        "cache_dir": CACHE_DIR,
        "entries": 0,
        "total_size_bytes": 0,
        "valid_entries": 0,
        "expired_entries": 0
    }

    if not os.path.exists(CACHE_DIR):
        return stats

    for filename in os.listdir(CACHE_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(CACHE_DIR, filename)
            stats["entries"] += 1
            stats["total_size_bytes"] += os.path.getsize(filepath)

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if time.time() - cached.get("timestamp", 0) < _get_ttl():
                    stats["valid_entries"] += 1
                else:
                    stats["expired_entries"] += 1
            except (json.JSONDecodeError, IOError):
                stats["expired_entries"] += 1

    return stats


# ============ Decorator ============

def cached_endpoint(cache_key):
    """Decorator that adds caching to a Flask route handler.

    The decorated function should return a plain dict.
    The decorator handles cache lookup, storage, and jsonify.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            cached = get_cached(cache_key)
            if cached:
                return jsonify(cached)
            result = fn(*args, **kwargs)
            set_cached(cache_key, result)
            return jsonify(result)
        return wrapper
    return decorator


# ============ Legacy functions for backward compatibility ============

def get_cached_vibecheck_status():
    """Get cached vibecheck status for all repos (legacy function)."""
    global _vibecheck_cache, _cache_timestamp
    if time.time() - _cache_timestamp < DEFAULT_TTL and _vibecheck_cache:
        return _vibecheck_cache
    return None


def set_cached_vibecheck_status(status_dict):
    """Set cached vibecheck status (legacy function)."""
    global _vibecheck_cache, _cache_timestamp
    _vibecheck_cache = status_dict
    _cache_timestamp = time.time()


def clear_vibecheck_cache():
    """Clear the vibecheck cache (legacy function)."""
    global _vibecheck_cache, _cache_timestamp
    _vibecheck_cache = {}
    _cache_timestamp = 0
