"""Tests for the memory storage module."""

import json
from datetime import datetime
from pathlib import Path

from agent_framework.storage.memory_store import Memory, MemoryStore


class TestMemory:
    """Tests for the Memory model."""

    def test_memory_creation(self):
        """Test creating a Memory object with required fields."""
        memory = Memory(key="test_key", value="test_value")

        assert memory.key == "test_key"
        assert memory.value == "test_value"
        assert memory.category is None
        assert memory.tags == []
        assert memory.importance == 5
        assert isinstance(memory.created_at, datetime)
        assert isinstance(memory.updated_at, datetime)

    def test_memory_creation_with_all_fields(self, sample_memory: Memory):
        """Test creating a Memory object with all fields."""
        assert sample_memory.key == "test_key"
        assert sample_memory.value == "test value"
        assert sample_memory.category == "test_category"
        assert sample_memory.tags == ["tag1", "tag2"]
        assert sample_memory.importance == 7

    def test_memory_to_dict(self, sample_memory: Memory):
        """Test converting Memory to dictionary."""
        data = sample_memory.to_dict()

        assert data["key"] == "test_key"
        assert data["value"] == "test value"
        assert data["category"] == "test_category"
        assert data["tags"] == ["tag1", "tag2"]
        assert data["importance"] == 7
        assert "created_at" in data
        assert "updated_at" in data

    def test_memory_from_dict(self, sample_memory: Memory):
        """Test creating Memory from dictionary."""
        data = sample_memory.to_dict()
        restored = Memory.from_dict(data)

        assert restored.key == sample_memory.key
        assert restored.value == sample_memory.value
        assert restored.category == sample_memory.category
        assert restored.tags == sample_memory.tags
        assert restored.importance == sample_memory.importance

    def test_memory_roundtrip(self, sample_memory: Memory):
        """Test that Memory can be serialized and deserialized."""
        data = sample_memory.to_dict()
        json_str = json.dumps(data)
        restored_data = json.loads(json_str)
        restored = Memory.from_dict(restored_data)

        assert restored.key == sample_memory.key
        assert restored.value == sample_memory.value


