"""Tests for the RAG tools module."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_framework.storage.rag_store import Document, SearchResult
from agent_framework.tools.rag import (
    add_document,
    delete_document,
    extract_text_from_file,
    extract_text_from_pdf,
    get_document,
    get_rag_stats,
    get_rag_store,
    list_documents,
    search_documents,
)


class TestGetRagStore:
    """Tests for get_rag_store function."""

    def test_get_rag_store_missing_database_url(self, monkeypatch):
        """Test get_rag_store raises error when database URL is missing."""
        from agent_framework.tools import rag

        monkeypatch.setattr(rag, "_rag_store", None)
        monkeypatch.delenv("RAG_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)  # Also check shared URL
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with patch("agent_framework.tools.rag.settings") as mock_settings:
            mock_settings.rag_database_url = None
            mock_settings.openai_api_key = None

            with pytest.raises(ValueError) as exc_info:
                get_rag_store()

            # Should mention both options
            assert "RAG_DATABASE_URL" in str(exc_info.value) or "DATABASE_URL" in str(
                exc_info.value
            )

    def test_get_rag_store_uses_database_url_fallback(self, monkeypatch):
        """Test get_rag_store falls back to DATABASE_URL if RAG_DATABASE_URL not set."""
        from agent_framework.tools import rag

        monkeypatch.setattr(rag, "_rag_store", None)
        monkeypatch.delenv("RAG_DATABASE_URL", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/shared_db")

        with patch("agent_framework.tools.rag.settings") as mock_settings:
            mock_settings.rag_database_url = None
            mock_settings.openai_api_key = "sk-test123"
            mock_settings.rag_embedding_model = "text-embedding-3-small"
            mock_settings.rag_table_name = "test_documents"

            with patch("agent_framework.tools.rag.RAGStore") as mock_store_class:
                mock_store = MagicMock()
                mock_store_class.return_value = mock_store

                result = get_rag_store()

                # Should use DATABASE_URL as fallback
                mock_store_class.assert_called_once_with(
                    database_url="postgresql://localhost/shared_db",
                    openai_api_key="sk-test123",
                    embedding_model="text-embedding-3-small",
                    table_name="test_documents",
                )
                assert result is mock_store

    def test_get_rag_store_missing_openai_key(self, monkeypatch):
        """Test get_rag_store raises error when OpenAI key is missing."""
        from agent_framework.tools import rag

        monkeypatch.setattr(rag, "_rag_store", None)
        monkeypatch.setenv("RAG_DATABASE_URL", "postgresql://localhost/test")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with patch("agent_framework.tools.rag.settings") as mock_settings:
            mock_settings.rag_database_url = "postgresql://localhost/test"
            mock_settings.openai_api_key = None

            with pytest.raises(ValueError) as exc_info:
                get_rag_store()

            assert "OPENAI_API_KEY" in str(exc_info.value)

    def test_get_rag_store_creates_instance(self, monkeypatch):
        """Test get_rag_store creates a new instance with valid config."""
        from agent_framework.tools import rag

        monkeypatch.setattr(rag, "_rag_store", None)

        with patch("agent_framework.tools.rag.settings") as mock_settings:
            mock_settings.rag_database_url = "postgresql://localhost/test"
            mock_settings.openai_api_key = "sk-test123"
            mock_settings.rag_embedding_model = "text-embedding-3-small"
            mock_settings.rag_table_name = "test_documents"

            with patch("agent_framework.tools.rag.RAGStore") as mock_store_class:
                mock_store = MagicMock()
                mock_store_class.return_value = mock_store

                result = get_rag_store()

                mock_store_class.assert_called_once_with(
                    database_url="postgresql://localhost/test",
                    openai_api_key="sk-test123",
                    embedding_model="text-embedding-3-small",
                    table_name="test_documents",
                )
                assert result is mock_store


class TestAddDocument:
    """Tests for add_document function."""

    @pytest.mark.asyncio
    async def test_add_document_success(self):
        """Test add_document returns success response."""
        mock_document = Document(
            id="doc-123",
            content="This is test content for the document.",
            metadata={"source": "test", "title": "Test Doc"},
            content_hash="abc123",
            created_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
        )

        mock_store = AsyncMock()
        mock_store.add_document.return_value = mock_document

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await add_document(
                content="This is test content for the document.",
                metadata={"source": "test", "title": "Test Doc"},
                document_id="doc-123",
            )

        assert result["status"] == "success"
        assert result["action"] == "created"
        assert result["document"]["id"] == "doc-123"
        assert "Successfully added" in result["message"]

    @pytest.mark.asyncio
    async def test_add_document_updated(self):
        """Test add_document identifies updated documents."""
        mock_document = Document(
            id="doc-123",
            content="Updated content",
            metadata={},
            content_hash="abc123",
            created_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 2, 0, 0, 0),  # Different = updated
        )

        mock_store = AsyncMock()
        mock_store.add_document.return_value = mock_document

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await add_document(content="Updated content")

        assert result["status"] == "success"
        assert result["action"] == "updated"

    @pytest.mark.asyncio
    async def test_add_document_content_preview(self):
        """Test add_document truncates long content in preview."""
        long_content = "A" * 300  # More than 200 chars
        mock_document = Document(
            id="doc-123",
            content=long_content,
            metadata={},
            content_hash="abc123",
            created_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
        )

        mock_store = AsyncMock()
        mock_store.add_document.return_value = mock_document

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await add_document(content=long_content)

        assert result["document"]["content_preview"].endswith("...")
        assert len(result["document"]["content_preview"]) == 203  # 200 + "..."
        assert result["document"]["content_length"] == 300

    @pytest.mark.asyncio
    async def test_add_document_validation_error(self):
        """Test add_document handles validation errors when no content provided."""
        # Now with the file_path option, empty content triggers a different error
        result = await add_document(content="")

        assert result["status"] == "error"
        # Should error about needing content or file_path
        assert "content" in result["message"].lower() or "file_path" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_add_document_error_handling(self):
        """Test add_document handles generic errors gracefully."""
        mock_store = AsyncMock()
        mock_store.add_document.side_effect = Exception("Database error")

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await add_document(content="Test content")

        assert result["status"] == "error"
        assert "Failed to add document" in result["message"]


class TestSearchDocuments:
    """Tests for search_documents function."""

    @pytest.mark.asyncio
    async def test_search_documents_success(self):
        """Test search_documents returns results successfully."""
        mock_doc = Document(
            id="doc-1",
            content="Python programming guide",
            metadata={"category": "programming"},
            content_hash="hash1",
            created_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
        )
        mock_results = [SearchResult(document=mock_doc, score=0.85)]

        mock_store = AsyncMock()
        mock_store.search.return_value = mock_results

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await search_documents(query="python programming")

        assert result["status"] == "success"
        assert result["query"] == "python programming"
        assert result["count"] == 1
        assert result["results"][0]["id"] == "doc-1"
        assert result["results"][0]["score"] == 0.85

    @pytest.mark.asyncio
    async def test_search_documents_with_filters(self):
        """Test search_documents passes filters correctly."""
        mock_store = AsyncMock()
        mock_store.search.return_value = []

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            await search_documents(
                query="test",
                top_k=10,
                min_score=0.5,
                metadata_filter={"category": "blog"},
            )

        mock_store.search.assert_called_once_with(
            query="test",
            top_k=10,
            min_score=0.5,
            metadata_filter={"category": "blog"},
        )

    @pytest.mark.asyncio
    async def test_search_documents_no_results(self):
        """Test search_documents handles empty results."""
        mock_store = AsyncMock()
        mock_store.search.return_value = []

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await search_documents(query="nonexistent topic")

        assert result["status"] == "success"
        assert result["count"] == 0
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_search_documents_validation_error(self):
        """Test search_documents handles validation errors."""
        mock_store = AsyncMock()
        mock_store.search.side_effect = ValueError("Query cannot be empty")

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await search_documents(query="")

        assert result["status"] == "error"
        assert "Query cannot be empty" in result["message"]
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_search_documents_error_handling(self):
        """Test search_documents handles errors gracefully."""
        mock_store = AsyncMock()
        mock_store.search.side_effect = Exception("Connection error")

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await search_documents(query="test")

        assert result["status"] == "error"
        assert "Failed to search" in result["message"]
        assert result["results"] == []


class TestGetDocument:
    """Tests for get_document function."""

    @pytest.mark.asyncio
    async def test_get_document_success(self):
        """Test get_document returns document successfully."""
        mock_doc = Document(
            id="doc-123",
            content="Full document content here",
            metadata={"source": "api"},
            content_hash="hash123",
            created_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
        )

        mock_store = AsyncMock()
        mock_store.get_document.return_value = mock_doc

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await get_document(document_id="doc-123")

        assert result["status"] == "success"
        assert result["document"]["id"] == "doc-123"
        assert result["document"]["content"] == "Full document content here"

    @pytest.mark.asyncio
    async def test_get_document_not_found(self):
        """Test get_document handles missing documents."""
        mock_store = AsyncMock()
        mock_store.get_document.return_value = None

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await get_document(document_id="nonexistent")

        assert result["status"] == "not_found"
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_get_document_error_handling(self):
        """Test get_document handles errors gracefully."""
        mock_store = AsyncMock()
        mock_store.get_document.side_effect = Exception("Database error")

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await get_document(document_id="doc-123")

        assert result["status"] == "error"
        assert "Failed to get document" in result["message"]


class TestDeleteDocument:
    """Tests for delete_document function."""

    @pytest.mark.asyncio
    async def test_delete_document_success(self):
        """Test delete_document returns success response."""
        mock_store = AsyncMock()
        mock_store.delete_document.return_value = True

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await delete_document(document_id="doc-123")

        assert result["status"] == "success"
        assert "Successfully deleted" in result["message"]

    @pytest.mark.asyncio
    async def test_delete_document_not_found(self):
        """Test delete_document handles missing documents."""
        mock_store = AsyncMock()
        mock_store.delete_document.return_value = False

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await delete_document(document_id="nonexistent")

        assert result["status"] == "not_found"
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_delete_document_error_handling(self):
        """Test delete_document handles errors gracefully."""
        mock_store = AsyncMock()
        mock_store.delete_document.side_effect = Exception("Delete failed")

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await delete_document(document_id="doc-123")

        assert result["status"] == "error"
        assert "Failed to delete document" in result["message"]


class TestListDocuments:
    """Tests for list_documents function."""

    @pytest.mark.asyncio
    async def test_list_documents_success(self):
        """Test list_documents returns documents successfully."""
        mock_docs = [
            Document(
                id=f"doc-{i}",
                content=f"Content {i}",
                metadata={},
                content_hash=f"hash{i}",
                created_at=datetime(2024, 1, 1, 0, 0, 0),
                updated_at=datetime(2024, 1, 1, 0, 0, 0),
            )
            for i in range(3)
        ]

        mock_store = AsyncMock()
        mock_store.list_documents.return_value = mock_docs

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await list_documents(limit=10, offset=0)

        assert result["status"] == "success"
        assert result["count"] == 3
        assert len(result["documents"]) == 3

    @pytest.mark.asyncio
    async def test_list_documents_enforces_max_limit(self):
        """Test list_documents enforces max limit of 100."""
        mock_store = AsyncMock()
        mock_store.list_documents.return_value = []

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            await list_documents(limit=500)  # Request more than max

        # Should be capped to 100
        mock_store.list_documents.assert_called_once_with(limit=100, offset=0, metadata_filter=None)

    @pytest.mark.asyncio
    async def test_list_documents_with_filter(self):
        """Test list_documents passes metadata filter."""
        mock_store = AsyncMock()
        mock_store.list_documents.return_value = []

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            await list_documents(metadata_filter={"category": "blog"})

        mock_store.list_documents.assert_called_once_with(
            limit=20, offset=0, metadata_filter={"category": "blog"}
        )

    @pytest.mark.asyncio
    async def test_list_documents_error_handling(self):
        """Test list_documents handles errors gracefully."""
        mock_store = AsyncMock()
        mock_store.list_documents.side_effect = Exception("Query error")

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await list_documents()

        assert result["status"] == "error"
        assert "Failed to list documents" in result["message"]
        assert result["documents"] == []


class TestGetRagStats:
    """Tests for get_rag_stats function."""

    @pytest.mark.asyncio
    async def test_get_rag_stats_success(self):
        """Test get_rag_stats returns statistics successfully."""
        mock_stats = {
            "total_documents": 42,
            "oldest_document": "2024-01-01T00:00:00",
            "newest_document": "2024-06-15T00:00:00",
            "categories": {"security": 20, "ml": 15, "uncategorized": 7},
            "sources": {"arxiv": 30, "blog": 12},
            "recent_documents": [
                {"id": "doc-1", "title": "AI Security Paper", "created_at": "2024-06-15T00:00:00"},
                {"id": "doc-2", "title": "ML Research", "created_at": "2024-06-14T00:00:00"},
            ],
            "embedding_model": "text-embedding-3-small",
            "embedding_dimensions": 1536,
        }

        mock_store = AsyncMock()
        mock_store.get_stats.return_value = mock_stats

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await get_rag_stats()

        assert result["status"] == "success"
        assert result["stats"]["total_documents"] == 42
        assert result["stats"]["categories"]["security"] == 20
        assert len(result["stats"]["recent_documents"]) == 2
        assert "42 documents" in result["message"]

    @pytest.mark.asyncio
    async def test_get_rag_stats_error_handling(self):
        """Test get_rag_stats handles errors gracefully."""
        mock_store = AsyncMock()
        mock_store.get_stats.side_effect = Exception("Stats error")

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            result = await get_rag_stats()

        assert result["status"] == "error"
        assert "Failed to get stats" in result["message"]


class TestPDFExtraction:
    """Tests for PDF extraction functionality."""

    def test_extract_text_from_pdf_success(self, tmp_path):
        """Test extracting text from a valid PDF."""
        with patch(
            "agent_framework.tools.rag.pymupdf4llm.to_markdown",
            return_value="# Document Title\n\nPage 1 content",
        ):
            result = extract_text_from_pdf(tmp_path / "test.pdf")

        assert "Page 1 content" in result
        assert "# Document Title" in result

    def test_extract_text_from_pdf_with_markdown_structure(self, tmp_path):
        """Test that PDF extraction preserves markdown structure."""
        markdown_content = """# Main Title

