"""Tests for memory backend routing based on environment variables.

These tests verify that:
1. MEMORY_BACKEND=file uses the file-based MemoryStore
2. MEMORY_BACKEND=database uses the DatabaseMemoryStore
3. DATABASE_URL and MEMORY_DATABASE_URL are both supported
4. The memory tools properly route to the configured backend
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest


class TestMemoryBackendSelection:
    """Tests for _get_backend() function."""

    def test_default_backend_is_file(self, monkeypatch):
        """Test that the default backend is 'file' when no env var is set."""
        monkeypatch.delenv("MEMORY_BACKEND", raising=False)

        from agent_framework.tools.memory import _get_backend

        assert _get_backend() == "file"

    def test_file_backend_from_env(self, monkeypatch):
        """Test that MEMORY_BACKEND=file returns 'file'."""
        monkeypatch.setenv("MEMORY_BACKEND", "file")

        from agent_framework.tools.memory import _get_backend

        assert _get_backend() == "file"

    def test_database_backend_from_env(self, monkeypatch):
        """Test that MEMORY_BACKEND=database returns 'database'."""
        monkeypatch.setenv("MEMORY_BACKEND", "database")

        from agent_framework.tools.memory import _get_backend

        assert _get_backend() == "database"

    def test_backend_case_insensitive(self, monkeypatch):
        """Test that backend selection is case-insensitive."""
        monkeypatch.setenv("MEMORY_BACKEND", "DATABASE")

        from agent_framework.tools.memory import _get_backend

        assert _get_backend() == "database"


class TestDatabaseUrlResolution:
    """Tests for database URL environment variable resolution."""

    @pytest.mark.asyncio
    async def test_memory_database_url_takes_precedence(self, monkeypatch):
        """Test that MEMORY_DATABASE_URL takes precedence over DATABASE_URL."""
        monkeypatch.setenv("MEMORY_BACKEND", "database")
        monkeypatch.setenv("MEMORY_DATABASE_URL", "postgresql://memory:pass@host1/db")
        monkeypatch.setenv("DATABASE_URL", "postgresql://general:pass@host2/db")

        from agent_framework.tools import memory

        # Reset the singleton
        memory._database_memory_store = None

        # Mock DatabaseMemoryStore to capture the URL it's initialized with
        with patch("agent_framework.tools.memory.DatabaseMemoryStore") as mock_store:
            mock_instance = AsyncMock()
            mock_store.return_value = mock_instance

            await memory.get_database_memory_store()

            # Verify it was called with MEMORY_DATABASE_URL
            mock_store.assert_called_once()
            call_args = mock_store.call_args[0]
            assert call_args[0] == "postgresql://memory:pass@host1/db"

    @pytest.mark.asyncio
    async def test_database_url_fallback(self, monkeypatch):
        """Test that DATABASE_URL is used when MEMORY_DATABASE_URL is not set."""
        monkeypatch.setenv("MEMORY_BACKEND", "database")
        monkeypatch.delenv("MEMORY_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://fallback:pass@host/db")

        from agent_framework.tools import memory

        # Reset the singleton
        memory._database_memory_store = None

        # Mock DatabaseMemoryStore to capture the URL it's initialized with
        with patch("agent_framework.tools.memory.DatabaseMemoryStore") as mock_store:
            mock_instance = AsyncMock()
            mock_store.return_value = mock_instance

            await memory.get_database_memory_store()

            # Verify it was called with DATABASE_URL
            mock_store.assert_called_once()
            call_args = mock_store.call_args[0]
            assert call_args[0] == "postgresql://fallback:pass@host/db"

    @pytest.mark.asyncio
    async def test_no_database_url_raises_error(self, monkeypatch):
        """Test that missing database URL raises ValueError."""
        monkeypatch.setenv("MEMORY_BACKEND", "database")
        monkeypatch.delenv("MEMORY_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        from agent_framework.tools import memory

        # Reset the singleton
        memory._database_memory_store = None

        with pytest.raises(ValueError, match="DATABASE_URL.*required"):
            await memory.get_database_memory_store()


class TestMemoryToolsRouting:
    """Tests for memory tool routing to correct backend."""

    @pytest.mark.asyncio
    async def test_save_memory_uses_file_backend(self, monkeypatch, temp_dir):
        """Test that save_memory uses file backend when configured."""
        monkeypatch.setenv("MEMORY_BACKEND", "file")

        from agent_framework.storage.memory_store import MemoryStore
        from agent_framework.tools import memory

        # Reset singletons
        memory._file_memory_store = None
        memory._database_memory_store = None

        # Create file store with temp path
        memory._file_memory_store = MemoryStore(storage_path=temp_dir / "memories")

        result = await memory.save_memory(
            key="test_file_routing",
            value="test value",
        )

        assert result["status"] == "success"
        # Verify it was saved to the file store
        assert "test_file_routing" in memory._file_memory_store.memories

    @pytest.mark.asyncio
    async def test_save_memory_uses_database_backend(self, monkeypatch):
        """Test that save_memory uses database backend when configured."""
        from datetime import datetime

        monkeypatch.setenv("MEMORY_BACKEND", "database")
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:pass@localhost/db")

        from agent_framework.storage.memory_store import Memory
        from agent_framework.tools import memory

        # Reset singletons
        memory._file_memory_store = None
        memory._database_memory_store = None

        # Mock the database store with a proper Memory object
        mock_db_store = AsyncMock()
        mock_memory = Memory(
            key="test_db_routing",
            value="test value",
            category=None,
            tags=[],
            importance=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mock_db_store.save_memory.return_value = mock_memory

        with patch("agent_framework.tools.memory.get_database_memory_store") as mock_get_db:
            mock_get_db.return_value = mock_db_store

            result = await memory.save_memory(
                key="test_db_routing",
                value="test value",
            )

            assert result["status"] == "success"
            mock_db_store.save_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_memories_uses_correct_backend(self, monkeypatch, temp_dir):
        """Test that get_memories uses the configured backend."""
        monkeypatch.setenv("MEMORY_BACKEND", "file")

        from agent_framework.storage.memory_store import MemoryStore
        from agent_framework.tools import memory

        # Reset singletons
        memory._file_memory_store = None
        memory._database_memory_store = None

        # Create file store with temp path and add a memory
        file_store = MemoryStore(storage_path=temp_dir / "memories")
        file_store.save_memory(key="test_get", value="test value")
        memory._file_memory_store = file_store

        result = await memory.get_memories()

        assert result["status"] == "success"
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_search_memories_uses_correct_backend(self, monkeypatch, temp_dir):
        """Test that search_memories uses the configured backend."""
        monkeypatch.setenv("MEMORY_BACKEND", "file")

        from agent_framework.storage.memory_store import MemoryStore
        from agent_framework.tools import memory

        # Reset singletons
        memory._file_memory_store = None
        memory._database_memory_store = None

        # Create file store with temp path and add a memory
        file_store = MemoryStore(storage_path=temp_dir / "memories")
        file_store.save_memory(key="searchable_key", value="searchable value")
        memory._file_memory_store = file_store

        result = await memory.search_memories(query="searchable")

        assert result["status"] == "success"
        assert result["count"] >= 1


class TestConfigureMemoryStore:
    """Tests for configure_memory_store function."""

    @pytest.mark.asyncio
    async def test_configure_file_backend(self, monkeypatch, temp_dir):
        """Test configuring file backend."""

        from agent_framework.tools import memory

        # Reset singletons
        memory._file_memory_store = None
        memory._database_memory_store = None

        await memory.configure_memory_store(
            backend="file",
            storage_path=str(temp_dir / "configured_memories"),
        )

        assert memory._file_memory_store is not None
        assert os.environ.get("MEMORY_BACKEND") == "file"

    @pytest.mark.asyncio
    async def test_configure_database_backend(self, monkeypatch):
        """Test configuring database backend."""

        from agent_framework.tools import memory

        # Reset singletons
        memory._file_memory_store = None
        memory._database_memory_store = None

        # Mock DatabaseMemoryStore since we don't have a real DB in unit tests
        with patch("agent_framework.tools.memory.DatabaseMemoryStore") as mock_store:
            mock_instance = AsyncMock()
            mock_store.return_value = mock_instance

            await memory.configure_memory_store(
                backend="database",
                database_url="postgresql://test:pass@localhost/db",
            )

            assert os.environ.get("MEMORY_BACKEND") == "database"
            mock_instance.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_configure_database_without_url_raises_error(self):
        """Test that configuring database backend without URL raises error."""
        from agent_framework.tools import memory

        # Reset singletons
        memory._file_memory_store = None
        memory._database_memory_store = None

        with pytest.raises(ValueError, match="database_url.*required"):
            await memory.configure_memory_store(backend="database")
