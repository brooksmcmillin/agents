"""RAG (Retrieval-Augmented Generation) tools for the agent.

These tools allow the agent to add documents to a knowledge base,
search for relevant documents using semantic similarity, and
manage the document collection.

Configure via environment variables:
    RAG_DATABASE_URL: PostgreSQL connection string (or use DATABASE_URL)
    OPENAI_API_KEY: Required for generating embeddings
"""

import logging
import os
from pathlib import Path
from typing import Any

import pymupdf4llm

from ..core.config import settings
from ..storage.rag_store import RAGStore

logger = logging.getLogger(__name__)

# Global RAG store instance
_rag_store: RAGStore | None = None

# Supported file extensions for automatic text extraction
SUPPORTED_EXTENSIONS = {".pdf"}


def extract_text_from_pdf(file_path: Path) -> str:
    """
    Extract text content from a PDF file as clean markdown.

    Uses PyMuPDF (via pymupdf4llm) for better extraction of:
    - Complex layouts (academic papers, multi-column documents)
    - Tables and figures
    - Mathematical notation
    - Document structure (headings, lists, etc.)

    Args:
        file_path: Path to the PDF file

    Returns:
        Extracted text content as markdown

    Raises:
        ValueError: If the file cannot be read or has no extractable text
    """
    try:
        # pymupdf4llm extracts PDF content as clean markdown
        # This handles complex layouts, tables, and preserves structure
        result = pymupdf4llm.to_markdown(str(file_path))

        # to_markdown can return str or list[dict] depending on options
        if isinstance(result, list):
            # Join page results if returned as list
            markdown_text = "\n\n".join(
                page.get("text", "") if isinstance(page, dict) else str(page) for page in result
            )
        else:
            markdown_text = result

        if not markdown_text or not markdown_text.strip():
            raise ValueError(f"No extractable text found in PDF: {file_path}")

        return markdown_text

    except Exception as e:
        raise ValueError(f"Failed to extract text from PDF: {e}") from e


