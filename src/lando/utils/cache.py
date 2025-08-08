import functools
from typing import (
    Callable,
    TypeVar,
)

from django.core.cache import cache

# Generic type representing the content being cached.
T = TypeVar("T")


def django_cache_method(
    key_fn: Callable[..., str],
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator factory that caches the result of a method using the provided key function."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            key = key_fn(*args, **kwargs)

            if cache.has_key(key):  # noqa: W601
                return cache.get(key)

            result = func(*args, **kwargs)

            if result is not None:
                cache.set(key, result)

            return result

        return wrapper

    return decorator
