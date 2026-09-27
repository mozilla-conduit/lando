import functools
from typing import (
    Callable,
    TypeVar,
)

from django.core.cache import caches

# Generic type representing the content being cached.
T = TypeVar("T")


def cache_method(
    key_fn: Callable[..., str],
    cache_alias: str = "default",
    timeout: int | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Cache the method result using the key function.

    Decorator factory that caches the result of a method using the provided key
    function, in the cache named by `cache_alias`. Callers that invalidate an
    entry must delete it from the same cache.

    When `timeout` is given it is the entry's TTL in seconds; when left as `None`
    the entry is stored with the cache backend's own configured timeout.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            cache = caches[cache_alias]

            # The key function fully determines the cache key, so callers can
            # build the same key to invalidate an entry. Key functions must
            # therefore return a value unique to each cached function.
            key = key_fn(*args, **kwargs)

            if cache.has_key(key):
                return cache.get(key)

            result = func(*args, **kwargs)

            if result is not None:
                # Only forward `timeout` when set, so the backend default applies
                # otherwise (passing `None` to `cache.set` means "cache forever").
                if timeout is None:
                    cache.set(key, result)
                else:
                    cache.set(key, result, timeout)

            return result

        return wrapper

    return decorator
