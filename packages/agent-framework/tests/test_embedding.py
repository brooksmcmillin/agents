"""Tests for the shared EmbeddingClient and recall_memories tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_framework.storage.embedding import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
    EmbeddingClient,
)


class TestEmbeddingClient:
    """Tests for the EmbeddingClient class."""

    def test_defaults(self):
        """Test default model is set correctly."""
        client = EmbeddingClient(api_key="test-key")
        assert client.model == DEFAULT_EMBEDDING_MODEL

    def test_custom_model(self):
        """Test passing a custom model."""
        client = EmbeddingClient(api_key="test-key", model="text-embedding-3-large")
        assert client.model == "text-embedding-3-large"

    @pytest.mark.asyncio
    async def test_get_embedding(self):
        """Test get_embedding calls OpenAI and returns the vector."""
        client = EmbeddingClient(api_key="test-key")

        mock_embedding = [0.1] * EMBEDDING_DIMENSIONS
        mock_data = MagicMock()
        mock_data.embedding = mock_embedding
        mock_response = MagicMock()
        mock_response.data = [mock_data]

        client._openai = AsyncMock()
        client._openai.embeddings.create = AsyncMock(return_value=mock_response)

        result = await client.get_embedding("hello world")
        assert result == mock_embedding
        client._openai.embeddings.create.assert_called_once_with(
            model=DEFAULT_EMBEDDING_MODEL,
            input="hello world",
        )

    def test_embedding_to_pgvector(self):
        """Test static pgvector format conversion."""
        vec = [0.1, 0.2, 0.3]
        result = EmbeddingClient.embedding_to_pgvector(vec)
        assert result == "[0.1,0.2,0.3]"

    def test_embedding_to_pgvector_empty(self):
        """Test pgvector conversion with empty vector."""
        assert EmbeddingClient.embedding_to_pgvector([]) == "[]"


class TestRecallMemoriesTool:
    """Tests for the recall_memories tool function."""

    @pytest.mark.asyncio
    async def test_recall_memories_file_backend_falls_back_to_keyword(
        self, monkeypatch, memory_store
    ):
        """Test that file backend falls back to keyword search."""
        monkeypatch.setenv("MEMORY_BACKEND", "file")

        # Save some memories to search against
        memory_store.save_memory(key="deploy_pref", value="User prefers Docker deployment")
        memory_store.save_memory(key="language_pref", value="User likes Python")

        from agent_framework.tools.memory import recall_memories

        with patch("agent_framework.tools.memory.get_memory_store", return_value=memory_store):
            result = await recall_memories(query="Docker", agent_name="shared")

        assert result["status"] == "success"
        assert result["method"] == "keyword"
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_recall_memories_database_semantic_path(self, monkeypatch):
        """Test semantic search path with mocked database store."""
        monkeypatch.setenv("MEMORY_BACKEND", "database")

        from agent_framework.storage.memory_store import Memory
        from agent_framework.tools.memory import recall_memories

        mock_memory = Memory(key="deploy_pref", value="User prefers Docker", importance=7)
        mock_store = AsyncMock()
        mock_store.has_embeddings = True  # semantic path
        mock_store.recall_memories = AsyncMock(return_value=[(mock_memory, 0.85)])

        with patch(
            "agent_framework.tools.memory.get_database_memory_store",
            return_value=mock_store,
        ):
            result = await recall_memories(query="deployment preferences", agent_name="test")

        assert result["status"] == "success"
        assert result["method"] == "semantic"
        assert result["count"] == 1
        assert result["memories"][0]["score"] == 0.85
        assert result["memories"][0]["key"] == "deploy_pref"

    @pytest.mark.asyncio
    async def test_recall_memories_database_keyword_fallback(self, monkeypatch):
        """Test database backend without embeddings falls back to keyword."""
        monkeypatch.setenv("MEMORY_BACKEND", "database")

        from agent_framework.storage.memory_store import Memory
        from agent_framework.tools.memory import recall_memories

        mock_memory = Memory(key="lang_pref", value="Python", importance=5)
        mock_store = AsyncMock()
        mock_store.has_embeddings = False  # keyword fallback
        mock_store.recall_memories = AsyncMock(return_value=[(mock_memory, 0.0)])

        with patch(
            "agent_framework.tools.memory.get_database_memory_store",
            return_value=mock_store,
        ):
            result = await recall_memories(query="Python", agent_name="test")

        assert result["status"] == "success"
        assert result["method"] == "keyword"

    @pytest.mark.asyncio
    async def test_recall_memories_error_handling(self, monkeypatch):
        """Test that errors are caught and returned gracefully."""
        monkeypatch.setenv("MEMORY_BACKEND", "database")

        from agent_framework.tools.memory import recall_memories

        with patch(
            "agent_framework.tools.memory.get_database_memory_store",
            side_effect=ValueError("DB not configured"),
        ):
            result = await recall_memories(query="anything", agent_name="test")

        assert result["status"] == "error"
        assert "memories" in result


class TestRecallMemoriesToolSchema:
    """Tests for the recall_memories tool schema registration."""

    def test_recall_memories_in_tool_schemas(self):
        """Test that recall_memories is registered in TOOL_SCHEMAS."""
        from agent_framework.tools.memory import TOOL_SCHEMAS

        names = [s["name"] for s in TOOL_SCHEMAS]
        assert "recall_memories" in names

    def test_recall_memories_schema_properties(self):
        """Test the schema has the expected properties."""
        from agent_framework.tools.memory import TOOL_SCHEMAS

        schema = next(s for s in TOOL_SCHEMAS if s["name"] == "recall_memories")
        props = schema["input_schema"]["properties"]
        assert "query" in props
        assert "limit" in props
        assert "min_score" in props
        assert "category" in props
        assert "agent_name" in props
        assert schema["input_schema"]["required"] == ["query"]