class TestMemoryStore:
    """Tests for the MemoryStore class."""

    def test_memory_store_initialization(self, temp_dir: Path):
        """Test MemoryStore initialization creates storage directory."""
        storage_path = temp_dir / "test_memories"
        store = MemoryStore(storage_path=storage_path)

        assert storage_path.exists()
        assert store.memory_file == storage_path / "memories.json"
        assert len(store.memories) == 0

    def test_save_new_memory(self, memory_store: MemoryStore):
        """Test saving a new memory."""
        memory = memory_store.save_memory(
            key="user_name",
            value="John Doe",
            category="user_info",
            tags=["personal"],
            importance=8,
        )

        assert memory.key == "user_name"
        assert memory.value == "John Doe"
        assert memory.category == "user_info"
        assert memory.tags == ["personal"]
        assert memory.importance == 8
        assert "user_name" in memory_store.memories

    def test_update_existing_memory(self, memory_store: MemoryStore):
        """Test updating an existing memory."""
        # Save initial memory
        memory_store.save_memory(key="test", value="initial")

        # Update memory
        updated = memory_store.save_memory(key="test", value="updated", importance=10)

        assert updated.value == "updated"
        assert updated.importance == 10
        assert len(memory_store.memories) == 1

    def test_get_memory(self, memory_store: MemoryStore):
        """Test retrieving a memory by key."""
        memory_store.save_memory(key="test", value="value")

        result = memory_store.get_memory("test")

        assert result is not None
        assert result.value == "value"

    def test_get_nonexistent_memory(self, memory_store: MemoryStore):
        """Test retrieving a non-existent memory returns None."""
        result = memory_store.get_memory("nonexistent")
        assert result is None

    def test_get_all_memories(self, memory_store: MemoryStore):
        """Test retrieving all memories."""
        memory_store.save_memory(key="mem1", value="value1", importance=5)
        memory_store.save_memory(key="mem2", value="value2", importance=10)
        memory_store.save_memory(key="mem3", value="value3", importance=3)

        memories = memory_store.get_all_memories()

        assert len(memories) == 3
        # Should be sorted by importance (high to low)
        assert memories[0].importance == 10
        assert memories[1].importance == 5
        assert memories[2].importance == 3

    def test_get_memories_filter_by_category(self, memory_store: MemoryStore):
        """Test filtering memories by category."""
        memory_store.save_memory(key="pref1", value="v1", category="preference")
        memory_store.save_memory(key="fact1", value="v2", category="fact")
        memory_store.save_memory(key="pref2", value="v3", category="preference")

        memories = memory_store.get_all_memories(category="preference")

        assert len(memories) == 2
        assert all(m.category == "preference" for m in memories)

    def test_get_memories_filter_by_tags(self, memory_store: MemoryStore):
        """Test filtering memories by tags."""
        memory_store.save_memory(key="m1", value="v1", tags=["python", "coding"])
        memory_store.save_memory(key="m2", value="v2", tags=["javascript"])
        memory_store.save_memory(key="m3", value="v3", tags=["python"])

        memories = memory_store.get_all_memories(tags=["python"])

        assert len(memories) == 2

    def test_get_memories_filter_by_min_importance(self, memory_store: MemoryStore):
        """Test filtering memories by minimum importance."""
        memory_store.save_memory(key="m1", value="v1", importance=3)
        memory_store.save_memory(key="m2", value="v2", importance=7)
        memory_store.save_memory(key="m3", value="v3", importance=9)

        memories = memory_store.get_all_memories(min_importance=7)

        assert len(memories) == 2
        assert all(m.importance >= 7 for m in memories)

    def test_search_memories(self, memory_store: MemoryStore):
        """Test searching memories by text."""
        memory_store.save_memory(key="user_email", value="john@example.com")
        memory_store.save_memory(key="api_key", value="secret123")
        memory_store.save_memory(key="user_phone", value="555-1234")

        results = memory_store.search_memories("user")

        assert len(results) == 2

    def test_search_memories_case_insensitive(self, memory_store: MemoryStore):
        """Test that search is case-insensitive."""
        memory_store.save_memory(key="UserName", value="John")

        results = memory_store.search_memories("username")

        assert len(results) == 1

    def test_delete_memory(self, memory_store: MemoryStore):
        """Test deleting a memory."""
        memory_store.save_memory(key="to_delete", value="value")

        result = memory_store.delete_memory("to_delete")

        assert result is True
        assert "to_delete" not in memory_store.memories

    def test_delete_nonexistent_memory(self, memory_store: MemoryStore):
        """Test deleting a non-existent memory returns False."""
        result = memory_store.delete_memory("nonexistent")
        assert result is False

    def test_get_stats(self, memory_store: MemoryStore):
        """Test getting memory statistics."""
        memory_store.save_memory(key="m1", value="v1", category="cat1")
        memory_store.save_memory(key="m2", value="v2", category="cat1")
        memory_store.save_memory(key="m3", value="v3", category="cat2")

        stats = memory_store.get_stats()

        assert stats["total_memories"] == 3
        assert stats["categories"]["cat1"] == 2
        assert stats["categories"]["cat2"] == 1
        assert stats["oldest_memory"] is not None
        assert stats["newest_memory"] is not None

    def test_get_stats_empty_store(self, memory_store: MemoryStore):
        """Test getting stats from empty store."""
        stats = memory_store.get_stats()

        assert stats["total_memories"] == 0
        assert stats["categories"] == {}
        assert stats["oldest_memory"] is None
        assert stats["newest_memory"] is None

    def test_persistence(self, temp_dir: Path):
        """Test that memories persist across store instances."""
        storage_path = temp_dir / "persist_test"

        # Create store and save memory
        store1 = MemoryStore(storage_path=storage_path)
        store1.save_memory(key="persistent", value="data", importance=9)

        # Create new store instance with same path
        store2 = MemoryStore(storage_path=storage_path)

        # Memory should be loaded
        memory = store2.get_memory("persistent")
        assert memory is not None
        assert memory.value == "data"
        assert memory.importance == 9
