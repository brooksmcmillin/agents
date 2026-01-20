"""Tests for the memory tools module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_framework.tools.memory import (
    get_memories,
    get_memory_store,
    save_memory,
    search_memories,
)


class TestGetMemoryStore:
    """Tests for get_memory_store function."""

    def test_get_memory_store_creates_instance(self, temp_dir: Path, monkeypatch):
        """Test get_memory_store creates a new instance."""
        from agent_framework.tools import memory

        monkeypatch.setattr(memory, "_file_memory_store", None)

        with patch("agent_framework.tools.memory.MemoryStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store_class.return_value = mock_store

            result = get_memory_store()

            mock_store_class.assert_called_once()
            assert result is mock_store

    def test_get_memory_store_returns_singleton(self, temp_dir: Path):
        """Test get_memory_store returns the same instance."""

        with patch("agent_framework.tools.memory.MemoryStore") as mock_store_class:
            mock_store = MagicMock()
            mock_store_class.return_value = mock_store

            result1 = get_memory_store()
            result2 = get_memory_store()

            # Should only create once
            mock_store_class.assert_called_once()
            assert result1 is result2


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

        mock_store = MagicMock()
        mock_store.save_memory.return_value = mock_memory

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await save_memory(
                key="test_key",
                value="test_value",
                category="test_cat",
                tags=["tag1"],
                importance=7,
            )

        assert result["status"] == "success"
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

        mock_store = MagicMock()
        mock_store.save_memory.return_value = mock_memory

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await save_memory(key="new_key", value="value")

        assert result["action"] == "created"

    @pytest.mark.asyncio
    async def test_save_memory_error_handling(self):
        """Test save_memory handles errors gracefully."""
        mock_store = MagicMock()
        mock_store.save_memory.side_effect = Exception("Storage error")

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await save_memory(key="test", value="value")

        assert result["status"] == "error"
        assert "Failed to save memory" in result["message"]


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

        mock_store = MagicMock()
        mock_store.get_all_memories.return_value = [mock_memory]

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await get_memories(category="cat1", min_importance=5)

        assert result["status"] == "success"
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

        mock_store = MagicMock()
        mock_store.get_all_memories.return_value = mock_memories

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await get_memories(limit=5)

        assert result["count"] == 5
        assert len(result["memories"]) == 5

    @pytest.mark.asyncio
    async def test_get_memories_empty(self):
        """Test get_memories handles empty results."""
        mock_store = MagicMock()
        mock_store.get_all_memories.return_value = []

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await get_memories()

        assert result["status"] == "success"
        assert result["count"] == 0
        assert result["memories"] == []

    @pytest.mark.asyncio
    async def test_get_memories_error_handling(self):
        """Test get_memories handles errors gracefully."""
        mock_store = MagicMock()
        mock_store.get_all_memories.side_effect = Exception("Query error")

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await get_memories()

        assert result["status"] == "error"
        assert "Failed to retrieve memories" in result["message"]
        assert result["memories"] == []


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

        mock_store = MagicMock()
        mock_store.search_memories.return_value = [mock_memory]

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await search_memories(query="email")

        assert result["status"] == "success"
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

        mock_store = MagicMock()
        mock_store.search_memories.return_value = mock_memories

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await search_memories(query="key", limit=3)

        assert result["count"] == 3

    @pytest.mark.asyncio
    async def test_search_memories_no_results(self):
        """Test search_memories handles no matches."""
        mock_store = MagicMock()
        mock_store.search_memories.return_value = []

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await search_memories(query="nonexistent")

        assert result["status"] == "success"
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_search_memories_error_handling(self):
        """Test search_memories handles errors gracefully."""
        mock_store = MagicMock()
        mock_store.search_memories.side_effect = Exception("Search error")

        with patch("agent_framework.tools.memory.get_memory_store", return_value=mock_store):
            result = await search_memories(query="test")

        assert result["status"] == "error"
        assert "Failed to search memories" in result["message"]