## Section 1

Some content here.

## Section 2

| Column A | Column B |
|----------|----------|
| Value 1  | Value 2  |
"""
        with patch(
            "agent_framework.tools.rag.pymupdf4llm.to_markdown",
            return_value=markdown_content,
        ):
            result = extract_text_from_pdf(tmp_path / "test.pdf")

        assert "# Main Title" in result
        assert "## Section 1" in result
        assert "| Column A |" in result

    def test_extract_text_from_pdf_no_text(self, tmp_path):
        """Test handling PDF with no extractable text."""
        with patch(
            "agent_framework.tools.rag.pymupdf4llm.to_markdown",
            return_value="",
        ):
            with pytest.raises(ValueError) as exc_info:
                extract_text_from_pdf(tmp_path / "empty.pdf")

            assert "No extractable text" in str(exc_info.value)

    def test_extract_text_from_pdf_error_handling(self, tmp_path):
        """Test handling PDF extraction errors."""
        with patch(
            "agent_framework.tools.rag.pymupdf4llm.to_markdown",
            side_effect=Exception("PDF parsing failed"),
        ):
            with pytest.raises(ValueError) as exc_info:
                extract_text_from_pdf(tmp_path / "corrupt.pdf")

            assert "Failed to extract text from PDF" in str(exc_info.value)

    def test_extract_text_from_file_not_found(self):
        """Test extract_text_from_file with non-existent file."""
        with pytest.raises(ValueError) as exc_info:
            extract_text_from_file("/nonexistent/path/doc.pdf")

        assert "File not found" in str(exc_info.value)

    def test_extract_text_from_file_unsupported_type(self, tmp_path):
        """Test extract_text_from_file with unsupported file type."""
        # Create a dummy file
        unsupported_file = tmp_path / "document.docx"
        unsupported_file.write_text("dummy content")

        with pytest.raises(ValueError) as exc_info:
            extract_text_from_file(unsupported_file)

        assert "Unsupported file type" in str(exc_info.value)
        assert ".docx" in str(exc_info.value)

    def test_extract_text_from_file_returns_metadata(self, tmp_path):
        """Test that extract_text_from_file returns proper metadata."""
        # Create a mock PDF file
        pdf_file = tmp_path / "report.pdf"
        pdf_file.write_bytes(b"fake pdf content")

        with patch(
            "agent_framework.tools.rag.pymupdf4llm.to_markdown",
            return_value="# Report\n\nExtracted content",
        ):
            text, metadata = extract_text_from_file(pdf_file)

        assert "Extracted content" in text
        assert metadata["filename"] == "report.pdf"
        assert metadata["file_type"] == "pdf"
        assert "source" in metadata
        assert "file_size_bytes" in metadata


class TestAddDocumentWithFile:
    """Tests for add_document with file_path parameter."""

    @pytest.mark.asyncio
    async def test_add_document_with_file_path(self, tmp_path):
        """Test add_document extracts text from file."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"fake pdf")

        mock_document = Document(
            id="doc-123",
            content="Extracted PDF content",
            metadata={"source": str(pdf_file), "filename": "test.pdf", "file_type": "pdf"},
            content_hash="abc123",
            created_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
        )

        mock_store = AsyncMock()
        mock_store.add_document.return_value = mock_document

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            with patch(
                "agent_framework.tools.rag.extract_text_from_file",
                return_value=(
                    "Extracted PDF content",
                    {
                        "source": str(pdf_file),
                        "filename": "test.pdf",
                        "file_type": "pdf",
                        "file_size_bytes": 100,
                    },
                ),
            ):
                result = await add_document(file_path=str(pdf_file))

        assert result["status"] == "success"
        mock_store.add_document.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_document_file_path_merges_metadata(self, tmp_path):
        """Test that user metadata overrides auto-generated metadata."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"fake pdf")

        mock_document = Document(
            id="doc-123",
            content="Content",
            metadata={},
            content_hash="abc123",
            created_at=datetime(2024, 1, 1, 0, 0, 0),
            updated_at=datetime(2024, 1, 1, 0, 0, 0),
        )

        mock_store = AsyncMock()
        mock_store.add_document.return_value = mock_document

        auto_metadata = {
            "source": str(pdf_file),
            "filename": "test.pdf",
            "file_type": "pdf",
            "file_size_bytes": 100,
        }

        with patch("agent_framework.tools.rag.get_rag_store", return_value=mock_store):
            with patch(
                "agent_framework.tools.rag.extract_text_from_file",
                return_value=("Content", auto_metadata),
            ):
                await add_document(
                    file_path=str(pdf_file),
                    metadata={"title": "Custom Title", "source": "override_source"},
                )

        # Check that metadata was merged correctly
        call_kwargs = mock_store.add_document.call_args[1]
        assert call_kwargs["metadata"]["title"] == "Custom Title"
        assert call_kwargs["metadata"]["source"] == "override_source"  # User override
        assert call_kwargs["metadata"]["filename"] == "test.pdf"  # Auto-generated

    @pytest.mark.asyncio
    async def test_add_document_no_content_or_file(self):
        """Test add_document errors when neither content nor file_path provided."""
        result = await add_document()

        assert result["status"] == "error"
        assert "content" in result["message"].lower() or "file_path" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_add_document_file_extraction_error(self, tmp_path):
        """Test add_document handles file extraction errors."""
        with patch(
            "agent_framework.tools.rag.extract_text_from_file",
            side_effect=ValueError("Failed to extract text"),
        ):
            result = await add_document(file_path="/path/to/bad.pdf")

        assert result["status"] == "error"
        assert "Failed to extract text" in result["message"]
