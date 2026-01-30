"""Tests for the memory storage module."""

import json
from datetime import datetime
from pathlib import Path

from agent_framework.storage.memory_store import DEFAULT_AGENT_NAME, Memory, MemoryStore


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

        # Agent-specific subdirectory should be created
        assert (storage_path / DEFAULT_AGENT_NAME).exists()
        assert store.memory_file == storage_path / DEFAULT_AGENT_NAME / "memories.json"
        assert len(store.memories) == 0
        assert store.agent_name == DEFAULT_AGENT_NAME

    def test_memory_store_with_custom_agent_name(self, temp_dir: Path):
        """Test MemoryStore initialization with custom agent name."""
        storage_path = temp_dir / "test_memories"
        store = MemoryStore(storage_path=storage_path, agent_name="chatbot")

        assert (storage_path / "chatbot").exists()
        assert store.memory_file == storage_path / "chatbot" / "memories.json"
        assert store.agent_name == "chatbot"

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

    def test_get_stats_includes_agent_name(self, memory_store: MemoryStore):
        """Test that get_stats includes agent_name."""
        stats = memory_store.get_stats()
        assert "agent_name" in stats
        assert stats["agent_name"] == DEFAULT_AGENT_NAME


class TestMemoryStoreAgentIsolation:
    """Tests for agent-level memory isolation."""

    def test_different_agents_have_separate_memories(self, temp_dir: Path):
        """Test that different agents have completely separate memory stores."""
        storage_path = temp_dir / "isolation_test"

        # Create stores for two different agents
        chatbot_store = MemoryStore(storage_path=storage_path, agent_name="chatbot")
        pr_agent_store = MemoryStore(storage_path=storage_path, agent_name="pr_agent")

        # Save memories to each agent
        chatbot_store.save_memory(key="user_name", value="Alice", importance=8)
        pr_agent_store.save_memory(key="user_name", value="Bob", importance=8)

        # Each agent should only see its own memory
        assert chatbot_store.get_memory("user_name").value == "Alice"
        assert pr_agent_store.get_memory("user_name").value == "Bob"

        # Verify they're stored in different directories
        assert (storage_path / "chatbot" / "memories.json").exists()
        assert (storage_path / "pr_agent" / "memories.json").exists()

    def test_agent_isolation_with_same_keys(self, temp_dir: Path):
        """Test that agents can use same keys without collision."""
        storage_path = temp_dir / "key_collision_test"

        # Create stores for multiple agents
        agents = ["chatbot", "pr_agent", "security_researcher"]
        stores = {
            name: MemoryStore(storage_path=storage_path, agent_name=name)
            for name in agents
        }

        # Save a memory with the same key to all agents
        for i, (name, store) in enumerate(stores.items()):
            store.save_memory(
                key="preference",
                value=f"Value for {name}",
                importance=i + 1,
            )

        # Verify each agent has its own value
        for i, (name, store) in enumerate(stores.items()):
            memory = store.get_memory("preference")
            assert memory.value == f"Value for {name}"
            assert memory.importance == i + 1

    def test_agent_isolation_get_all_memories(self, temp_dir: Path):
        """Test that get_all_memories only returns memories for the specified agent."""
        storage_path = temp_dir / "get_all_test"

        chatbot_store = MemoryStore(storage_path=storage_path, agent_name="chatbot")
        pr_agent_store = MemoryStore(storage_path=storage_path, agent_name="pr_agent")

        # Save multiple memories to each agent
        for i in range(3):
            chatbot_store.save_memory(key=f"chat_mem_{i}", value=f"chat value {i}")
            pr_agent_store.save_memory(key=f"pr_mem_{i}", value=f"pr value {i}")

        # Each agent should only see 3 memories
        assert len(chatbot_store.get_all_memories()) == 3
        assert len(pr_agent_store.get_all_memories()) == 3

        # Verify keys are correct
        chatbot_keys = {m.key for m in chatbot_store.get_all_memories()}
        pr_keys = {m.key for m in pr_agent_store.get_all_memories()}

        assert chatbot_keys == {"chat_mem_0", "chat_mem_1", "chat_mem_2"}
        assert pr_keys == {"pr_mem_0", "pr_mem_1", "pr_mem_2"}

    def test_agent_isolation_search_memories(self, temp_dir: Path):
        """Test that search_memories only searches within agent's memories."""
        storage_path = temp_dir / "search_test"

        chatbot_store = MemoryStore(storage_path=storage_path, agent_name="chatbot")
        pr_agent_store = MemoryStore(storage_path=storage_path, agent_name="pr_agent")

        # Save memories with searchable content
        chatbot_store.save_memory(key="email", value="alice@chatbot.com")
        pr_agent_store.save_memory(key="email", value="bob@pr.com")

        # Search should only find memories within the agent's store
        chatbot_results = chatbot_store.search_memories("@")
        pr_results = pr_agent_store.search_memories("@")

        assert len(chatbot_results) == 1
        assert chatbot_results[0].value == "alice@chatbot.com"

        assert len(pr_results) == 1
        assert pr_results[0].value == "bob@pr.com"

    def test_agent_isolation_delete_memory(self, temp_dir: Path):
        """Test that delete_memory only affects the specified agent."""
        storage_path = temp_dir / "delete_test"

        chatbot_store = MemoryStore(storage_path=storage_path, agent_name="chatbot")
        pr_agent_store = MemoryStore(storage_path=storage_path, agent_name="pr_agent")

        # Save same key to both agents
        chatbot_store.save_memory(key="to_delete", value="chatbot value")
        pr_agent_store.save_memory(key="to_delete", value="pr value")

        # Delete from chatbot only
        chatbot_store.delete_memory("to_delete")

        # Chatbot's memory should be gone, PR agent's should remain
        assert chatbot_store.get_memory("to_delete") is None
        assert pr_agent_store.get_memory("to_delete") is not None
        assert pr_agent_store.get_memory("to_delete").value == "pr value"

    def test_agent_persistence_with_isolation(self, temp_dir: Path):
        """Test that agent-specific memories persist correctly."""
        storage_path = temp_dir / "persist_isolation_test"

        # Create stores and save memories
        chatbot_store1 = MemoryStore(storage_path=storage_path, agent_name="chatbot")
        pr_store1 = MemoryStore(storage_path=storage_path, agent_name="pr_agent")

        chatbot_store1.save_memory(key="persist_key", value="chatbot persist")
        pr_store1.save_memory(key="persist_key", value="pr persist")

        # Create new store instances (simulating restart)
        chatbot_store2 = MemoryStore(storage_path=storage_path, agent_name="chatbot")
        pr_store2 = MemoryStore(storage_path=storage_path, agent_name="pr_agent")

        # Each should load its own memories
        assert chatbot_store2.get_memory("persist_key").value == "chatbot persist"
        assert pr_store2.get_memory("persist_key").value == "pr persist"

    def test_agent_stats_isolation(self, temp_dir: Path):
        """Test that get_stats only counts memories for the specified agent."""
        storage_path = temp_dir / "stats_test"

        chatbot_store = MemoryStore(storage_path=storage_path, agent_name="chatbot")
        pr_agent_store = MemoryStore(storage_path=storage_path, agent_name="pr_agent")

        # Save different numbers of memories
        for i in range(5):
            chatbot_store.save_memory(key=f"chat_{i}", value=f"v{i}", category="cat1")

        for i in range(3):
            pr_agent_store.save_memory(key=f"pr_{i}", value=f"v{i}", category="cat2")

        chatbot_stats = chatbot_store.get_stats()
        pr_stats = pr_agent_store.get_stats()

        assert chatbot_stats["total_memories"] == 5
        assert chatbot_stats["agent_name"] == "chatbot"
        assert "cat1" in chatbot_stats["categories"]

        assert pr_stats["total_memories"] == 3
        assert pr_stats["agent_name"] == "pr_agent"
        assert "cat2" in pr_stats["categories"]
