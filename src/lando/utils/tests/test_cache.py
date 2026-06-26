import pytest
from django.core.cache import cache
from django.test import override_settings

from lando.utils.cache import cache_method


def sample_cache_key(name: str) -> str:
    return f"test-cache-{name}"


# Enable the local memory cache since we use the dummy cache in tests.
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "test-cache",
        }
    }
)
@pytest.mark.django_db
def test_cache_method():
    call_counter = {"count": 0}

    @cache_method(sample_cache_key)
    def expensive_function(name: str) -> str:
        call_counter["count"] += 1
        return f"Hello, {name}!"

    cache.clear()

    # First call should compute and cache
    result1 = expensive_function("Alice")
    assert result1 == "Hello, Alice!"
    assert call_counter["count"] == 1

    # Second call should return cached result (not increment counter)
    result2 = expensive_function("Alice")
    assert result2 == "Hello, Alice!"
    assert call_counter["count"] == 1  # Confirm it did NOT call again

    # A new argument should trigger a cache miss
    result3 = expensive_function("Bob")
    assert result3 == "Hello, Bob!"
    assert call_counter["count"] == 2

    # Confirm the cache is keyed purely on the key function's output.
    assert cache.get("test-cache-Alice") == "Hello, Alice!", (
        "The cached value should be stored under the key function's output."
    )
    assert cache.get("test-cache-Bob") == "Hello, Bob!", (
        "The cached value should be stored under the key function's output."
    )
