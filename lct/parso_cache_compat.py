"""Compatibility for Parso 0.8.7's file-cache insertion timestamp.

Parso initializes ``last_used`` from the source mtime, including for a newly
parsed file, and restores that old value from disk. At its 600-entry cleanup
threshold it can immediately evict a tree that Jedi still references. Only
the insertion's usage timestamp needs correcting; ``change_time`` remains the
source validity marker and Parso's own eviction remains enabled.
"""

from functools import wraps
from threading import Lock

import parso
from parso import cache

_install_lock = Lock()


def ensure_parso_cache_timestamps():
    """Refresh usage on cache insertion for the exact supported Parso API."""
    if parso.__version__ != "0.8.7":
        raise RuntimeError("Parso cache compatibility requires parso==0.8.7")

    with _install_lock:
        original = cache._set_cache_item
        if getattr(original, "_lct_refreshes_last_used", False):
            return

        @wraps(original)
        def insert_with_current_usage(hashed_grammar, path, module_cache_item):
            module_cache_item.last_used = cache.time.time()
            return original(hashed_grammar, path, module_cache_item)

        insert_with_current_usage._lct_refreshes_last_used = True
        cache._set_cache_item = insert_with_current_usage
