"""Tests for the RAG storage module."""

from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_framework.storage.rag_store import (
    EMBEDDING_DIMENSIONS,
    Document,
    RAGStore,
    SearchResult,
)


def create_mock_pool(mock_conn):
    """Create a properly mocked asyncpg pool."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def acquire():
        yield mock_conn

    mock_pool.acquire = acquire
    mock_pool.close = AsyncMock()
    return mock_pool


class TestDocument:
    """Tests for the Document model."""

    def test_document_creation(self):
        """Test creating a document with all fields."""
        doc = Document(
            id="doc-123",
            content="Test content",
            metadata={"source": "test"},
            content_hash="abc123",
            created_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
        )

        assert doc.id == "doc-123"
        assert doc.content == "Test content"
        assert doc.metadata == {"source": "test"}
        assert doc.content_hash == "abc123"

    def test_document_to_dict(self):
        """Test converting document to dictionary."""
        doc = Document(
            id="doc-123",
            content="Test content",
            metadata={"key": "value"},
            content_hash="abc123",
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            updated_at=datetime(2024, 1, 2, 12, 0, 0),
        )

        result = doc.to_dict()

        assert result["id"] == "doc-123"
        assert result["content"] == "Test content"
        assert result["metadata"] == {"key": "value"}
        assert result["created_at"] == "2024-01-01T12:00:00"
        assert result["updated_at"] == "2024-01-02T12:00:00"

    def test_document_default_metadata(self):
        """Test document with default empty metadata."""
        doc = Document(
            id="doc-123",
            content="Test",
            content_hash="hash",
        )

        assert doc.metadata == {}


class TestSearchResult:
    """Tests for the SearchResult model."""

    def test_search_result_creation(self):
        """Test creating a search result."""
        doc = Document(
            id="doc-1",
            content="Test",
            content_hash="hash",
        )
        result = SearchResult(document=doc, score=0.85)

        assert result.document.id == "doc-1"
        assert result.score == 0.85


class TestRAGStore:
    """Tests for the RAGStore class."""

    def test_rag_store_init(self):
        """Test RAGStore initialization."""
        with patch("agent_framework.storage.rag_store.AsyncOpenAI") as mock_openai:
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
                embedding_model="text-embedding-3-small",
                table_name="custom_table",
            )

            assert store.database_url == "postgresql://localhost/test"
            assert store.embedding_model == "text-embedding-3-small"
            assert store.table_name == "custom_table"
            mock_openai.assert_called_once_with(api_key="sk-test")

    def test_generate_content_hash(self):
        """Test content hash generation."""
        with patch("agent_framework.storage.rag_store.AsyncOpenAI"):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )

            hash1 = store._generate_content_hash("test content")
            hash2 = store._generate_content_hash("test content")
            hash3 = store._generate_content_hash("different content")

            assert hash1 == hash2  # Same content = same hash
            assert hash1 != hash3  # Different content = different hash
            assert len(hash1) == 32  # SHA256 truncated to 32 chars

    @pytest.mark.asyncio
    async def test_get_embedding(self):
        """Test embedding generation."""
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * EMBEDDING_DIMENSIONS)]

        mock_openai = AsyncMock()
        mock_openai.embeddings.create.return_value = mock_response

        with patch("agent_framework.storage.rag_store.AsyncOpenAI", return_value=mock_openai):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )
            store._openai = mock_openai

            embedding = await store._get_embedding("test text")

            assert len(embedding) == EMBEDDING_DIMENSIONS
            mock_openai.embeddings.create.assert_called_once_with(
                model="text-embedding-3-small",
                input="test text",
            )

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self):
        """Test initialize creates required tables and indexes."""
        mock_conn = AsyncMock()
        mock_pool = create_mock_pool(mock_conn)

        with patch("agent_framework.storage.rag_store.AsyncOpenAI"):
            with patch(
                "agent_framework.storage.rag_store.asyncpg.create_pool",
                new=AsyncMock(return_value=mock_pool),
            ):
                store = RAGStore(
                    database_url="postgresql://localhost/test",
                    openai_api_key="sk-test",
                )

                await store.initialize()

                # Check that required SQL was executed
                calls = [call[0][0] for call in mock_conn.execute.call_args_list]
                assert any("CREATE EXTENSION IF NOT EXISTS vector" in call for call in calls)
                assert any("CREATE TABLE IF NOT EXISTS" in call for call in calls)
                assert any("CREATE INDEX" in call for call in calls)

    @pytest.mark.asyncio
    async def test_add_document_new(self):
        """Test adding a new document."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None  # No existing doc
        mock_pool = create_mock_pool(mock_conn)

        mock_openai = AsyncMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * EMBEDDING_DIMENSIONS)]
        mock_openai.embeddings.create.return_value = mock_response

        with patch("agent_framework.storage.rag_store.AsyncOpenAI", return_value=mock_openai):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )
            store._openai = mock_openai
            store._pool = mock_pool

            result = await store.add_document(
                content="Test document content",
                metadata={"source": "test"},
                document_id="doc-123",
            )

            assert result.id == "doc-123"
            assert result.content == "Test document content"
            assert result.metadata == {"source": "test"}

    @pytest.mark.asyncio
    async def test_add_document_empty_content(self):
        """Test adding document with empty content raises error."""
        with patch("agent_framework.storage.rag_store.AsyncOpenAI"):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )

            with pytest.raises(ValueError) as exc_info:
                await store.add_document(content="")

            assert "empty" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        """Test search with empty query raises error."""
        with patch("agent_framework.storage.rag_store.AsyncOpenAI"):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )

            with pytest.raises(ValueError) as exc_info:
                await store.search(query="")

            assert "empty" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """Test search returns properly formatted results."""
        mock_row = {
            "id": "doc-1",
            "content": "Python tutorial",
            "metadata": {"category": "programming"},
            "content_hash": "hash1",
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
            "similarity": 0.85,
        }

        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [mock_row]
        mock_pool = create_mock_pool(mock_conn)

        mock_openai = AsyncMock()
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * EMBEDDING_DIMENSIONS)]
        mock_openai.embeddings.create.return_value = mock_response

        with patch("agent_framework.storage.rag_store.AsyncOpenAI", return_value=mock_openai):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )
            store._openai = mock_openai
            store._pool = mock_pool

            results = await store.search(query="python", top_k=5)

            assert len(results) == 1
            assert results[0].document.id == "doc-1"
            assert results[0].score == 0.85

    @pytest.mark.asyncio
    async def test_get_document_found(self):
        """Test getting an existing document."""
        mock_row = {
            "id": "doc-123",
            "content": "Test content",
            "metadata": {"key": "value"},
            "content_hash": "hash123",
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = mock_row
        mock_pool = create_mock_pool(mock_conn)

        with patch("agent_framework.storage.rag_store.AsyncOpenAI"):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )
            store._pool = mock_pool

            result = await store.get_document("doc-123")

            assert result is not None
            assert result.id == "doc-123"
            assert result.content == "Test content"

    @pytest.mark.asyncio
    async def test_get_document_not_found(self):
        """Test getting a non-existent document."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow.return_value = None
        mock_pool = create_mock_pool(mock_conn)

        with patch("agent_framework.storage.rag_store.AsyncOpenAI"):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )
            store._pool = mock_pool

            result = await store.get_document("nonexistent")

            assert result is None

    @pytest.mark.asyncio
    async def test_delete_document_success(self):
        """Test deleting an existing document."""
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "DELETE 1"
        mock_pool = create_mock_pool(mock_conn)

        with patch("agent_framework.storage.rag_store.AsyncOpenAI"):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )
            store._pool = mock_pool

            result = await store.delete_document("doc-123")

            assert result is True

    @pytest.mark.asyncio
    async def test_delete_document_not_found(self):
        """Test deleting a non-existent document."""
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = "DELETE 0"
        mock_pool = create_mock_pool(mock_conn)

        with patch("agent_framework.storage.rag_store.AsyncOpenAI"):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )
            store._pool = mock_pool

            result = await store.delete_document("nonexistent")

            assert result is False

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting store statistics."""
        mock_conn = AsyncMock()
        mock_conn.fetchval.side_effect = [
            42,  # total count
            datetime(2024, 1, 1),  # oldest
            datetime(2024, 6, 1),  # newest
        ]
        mock_pool = create_mock_pool(mock_conn)

        with patch("agent_framework.storage.rag_store.AsyncOpenAI"):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )
            store._pool = mock_pool

            stats = await store.get_stats()

            assert stats["total_documents"] == 42
            assert stats["oldest_document"] == "2024-01-01T00:00:00"
            assert stats["newest_document"] == "2024-06-01T00:00:00"
            assert stats["embedding_model"] == "text-embedding-3-small"
            assert stats["embedding_dimensions"] == EMBEDDING_DIMENSIONS

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing the database connection."""
        mock_conn = AsyncMock()
        mock_pool = create_mock_pool(mock_conn)

        with patch("agent_framework.storage.rag_store.AsyncOpenAI"):
            store = RAGStore(
                database_url="postgresql://localhost/test",
                openai_api_key="sk-test",
            )
            store._pool = mock_pool

            await store.close()

            mock_pool.close.assert_called_once()
            assert store._pool is None
