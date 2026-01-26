"""Tests for the MemoryStore class."""

from pathlib import Path

import pytest

from agent_framework.storage.memory_store import Memory, MemoryStore


class TestMemory:
    """Tests for the Memory model."""

    def test_memory_creation(self):
        """Test creating a Memory with required fields."""
        memory = Memory(key="test_key", value="test_value")
        assert memory.key == "test_key"
        assert memory.value == "test_value"
        assert memory.category is None
        assert memory.tags == []
        assert memory.importance == 5

    def test_memory_with_optional_fields(self):
        """Test creating a Memory with all fields."""
        memory = Memory(
            key="test_key",
            value="test_value",
            category="user_preference",
            tags=["tag1", "tag2"],
            importance=8,
        )
        assert memory.category == "user_preference"
        assert memory.tags == ["tag1", "tag2"]
        assert memory.importance == 8

    def test_memory_to_dict_and_from_dict(self):
        """Test serialization round-trip."""
        original = Memory(
            key="test_key",
            value="test_value",
            category="fact",
            tags=["important"],
            importance=7,
        )
        data = original.to_dict()
        restored = Memory.from_dict(data)

        assert restored.key == original.key
        assert restored.value == original.value
        assert restored.category == original.category
        assert restored.tags == original.tags
        assert restored.importance == original.importance


class TestMemoryStore:
    """Tests for the MemoryStore class."""

    @pytest.fixture
    def temp_store(self, tmp_path: Path) -> MemoryStore:
        """Create a temporary MemoryStore for testing."""
        return MemoryStore(storage_path=tmp_path / "memories")

    def test_save_and_get_memory(self, temp_store: MemoryStore):
        """Test saving and retrieving a memory."""
        temp_store.save_memory(
            key="user_name",
            value="Alice",
            category="user_preference",
            importance=8,
        )

        memory = temp_store.get_memory("user_name")
        assert memory is not None
        assert memory.value == "Alice"
        assert memory.category == "user_preference"
        assert memory.importance == 8

    def test_get_nonexistent_memory(self, temp_store: MemoryStore):
        """Test getting a memory that doesn't exist."""
        memory = temp_store.get_memory("nonexistent")
        assert memory is None

    def test_update_memory(self, temp_store: MemoryStore):
        """Test updating an existing memory."""
        temp_store.save_memory(key="counter", value="1")
        temp_store.save_memory(key="counter", value="2")

        memory = temp_store.get_memory("counter")
        assert memory is not None
        assert memory.value == "2"
        assert memory.created_at < memory.updated_at

    def test_get_all_memories(self, temp_store: MemoryStore):
        """Test retrieving all memories."""
        temp_store.save_memory(key="a", value="1", importance=5)
        temp_store.save_memory(key="b", value="2", importance=8)
        temp_store.save_memory(key="c", value="3", importance=3)

        memories = temp_store.get_all_memories()
        assert len(memories) == 3
        # Should be sorted by importance (high to low)
        assert memories[0].key == "b"
        assert memories[1].key == "a"
        assert memories[2].key == "c"

    def test_filter_by_category(self, temp_store: MemoryStore):
        """Test filtering memories by category."""
        temp_store.save_memory(key="a", value="1", category="fact")
        temp_store.save_memory(key="b", value="2", category="goal")
        temp_store.save_memory(key="c", value="3", category="fact")

        facts = temp_store.get_all_memories(category="fact")
        assert len(facts) == 2
        assert all(m.category == "fact" for m in facts)

    def test_filter_by_tags(self, temp_store: MemoryStore):
        """Test filtering memories by tags."""
        temp_store.save_memory(key="a", value="1", tags=["seo", "blog"])
        temp_store.save_memory(key="b", value="2", tags=["twitter"])
        temp_store.save_memory(key="c", value="3", tags=["seo", "twitter"])

        seo_memories = temp_store.get_all_memories(tags=["seo"])
        assert len(seo_memories) == 2
        assert {m.key for m in seo_memories} == {"a", "c"}

    def test_filter_by_min_importance(self, temp_store: MemoryStore):
        """Test filtering by minimum importance."""
        temp_store.save_memory(key="low", value="1", importance=3)
        temp_store.save_memory(key="medium", value="2", importance=5)
        temp_store.save_memory(key="high", value="3", importance=9)

        important = temp_store.get_all_memories(min_importance=5)
        assert len(important) == 2
        assert {m.key for m in important} == {"medium", "high"}

    def test_search_memories(self, temp_store: MemoryStore):
        """Test searching memories by text."""
        temp_store.save_memory(key="user_blog", value="https://example.com/blog")
        temp_store.save_memory(key="user_twitter", value="@example")
        temp_store.save_memory(key="blog_frequency", value="posts weekly")

        results = temp_store.search_memories("blog")
        assert len(results) == 2
        assert {m.key for m in results} == {"user_blog", "blog_frequency"}

    def test_search_case_insensitive(self, temp_store: MemoryStore):
        """Test that search is case-insensitive."""
        temp_store.save_memory(key="Brand", value="ACME Corp")

        results = temp_store.search_memories("brand")
        assert len(results) == 1
        assert results[0].key == "Brand"

        results = temp_store.search_memories("acme")
        assert len(results) == 1

    def test_delete_memory(self, temp_store: MemoryStore):
        """Test deleting a memory."""
        temp_store.save_memory(key="to_delete", value="temporary")
        assert temp_store.get_memory("to_delete") is not None

        deleted = temp_store.delete_memory("to_delete")
        assert deleted is True
        assert temp_store.get_memory("to_delete") is None

    def test_delete_nonexistent_memory(self, temp_store: MemoryStore):
        """Test deleting a memory that doesn't exist."""
        deleted = temp_store.delete_memory("nonexistent")
        assert deleted is False

    def test_persistence(self, tmp_path: Path):
        """Test that memories persist across store instances."""
        storage_path = tmp_path / "persistent_memories"

        # Create store and save memory
        store1 = MemoryStore(storage_path=storage_path)
        store1.save_memory(key="persistent", value="data", importance=10)

        # Create new store instance with same path
        store2 = MemoryStore(storage_path=storage_path)
        memory = store2.get_memory("persistent")

        assert memory is not None
        assert memory.value == "data"
        assert memory.importance == 10

    def test_get_stats(self, temp_store: MemoryStore):
        """Test getting memory statistics."""
        temp_store.save_memory(key="a", value="1", category="fact")
        temp_store.save_memory(key="b", value="2", category="goal")
        temp_store.save_memory(key="c", value="3", category="fact")

        stats = temp_store.get_stats()
        assert stats["total_memories"] == 3
        assert stats["categories"]["fact"] == 2
        assert stats["categories"]["goal"] == 1

    def test_empty_store_stats(self, temp_store: MemoryStore):
        """Test stats on empty store."""
        stats = temp_store.get_stats()
        assert stats["total_memories"] == 0
        assert stats["oldest_memory"] is None
        assert stats["newest_memory"] is None
