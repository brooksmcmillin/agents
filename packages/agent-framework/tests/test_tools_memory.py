"""Tests for the memory tools module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_framework.storage.memory_store import DEFAULT_AGENT_NAME
from agent_framework.tools.memory import (
    MAX_KEY_LENGTH,
    MAX_VALUE_LENGTH,
    InvalidAgentNameError,
    get_memories,
    get_memory_store,
    save_memory,
    search_memories,
    validate_agent_name,
)


class TestGetMemoryStore:
    """Tests for get_memory_store function."""

    def test_get_memory_store_creates_instance(self, temp_dir: Path, monkeypatch):
        """Test get_memory_store creates a new instance."""
        from agent_framework.tools import memory

        memory._file_memory_stores.clear()

        with patch("agent_framework.tools.memory.MemoryStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store_class.return_value = mock_store

            result = get_memory_store()

            mock_store_class.assert_called_once_with(agent_name=DEFAULT_AGENT_NAME)
            assert result is mock_store

    def test_get_memory_store_returns_singleton_per_agent(self, temp_dir: Path):
        """Test get_memory_store returns the same instance for same agent."""
        from agent_framework.tools import memory

        memory._file_memory_stores.clear()

        with patch("agent_framework.tools.memory.MemoryStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store_class.return_value = mock_store

            result1 = get_memory_store()
            result2 = get_memory_store()

            # Should only create once for same agent
            mock_store_class.assert_called_once()
            assert result1 is result2

    def test_get_memory_store_different_agents(self, temp_dir: Path):
        """Test get_memory_store returns different instances for different agents."""
        from agent_framework.tools import memory

        memory._file_memory_stores.clear()

        with patch("agent_framework.tools.memory.MemoryStore") as mock_store_class:
            mock_chatbot = MagicMock()
            mock_pr = MagicMock()
            mock_store_class.side_effect = [mock_chatbot, mock_pr]

            result1 = get_memory_store("chatbot")
            result2 = get_memory_store("pr_agent")

            # Should create separate stores for each agent
            assert mock_store_class.call_count == 2
            assert result1 is not result2


class TestSaveMemory:
    """Tests for save_memory function."""

    @pytest.mark.asyncio
    async def test_save_memory_success(self):
        """Test save_memory returns success response."""
        mock_memory = MagicMock()
        mock_memory.key = "test_key"
        mock_memory.value = "test_value"
        mock_memory.category = "test_cat"
        mock_memory.tags = ["tag1"]
        mock_memory.importance = 7
        mock_memory.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_memory.updated_at.isoformat.return_value = "2024-01-01T00:00:00"

        mock_store = AsyncMock()
        mock_store.save_memory.return_value = mock_memory

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await save_memory(
                key="test_key",
                value="test_value",
                category="test_cat",
                tags=["tag1"],
                importance=7,
            )

        assert result["status"] == "success"
        assert result["agent_name"] == DEFAULT_AGENT_NAME
        assert result["memory"]["key"] == "test_key"
        assert result["memory"]["value"] == "test_value"
        assert "Successfully saved" in result["message"]

    @pytest.mark.asyncio
    async def test_save_memory_created_vs_updated(self):
        """Test save_memory correctly identifies created vs updated."""
        # Test new memory (created_at == updated_at)
        mock_memory = MagicMock()
        mock_memory.key = "new_key"
        mock_memory.value = "value"
        mock_memory.category = None
        mock_memory.tags = []
        mock_memory.importance = 5
        # Use same mock object for both to simulate newly created memory
        mock_time = MagicMock()
        mock_time.isoformat.return_value = "2024-01-01T00:00:00"
        mock_memory.created_at = mock_time
        mock_memory.updated_at = mock_time  # Same object = equal

        mock_store = AsyncMock()
        mock_store.save_memory.return_value = mock_memory

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await save_memory(key="new_key", value="value")

        assert result["action"] == "created"

    @pytest.mark.asyncio
    async def test_save_memory_error_handling(self):
        """Test save_memory handles errors gracefully."""
        mock_store = AsyncMock()
        mock_store.save_memory.side_effect = Exception("Storage error")

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await save_memory(key="test", value="value")

        assert result["status"] == "error"
        assert "Storage error" in result["message"]

    @pytest.mark.asyncio
    async def test_save_memory_key_too_long(self):
        """Test save_memory rejects keys exceeding MAX_KEY_LENGTH."""
        long_key = "k" * (MAX_KEY_LENGTH + 1)
        result = await save_memory(key=long_key, value="some value")

        assert result["status"] == "error"
        assert "key exceeds maximum length" in result["message"]
        assert str(MAX_KEY_LENGTH) in result["message"]

    @pytest.mark.asyncio
    async def test_save_memory_key_at_max_length_succeeds(self):
        """Test save_memory accepts keys exactly at MAX_KEY_LENGTH."""
        exact_key = "k" * MAX_KEY_LENGTH
        mock_memory = MagicMock()
        mock_memory.key = exact_key
        mock_memory.value = "value"
        mock_memory.category = None
        mock_memory.tags = []
        mock_memory.importance = 5
        mock_time = MagicMock()
        mock_time.isoformat.return_value = "2024-01-01T00:00:00"
        mock_memory.created_at = mock_time
        mock_memory.updated_at = mock_time

        mock_store = AsyncMock()
        mock_store.save_memory.return_value = mock_memory

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await save_memory(key=exact_key, value="value")

        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_save_memory_value_too_long(self):
        """Test save_memory rejects values exceeding MAX_VALUE_LENGTH."""
        long_value = "v" * (MAX_VALUE_LENGTH + 1)
        result = await save_memory(key="valid_key", value=long_value)

        assert result["status"] == "error"
        assert "value exceeds maximum length" in result["message"]
        assert str(MAX_VALUE_LENGTH) in result["message"]

    @pytest.mark.asyncio
    async def test_save_memory_value_at_max_length_succeeds(self):
        """Test save_memory accepts values exactly at MAX_VALUE_LENGTH."""
        exact_value = "v" * MAX_VALUE_LENGTH
        mock_memory = MagicMock()
        mock_memory.key = "key"
        mock_memory.value = exact_value
        mock_memory.category = None
        mock_memory.tags = []
        mock_memory.importance = 5
        mock_time = MagicMock()
        mock_time.isoformat.return_value = "2024-01-01T00:00:00"
        mock_memory.created_at = mock_time
        mock_memory.updated_at = mock_time

        mock_store = AsyncMock()
        mock_store.save_memory.return_value = mock_memory

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await save_memory(key="key", value=exact_value)

        assert result["status"] == "success"


class TestGetMemories:
    """Tests for get_memories function."""

    @pytest.mark.asyncio
    async def test_get_memories_success(self):
        """Test get_memories returns memories successfully."""
        mock_memory = MagicMock()
        mock_memory.key = "key1"
        mock_memory.value = "value1"
        mock_memory.category = "cat1"
        mock_memory.tags = ["tag1"]
        mock_memory.importance = 8
        mock_memory.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_memory.updated_at.isoformat.return_value = "2024-01-01T00:00:00"

        mock_store = AsyncMock()
        mock_store.get_all_memories.return_value = [mock_memory]

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await get_memories(category="cat1", min_importance=5)

        assert result["status"] == "success"
        assert result["agent_name"] == DEFAULT_AGENT_NAME
        assert result["count"] == 1
        assert len(result["memories"]) == 1
        assert result["memories"][0]["key"] == "key1"

    @pytest.mark.asyncio
    async def test_get_memories_with_limit(self):
        """Test get_memories respects limit parameter."""
        mock_memories = [MagicMock() for _ in range(10)]
        for i, m in enumerate(mock_memories):
            m.key = f"key{i}"
            m.value = f"value{i}"
            m.category = None
            m.tags = []
            m.importance = 5
            m.created_at.isoformat.return_value = "2024-01-01T00:00:00"
            m.updated_at.isoformat.return_value = "2024-01-01T00:00:00"

        mock_store = AsyncMock()
        mock_store.get_all_memories.return_value = mock_memories

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await get_memories(limit=5)

        assert result["count"] == 5
        assert len(result["memories"]) == 5

    @pytest.mark.asyncio
    async def test_get_memories_empty(self):
        """Test get_memories handles empty results."""
        mock_store = AsyncMock()
        mock_store.get_all_memories.return_value = []

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await get_memories()

        assert result["status"] == "success"
        assert result["count"] == 0
        assert result["memories"] == []

    @pytest.mark.asyncio
    async def test_get_memories_error_handling(self):
        """Test get_memories handles errors gracefully."""
        mock_store = AsyncMock()
        mock_store.get_all_memories.side_effect = Exception("Query error")

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await get_memories()

        assert result["status"] == "error"
        assert "Query error" in result["message"]


class TestSearchMemories:
    """Tests for search_memories function."""

    @pytest.mark.asyncio
    async def test_search_memories_success(self):
        """Test search_memories returns matching memories."""
        mock_memory = MagicMock()
        mock_memory.key = "user_email"
        mock_memory.value = "test@example.com"
        mock_memory.category = "contact"
        mock_memory.tags = []
        mock_memory.importance = 5
        mock_memory.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_memory.updated_at.isoformat.return_value = "2024-01-01T00:00:00"

        mock_store = AsyncMock()
        mock_store.search_memories.return_value = [mock_memory]

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await search_memories(query="email")

        assert result["status"] == "success"
        assert result["agent_name"] == DEFAULT_AGENT_NAME
        assert result["query"] == "email"
        assert result["count"] == 1
        assert "matching 'email'" in result["message"]

    @pytest.mark.asyncio
    async def test_search_memories_with_limit(self):
        """Test search_memories respects limit parameter."""
        mock_memories = [MagicMock() for _ in range(10)]
        for i, m in enumerate(mock_memories):
            m.key = f"key{i}"
            m.value = f"value{i}"
            m.category = None
            m.tags = []
            m.importance = 5
            m.created_at.isoformat.return_value = "2024-01-01T00:00:00"
            m.updated_at.isoformat.return_value = "2024-01-01T00:00:00"

        mock_store = AsyncMock()
        mock_store.search_memories.return_value = mock_memories

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await search_memories(query="key", limit=3)

        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_search_memories_no_results(self):
        """Test search_memories handles no matches."""
        mock_store = AsyncMock()
        mock_store.search_memories.return_value = []

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await search_memories(query="nonexistent")

        assert result["status"] == "success"
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_search_memories_error_handling(self):
        """Test search_memories handles errors gracefully."""
        mock_store = AsyncMock()
        mock_store.search_memories.side_effect = Exception("Search error")

        with patch(
            "agent_framework.tools.memory.get_active_memory_store",
            return_value=mock_store,
        ):
            result = await search_memories(query="test")

        assert result["status"] == "error"
        assert "Search error" in result["message"]


class TestAgentNameValidation:
    """Tests for agent_name validation to prevent security issues."""

    def test_valid_agent_names(self):
        """Test that valid agent names are accepted."""
        valid_names = [
            "chatbot",
            "pr_agent",
            "security-researcher",
            "Agent123",
            "my_agent_v2",
            "test-agent-1",
            "a",  # Single character
            "A" * 100,  # Max length
        ]
        for name in valid_names:
            assert validate_agent_name(name) == name

    def test_empty_agent_name_rejected(self):
        """Test that empty agent names are rejected."""
        with pytest.raises(InvalidAgentNameError, match="cannot be empty"):
            validate_agent_name("")

    def test_null_bytes_rejected(self):
        """Test that null bytes in agent names are rejected."""
        with pytest.raises(InvalidAgentNameError, match="null bytes"):
            validate_agent_name("agent\x00name")

    def test_path_traversal_rejected(self):
        """Test that path traversal attempts are rejected."""
        malicious_names = [
            "../etc/passwd",
            "..\\windows\\system32",
            "agent/../secrets",
            "/etc/passwd",
            "\\windows\\system32",
            "agent/subdir",
            "agent\\subdir",
        ]
        for name in malicious_names:
            with pytest.raises(InvalidAgentNameError, match="path traversal"):
                validate_agent_name(name)

    def test_max_length_exceeded_rejected(self):
        """Test that agent names exceeding max length are rejected."""
        long_name = "a" * 101  # Exceeds VARCHAR(100)
        with pytest.raises(InvalidAgentNameError, match="cannot exceed 100 characters"):
            validate_agent_name(long_name)

    def test_invalid_characters_rejected(self):
        """Test that invalid characters in agent names are rejected."""
        invalid_names = [
            "agent name",  # Space
            "agent@name",  # @ symbol
            "agent.name",  # Period (allowed in file paths but dangerous)
            "agent!name",  # Exclamation
            "agent#name",  # Hash
            "agent$name",  # Dollar sign
            "agent%name",  # Percent
            "agent;name",  # Semicolon (command injection)
            "agent|name",  # Pipe (command injection)
            "agent`name",  # Backtick (command injection)
            "agent'name",  # Single quote (SQL injection)
            'agent"name',  # Double quote
        ]
        for name in invalid_names:
            with pytest.raises(
                InvalidAgentNameError, match="alphanumeric characters, underscores, and hyphens"
            ):
                validate_agent_name(name)

    def test_get_memory_store_validates_agent_name(self, temp_dir: Path):
        """Test that get_memory_store validates the agent name."""
        from agent_framework.tools import memory

        memory._file_memory_stores.clear()

        with pytest.raises(InvalidAgentNameError, match="path traversal"):
            get_memory_store(agent_name="../malicious")


class TestSaveMemoryToolSchema:
    """Tests for the save_memory tool schema constraints."""

    def _get_save_memory_schema(self) -> dict:
        from agent_framework.tools.memory import TOOL_SCHEMAS

        for schema in TOOL_SCHEMAS:
            if schema["name"] == "save_memory":
                return schema["input_schema"]
        raise AssertionError("save_memory schema not found")

    def test_key_has_max_length_constraint(self):
        """Test that the key field has a maxLength of 256."""
        schema = self._get_save_memory_schema()
        key_schema = schema["properties"]["key"]
        assert "maxLength" in key_schema, "key field must have maxLength constraint"
        assert key_schema["maxLength"] == MAX_KEY_LENGTH

    def test_value_has_max_length_constraint(self):
        """Test that the value field has a maxLength of 10000."""
        schema = self._get_save_memory_schema()
        value_schema = schema["properties"]["value"]
        assert "maxLength" in value_schema, "value field must have maxLength constraint"
        assert value_schema["maxLength"] == MAX_VALUE_LENGTH

    def test_agent_name_retains_max_length_constraint(self):
        """Test that the existing agent_name maxLength constraint is unchanged."""
        schema = self._get_save_memory_schema()
        agent_name_schema = schema["properties"]["agent_name"]
        assert agent_name_schema["maxLength"] == 100
