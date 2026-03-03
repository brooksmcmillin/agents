"""Unit tests for MemoryCache in database_memory_store.py."""

from unittest.mock import patch

from agent_framework.storage.database_memory_store import (
    ALL_MEMORIES_CACHE_TTL,
    DEFAULT_CACHE_TTL,
    MemoryCache,
)
from agent_framework.storage.memory_store import Memory


def make_memory(key: str = "test_key", value: str = "test_value") -> Memory:
    """Create a Memory instance for testing."""
    return Memory(key=key, value=value)


class TestMemoryCacheInit:
    """Tests for MemoryCache initialization."""

    def test_default_ttl(self) -> None:
        """Default TTL should match the module constant."""
        cache = MemoryCache()
        assert cache._default_ttl == DEFAULT_CACHE_TTL

    def test_custom_ttl(self) -> None:
        """Custom TTL should be stored correctly."""
        cache = MemoryCache(default_ttl=42.0)
        assert cache._default_ttl == 42.0

    def test_starts_empty(self) -> None:
        """Cache should start with no entries."""
        cache = MemoryCache()
        assert cache._cache == {}
        assert cache._all_memories_cache is None

    def test_all_memories_ttl(self) -> None:
        """all_memories TTL should match the module constant."""
        cache = MemoryCache()
        assert cache._all_memories_ttl == ALL_MEMORIES_CACHE_TTL


class TestMemoryCacheGetSet:
    """Tests for cache get and set operations."""

    def test_cache_miss_unknown_key(self) -> None:
        """Getting an unknown key returns None."""
        cache = MemoryCache()
        assert cache.get("nonexistent") is None

    def test_cache_hit_before_ttl(self) -> None:
        """Getting a key that was just set returns the cached memory."""
        cache = MemoryCache()
        memory = make_memory()
        cache.set("k", memory)
        result = cache.get("k")
        assert result is memory

    def test_set_overwrites_existing_key(self) -> None:
        """Setting a key again replaces the previous value."""
        cache = MemoryCache()
        m1 = make_memory(value="first")
        m2 = make_memory(value="second")
        cache.set("k", m1)
        cache.set("k", m2)
        assert cache.get("k") is m2

    def test_custom_ttl_per_entry(self) -> None:
        """A per-entry TTL overrides the default."""
        cache = MemoryCache(default_ttl=9999.0)
        memory = make_memory()
        # Set with a very short custom TTL
        with patch("time.time", return_value=1000.0):
            cache.set("k", memory, ttl=1.0)
        # Just after expiry
        with patch("time.time", return_value=1001.1):
            assert cache.get("k") is None

    def test_default_ttl_used_when_not_specified(self) -> None:
        """When no per-entry TTL is given, the default TTL is used."""
        cache = MemoryCache(default_ttl=10.0)
        memory = make_memory()
        with patch("time.time", return_value=1000.0):
            cache.set("k", memory)
        # Halfway through TTL: still valid
        with patch("time.time", return_value=1005.0):
            assert cache.get("k") is memory
        # Just after TTL ends: expired
        with patch("time.time", return_value=1010.1):
            assert cache.get("k") is None

    def test_multiple_keys_independent(self) -> None:
        """Different keys are cached independently."""
        cache = MemoryCache()
        m1 = make_memory(key="a", value="1")
        m2 = make_memory(key="b", value="2")
        cache.set("a", m1)
        cache.set("b", m2)
        assert cache.get("a") is m1
        assert cache.get("b") is m2


class TestMemoryCacheExpiry:
    """Tests for TTL-based cache expiry."""

    def test_expired_entry_returns_none(self) -> None:
        """An entry past its TTL should not be returned."""
        cache = MemoryCache()
        with patch("time.time", return_value=1000.0):
            cache.set("k", make_memory(), ttl=1.0)
        with patch("time.time", return_value=1001.1):
            assert cache.get("k") is None

    def test_expired_entry_is_removed_from_internal_cache(self) -> None:
        """Reading an expired key should evict it from the internal dict."""
        cache = MemoryCache()
        memory = make_memory()
        with patch("time.time", return_value=1000.0):
            cache.set("k", memory, ttl=1.0)
        # Trigger get past expiry, which should delete the entry
        with patch("time.time", return_value=1002.0):
            result = cache.get("k")
        assert result is None
        assert "k" not in cache._cache

    def test_entry_valid_at_exact_expiry_boundary(self) -> None:
        """An entry is still valid if time.time() == expiry (strictly less-than check)."""
        cache = MemoryCache()
        memory = make_memory()
        with patch("time.time", return_value=1000.0):
            cache.set("k", memory, ttl=5.0)
        # Expiry is at 1005.0; at exactly 1004.9 it should still be valid
        with patch("time.time", return_value=1004.9):
            assert cache.get("k") is memory
        # At exactly 1005.0 the condition is time() < expiry => False, so expired
        with patch("time.time", return_value=1005.0):
            assert cache.get("k") is None

    def test_zero_ttl_expires_immediately(self) -> None:
        """A TTL of 0 means the entry expires as soon as time advances at all."""
        cache = MemoryCache()
        memory = make_memory()
        with patch("time.time", return_value=1000.0):
            cache.set("k", memory, ttl=0.0)
        with patch("time.time", return_value=1000.0):
            # Same instant: expiry == 1000.0, time() < expiry is False → expired
            assert cache.get("k") is None


