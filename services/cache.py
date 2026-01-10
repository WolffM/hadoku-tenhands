"""
VibeDispatch Caching Service
"""

import time

# Module-level cache storage
_vibecheck_cache: dict[str, bool] = {}
_cache_timestamp = 0
CACHE_TTL = 300  # 5 minutes


def get_cached_vibecheck_status():
    """Get cached vibecheck status for all repos."""
    global _vibecheck_cache, _cache_timestamp
    if time.time() - _cache_timestamp < CACHE_TTL and _vibecheck_cache:
        return _vibecheck_cache
    return None


def set_cached_vibecheck_status(status_dict):
    """Set cached vibecheck status."""
    global _vibecheck_cache, _cache_timestamp
    _vibecheck_cache = status_dict
    _cache_timestamp = time.time()


def clear_vibecheck_cache():
    """Clear the vibecheck cache."""
    global _vibecheck_cache, _cache_timestamp
    _vibecheck_cache = {}
    _cache_timestamp = 0
