import functools
import json
import time


def ttl_cache(seconds: int):
    """Tiny in-memory TTL cache for async functions (None results are not cached)."""
    def deco(fn):
        store = {}

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            key = json.dumps([args, kwargs], default=str, sort_keys=True)
            hit = store.get(key)
            if hit and time.time() - hit[0] < seconds:
                return hit[1]
            val = await fn(*args, **kwargs)
            if val is not None:
                if len(store) > 500:
                    store.clear()
                store[key] = (time.time(), val)
            return val
        return wrapper
    return deco