class TestMemoryCacheInvalidation:
    """Tests for cache invalidation and deletion."""

    def test_delete_removes_entry(self) -> None:
        """delete() should remove the key from cache."""
        cache = MemoryCache()
        cache.set("k", make_memory())
        cache.delete("k")
        assert cache.get("k") is None

    def test_delete_nonexistent_key_is_safe(self) -> None:
        """Deleting a key that doesn't exist should not raise."""
        cache = MemoryCache()
        cache.delete("no_such_key")  # must not raise

    def test_delete_invalidates_all_memories_cache(self) -> None:
        """delete() always invalidates the all-memories cache, even for present keys."""
        cache = MemoryCache()
        memory = make_memory(key="k")
        cache.set("k", memory)
        cache.set_all_memories([memory])
        assert cache.get_all_memories() is not None
        cache.delete("k")
        assert cache.get("k") is None
        assert cache.get_all_memories() is None

    def test_delete_nonexistent_key_also_invalidates_all_memories_cache(self) -> None:
        """delete() of a non-present key still invalidates the all-memories cache."""
        cache = MemoryCache()
        cache.set_all_memories([make_memory()])
        assert cache.get_all_memories() is not None
        cache.delete("never_set")
        assert cache.get_all_memories() is None

    def test_invalidate_is_alias_for_delete(self) -> None:
        """invalidate() should behave identically to delete()."""
        cache = MemoryCache()
        cache.set("k", make_memory())
        cache.set_all_memories([make_memory()])
        cache.invalidate("k")
        assert cache.get("k") is None
        assert cache.get_all_memories() is None

    def test_clear_removes_all_entries(self) -> None:
        """clear() should empty the individual cache and the all-memories cache."""
        cache = MemoryCache()
        cache.set("a", make_memory(key="a"))
        cache.set("b", make_memory(key="b"))
        cache.set_all_memories([make_memory()])
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None
        assert cache.get_all_memories() is None
        assert cache._cache == {}
        assert cache._all_memories_cache is None

    def test_clear_on_empty_cache_is_safe(self) -> None:
        """clear() on an already-empty cache should not raise."""
        cache = MemoryCache()
        cache.clear()  # must not raise


class TestAllMemoriesCache:
    """Tests for the all-memories list cache."""

    def test_get_all_memories_miss_when_empty(self) -> None:
        """get_all_memories() returns None when nothing has been cached."""
        cache = MemoryCache()
        assert cache.get_all_memories() is None

    def test_set_and_get_all_memories_hit(self) -> None:
        """set_all_memories / get_all_memories round-trip before TTL."""
        cache = MemoryCache()
        memories = [make_memory(key="a"), make_memory(key="b")]
        cache.set_all_memories(memories)
        result = cache.get_all_memories()
        assert result is memories

    def test_all_memories_cache_expires_after_ttl(self) -> None:
        """The all-memories cache should expire after ALL_MEMORIES_CACHE_TTL seconds."""
        cache = MemoryCache()
        with patch("time.time", return_value=1000.0):
            cache.set_all_memories([make_memory()])
        # Just before expiry
        with patch("time.time", return_value=1000.0 + ALL_MEMORIES_CACHE_TTL - 1):
            assert cache.get_all_memories() is not None
        # Just after expiry
        with patch("time.time", return_value=1000.0 + ALL_MEMORIES_CACHE_TTL + 1):
            assert cache.get_all_memories() is None

    def test_all_memories_cache_cleared_on_expiry(self) -> None:
        """After expiry, _all_memories_cache should be set to None."""
        cache = MemoryCache()
        with patch("time.time", return_value=1000.0):
            cache.set_all_memories([make_memory()])
        with patch("time.time", return_value=1000.0 + ALL_MEMORIES_CACHE_TTL + 1):
            cache.get_all_memories()
        assert cache._all_memories_cache is None

    def test_set_all_memories_overwrites_previous(self) -> None:
        """set_all_memories() replaces any existing all-memories cache."""
        cache = MemoryCache()
        first = [make_memory(key="first")]
        second = [make_memory(key="second")]
        cache.set_all_memories(first)
        cache.set_all_memories(second)
        assert cache.get_all_memories() is second

    def test_set_all_memories_with_empty_list(self) -> None:
        """An empty list is a valid value to cache."""
        cache = MemoryCache()
        cache.set_all_memories([])
        result = cache.get_all_memories()
        assert result == []

    def test_invalidate_all_memories_clears_list_cache(self) -> None:
        """_invalidate_all_memories() should set _all_memories_cache to None."""
        cache = MemoryCache()
        cache.set_all_memories([make_memory()])
        cache._invalidate_all_memories()
        assert cache._all_memories_cache is None