def extract_text_from_file(
    file_path: str | Path,
    allowed_dir: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Extract text from a file based on its extension.

    Args:
        file_path: Path to the file
        allowed_dir: Optional directory to restrict file access to (security)

    Returns:
        Tuple of (extracted_text, auto_metadata)

    Raises:
        ValueError: If file type is not supported, extraction fails, or path is unsafe
    """
    # Resolve to absolute path to prevent traversal attacks
    path = Path(file_path).resolve()

    # Security: If allowed_dir specified, ensure file is within it
    if allowed_dir:
        allowed = Path(allowed_dir).resolve()
        try:
            path.relative_to(allowed)
        except ValueError:
            raise ValueError(
                f"Access denied: file path '{file_path}' is outside allowed directory '{allowed_dir}'"
            )

    # Security: Block access to system directories
    path_str = str(path)
    system_dirs = ("/etc/", "/sys/", "/proc/", "/dev/", "/boot/")
    if path.is_absolute() and any(path_str.startswith(d) for d in system_dirs):
        raise ValueError(f"Access denied: system directory access not allowed: {file_path}")

    if not path.exists():
        raise ValueError(f"File not found: {file_path}")

    extension = path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {extension}. "
            f"Supported types: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    # Extract text based on file type
    if extension == ".pdf":
        text = extract_text_from_pdf(path)
    else:
        # This shouldn't happen due to the check above, but just in case
        raise ValueError(f"No extractor for file type: {extension}")

    # Build auto-generated metadata
    auto_metadata = {
        "source": str(path.absolute()),
        "filename": path.name,
        "file_type": extension[1:],  # Remove the leading dot
        "file_size_bytes": path.stat().st_size,
    }

    return text, auto_metadata


def get_rag_store() -> RAGStore:
    """Get or create the global RAG store instance."""
    global _rag_store
    if _rag_store is None:
        # Try RAG-specific URL first, then fall back to shared DATABASE_URL
        # This allows using the same database as the memory backend
        database_url = (
            settings.rag_database_url
            or os.environ.get("RAG_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
        )
        if not database_url:
            raise ValueError(
                "RAG_DATABASE_URL or DATABASE_URL environment variable required. "
                "Set it to your PostgreSQL connection string."
            )

        openai_api_key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
        if not openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable is required for generating embeddings."
            )

        _rag_store = RAGStore(
            database_url=database_url,
            openai_api_key=openai_api_key,
            embedding_model=settings.rag_embedding_model,
            table_name=settings.rag_table_name,
        )
    return _rag_store


async def add_document(
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
    document_id: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    """
    Add a document to the RAG knowledge base.

    Use this to store documents that should be searchable by the agent.
    Documents are converted to vector embeddings for semantic search.

    You can provide content directly OR specify a file_path to extract text from.
    Supported file types: PDF

    Args:
        content: The document text content to store (required if file_path not provided)
        metadata: Optional metadata for the document:
            - source: Where the document came from (e.g., URL, filename)
            - title: Document title
            - author: Document author
            - category: Document category for filtering
            - Any other key-value pairs you want to store
        document_id: Optional custom ID. If not provided, a UUID is generated.
            If provided and document exists, it will be updated.
        file_path: Path to a file to extract text from (PDF supported).
            If provided, content is extracted automatically and metadata
            is populated with file info (source, filename, file_type).

    Returns:
        Confirmation with the stored document details

    Example with content:
        add_document(content="My text...", metadata={"category": "blog"})

    Example with file:
        add_document(file_path="/path/to/document.pdf", metadata={"category": "reports"})
    """
    logger.info(f"Adding document to RAG store (id={document_id}, file={file_path})")

    try:
        # Handle file extraction if file_path is provided
        if file_path:
            extracted_text, auto_metadata = extract_text_from_file(file_path)
            content = extracted_text

            # Merge auto-generated metadata with user-provided metadata
            # User-provided metadata takes precedence
            final_metadata = {**auto_metadata, **(metadata or {})}
            metadata = final_metadata

            logger.info(f"Extracted {len(content)} characters from {auto_metadata['filename']}")

        # Validate that we have content
        if not content:
            raise ValueError(
                "Either 'content' or 'file_path' must be provided. Supported file types: PDF"
            )

        store = get_rag_store()
        document = await store.add_document(
            content=content,
            metadata=metadata,
            document_id=document_id,
        )

        return {
            "status": "success",
            "action": "updated" if document.created_at != document.updated_at else "created",
            "document": {
                "id": document.id,
                "content_preview": document.content[:200] + "..."
                if len(document.content) > 200
                else document.content,
                "content_length": len(document.content),
                "metadata": document.metadata,
                "created_at": document.created_at.isoformat(),
                "updated_at": document.updated_at.isoformat(),
            },
            "message": f"Successfully added document: {document.id}",
        }

    except ValueError as e:
        logger.error(f"Validation error adding document: {e}")
        return {
            "status": "error",
            "message": str(e),
        }
    except Exception as e:
        logger.error(f"Failed to add document: {e}")
        return {
            "status": "error",
            "message": f"Failed to add document: {e}",
        }


async def search_documents(
    query: str,
    top_k: int = 5,
    min_score: float = 0.0,
    metadata_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Search for documents in the RAG knowledge base using semantic similarity.

    Use this to find documents that are semantically related to a query.
    Unlike keyword search, this finds documents based on meaning.

    Args:
        query: The search query text. Describe what you're looking for.
        top_k: Maximum number of results to return (default: 5)
        min_score: Minimum similarity score 0-1 (default: 0, returns all)
            - 0.0-0.3: Loosely related
            - 0.3-0.5: Somewhat related
            - 0.5-0.7: Related
            - 0.7-1.0: Highly related
        metadata_filter: Optional filter on metadata fields.
            Example: {"category": "blog"} to only search blog posts

    Returns:
        List of matching documents with similarity scores
    """
    logger.info(f"Searching RAG store for: {query[:50]}...")

    try:
        store = get_rag_store()
        results = await store.search(
            query=query,
            top_k=top_k,
            min_score=min_score,
            metadata_filter=metadata_filter,
        )

        return {
            "status": "success",
            "query": query,
            "count": len(results),
            "results": [
                {
                    "id": r.document.id,
                    "content": r.document.content,
                    "metadata": r.document.metadata,
                    "score": round(r.score, 4),
                    "created_at": r.document.created_at.isoformat(),
                }
                for r in results
            ],
            "message": f"Found {len(results)} documents matching query",
        }

    except ValueError as e:
        logger.error(f"Validation error searching: {e}")
        return {
            "status": "error",
            "message": str(e),
            "results": [],
        }
    except Exception as e:
        logger.error(f"Failed to search documents: {e}")
        return {
            "status": "error",
            "message": f"Failed to search: {e}",
            "results": [],
        }


async def get_document(document_id: str) -> dict[str, Any]:
    """
    Retrieve a specific document from the RAG knowledge base by ID.

    Use this when you know the exact document ID you want to retrieve.

    Args:
        document_id: The unique identifier of the document

    Returns:
        The document details if found, or error if not found
    """
    logger.info(f"Getting document: {document_id}")

    try:
        store = get_rag_store()
        document = await store.get_document(document_id)

        if document is None:
            return {
                "status": "not_found",
                "message": f"Document not found: {document_id}",
            }

        return {
            "status": "success",
            "document": {
                "id": document.id,
                "content": document.content,
                "metadata": document.metadata,
                "created_at": document.created_at.isoformat(),
                "updated_at": document.updated_at.isoformat(),
            },
            "message": f"Retrieved document: {document_id}",
        }

    except Exception as e:
        logger.error(f"Failed to get document {document_id}: {e}")
        return {
            "status": "error",
            "message": f"Failed to get document: {e}",
        }


async def delete_document(document_id: str) -> dict[str, Any]:
    """
    Delete a document from the RAG knowledge base.

    Use this to remove documents that are no longer needed.

    Args:
        document_id: The unique identifier of the document to delete

    Returns:
        Confirmation of deletion or error if not found
    """
    logger.info(f"Deleting document: {document_id}")

    try:
        store = get_rag_store()
        deleted = await store.delete_document(document_id)

        if deleted:
            return {
                "status": "success",
                "message": f"Successfully deleted document: {document_id}",
            }
        else:
            return {
                "status": "not_found",
                "message": f"Document not found: {document_id}",
            }

    except Exception as e:
        logger.error(f"Failed to delete document {document_id}: {e}")
        return {
            "status": "error",
            "message": f"Failed to delete document: {e}",
        }


async def list_documents(
    limit: int = 20,
    offset: int = 0,
    metadata_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    List documents in the RAG knowledge base.

    Use this to browse documents or see what's stored.

    Args:
        limit: Maximum number of documents to return (default: 20, max: 100)
        offset: Number of documents to skip for pagination (default: 0)
        metadata_filter: Optional filter on metadata fields

    Returns:
        List of documents with their metadata
    """
    logger.info(f"Listing documents (limit={limit}, offset={offset})")

    try:
        # Enforce max limit
        limit = min(limit, 100)

        store = get_rag_store()
        documents = await store.list_documents(
            limit=limit,
            offset=offset,
            metadata_filter=metadata_filter,
        )

        return {
            "status": "success",
            "count": len(documents),
            "offset": offset,
            "documents": [
                {
                    "id": doc.id,
                    "content_preview": doc.content[:200] + "..."
                    if len(doc.content) > 200
                    else doc.content,
                    "content_length": len(doc.content),
                    "metadata": doc.metadata,
                    "created_at": doc.created_at.isoformat(),
                }
                for doc in documents
            ],
            "message": f"Retrieved {len(documents)} documents",
        }

    except Exception as e:
        logger.error(f"Failed to list documents: {e}")
        return {
            "status": "error",
            "message": f"Failed to list documents: {e}",
            "documents": [],
        }


async def get_rag_stats() -> dict[str, Any]:
    """
    Get statistics about the RAG knowledge base.

    Use this to understand the state of the document store.

    Returns:
        Statistics including document count, date range, and embedding info
    """
    logger.info("Getting RAG store statistics")

    try:
        store = get_rag_store()
        stats = await store.get_stats()

        return {
            "status": "success",
            "stats": stats,
            "message": f"RAG store contains {stats['total_documents']} documents",
        }

    except Exception as e:
        logger.error(f"Failed to get RAG stats: {e}")
        return {
            "status": "error",
            "message": f"Failed to get stats: {e}",
        }
