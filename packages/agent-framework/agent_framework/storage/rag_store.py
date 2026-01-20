"""RAG (Retrieval-Augmented Generation) storage using PostgreSQL with pgvector.

This module provides vector-based document storage for semantic search,
enabling the agent to store and retrieve documents based on meaning
rather than just keyword matching.

Requirements:
- PostgreSQL with pgvector extension installed
- OpenAI API key for generating embeddings

Environment variables:
- RAG_DATABASE_URL: PostgreSQL connection string
- OPENAI_API_KEY: For embedding generation
"""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

import asyncpg
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agent_framework.utils.errors import DatabaseNotInitializedError

from .query_builder import MetadataFilterBuilder

logger = logging.getLogger(__name__)

# Default embedding model and dimensions
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


class Document(BaseModel):
    """A document stored in the RAG system."""

    id: str = Field(..., description="Unique identifier for this document")
    content: str = Field(..., description="The document text content")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Optional metadata (source, title, etc.)"
    )
    content_hash: str = Field(..., description="Hash of content for deduplication")
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="When this document was created"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="When this document was last updated"
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class SearchResult(BaseModel):
    """A search result with similarity score."""

    document: Document
    score: float = Field(..., description="Similarity score (0-1, higher is more similar)")


class RAGStore:
    """
    PostgreSQL + pgvector storage for RAG documents.

    Stores documents with their embeddings for semantic search.
    Uses OpenAI's embedding API to generate vector representations.
    """

    def __init__(
        self,
        database_url: str,
        openai_api_key: str | None = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        table_name: str = "rag_documents",
    ):
        """
        Initialize RAG store.

        Args:
            database_url: PostgreSQL connection string
            openai_api_key: OpenAI API key for embeddings (can use OPENAI_API_KEY env var)
            embedding_model: OpenAI embedding model to use
            table_name: Name of the table to store documents
        """
        self.database_url = database_url
        self.embedding_model = embedding_model
        # Validate table_name to prevent SQL injection - must be a valid identifier
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
            raise ValueError(
                f"Invalid table_name '{table_name}': must be a valid SQL identifier "
                "(alphanumeric and underscores only, cannot start with a number)"
            )
        self.table_name = table_name
        self._pool: asyncpg.Pool | None = None
        self._openai = AsyncOpenAI(api_key=openai_api_key)

        logger.info(f"Initialized RAG store with table: {table_name}")

    async def initialize(self) -> None:
        """Initialize the database connection and create tables if needed."""
        if self._pool is not None:
            return

        logger.info("Connecting to PostgreSQL database...")
        self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=10)

        # Create pgvector extension and table if they don't exist
        async with self._pool.acquire() as conn:
            # Enable pgvector extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")

            # Create documents table
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata JSONB DEFAULT '{{}}',
                    content_hash TEXT NOT NULL,
                    embedding vector({EMBEDDING_DIMENSIONS}),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes for efficient querying
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_content_hash
                ON {self.table_name}(content_hash)
            """)

            # Create HNSW index for fast similarity search
            # HNSW is faster for queries but slower for inserts
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_embedding_hnsw
                ON {self.table_name}
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """)

        logger.info("Database initialized successfully")

    async def close(self) -> None:
        """Close the database connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("Database connection closed")

    async def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding for text using OpenAI."""
        response = await self._openai.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        return response.data[0].embedding

    def _generate_content_hash(self, content: str) -> str:
        """Generate a hash of the content for deduplication."""
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _embedding_to_pgvector(self, embedding: list[float]) -> str:
        """Convert embedding list to pgvector string format."""
        return "[" + ",".join(str(x) for x in embedding) + "]"

    async def add_document(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        document_id: str | None = None,
    ) -> Document:
        """
        Add a document to the RAG store.

        Args:
            content: The document text to store
            metadata: Optional metadata (source, title, author, etc.)
            document_id: Optional custom ID (auto-generated if not provided)

        Returns:
            The created Document object

        Raises:
            ValueError: If content is empty
        """
        if not content or not content.strip():
            raise ValueError("Document content cannot be empty")

        await self.initialize()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        doc_id = document_id or str(uuid.uuid4())
        content_hash = self._generate_content_hash(content)
        now = datetime.utcnow()

        # Generate embedding
        logger.info(f"Generating embedding for document {doc_id}")
        embedding = await self._get_embedding(content)

        # Insert or update document
        async with self._pool.acquire() as conn:
            # Check if document with same ID exists
            # table_name is validated in __init__ to be a safe SQL identifier
            existing = await conn.fetchrow(
                f"SELECT id FROM {self.table_name} WHERE id = $1",  # nosec B608
                doc_id,
            )

            if existing:
                # Update existing document
                await conn.execute(
                    f"""
                    UPDATE {self.table_name}
                    SET content = $2, metadata = $3, content_hash = $4,
                        embedding = $5::vector, updated_at = $6
                    WHERE id = $1
                    """,  # nosec B608
                    doc_id,
                    content,
                    json.dumps(metadata or {}),
                    content_hash,
                    self._embedding_to_pgvector(embedding),
                    now,
                )
                logger.info(f"Updated document: {doc_id}")
                created_at = await conn.fetchval(
                    f"SELECT created_at FROM {self.table_name} WHERE id = $1",  # nosec B608
                    doc_id,
                )
            else:
                # Insert new document
                await conn.execute(
                    f"""
                    INSERT INTO {self.table_name}
                    (id, content, metadata, content_hash, embedding, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5::vector, $6, $6)
                    """,  # nosec B608
                    doc_id,
                    content,
                    json.dumps(metadata or {}),
                    content_hash,
                    self._embedding_to_pgvector(embedding),
                    now,
                )
                logger.info(f"Created document: {doc_id}")
                created_at = now

        return Document(
            id=doc_id,
            content=content,
            metadata=metadata or {},
            content_hash=content_hash,
            created_at=created_at,
            updated_at=now,
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """
        Search for similar documents using semantic similarity.

        Args:
            query: The search query text
            top_k: Maximum number of results to return
            min_score: Minimum similarity score (0-1) to include in results
            metadata_filter: Optional filter on metadata fields

        Returns:
            List of SearchResult objects sorted by similarity (highest first)
        """
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty")

        await self.initialize()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        # Generate query embedding
        logger.info(f"Searching for: {query[:50]}...")
        query_embedding = await self._get_embedding(query)
        query_embedding_str = self._embedding_to_pgvector(query_embedding)

        # Build query with optional metadata filter
        # table_name is validated in __init__ to be a safe SQL identifier
        base_query = f"""
            SELECT
                id, content, metadata, content_hash, created_at, updated_at,
                1 - (embedding <=> $1::vector) as similarity
            FROM {self.table_name}
        """  # nosec B608

        # Use MetadataFilterBuilder for consistent query building
        builder = MetadataFilterBuilder(base_params=[query_embedding_str])
        if metadata_filter:
            builder.add_metadata_filter(metadata_filter)

        if builder.has_conditions():
            base_query += " WHERE " + builder.get_where_clause()

        base_query += f"""
            ORDER BY embedding <=> $1::vector
            LIMIT {top_k}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(base_query, *builder.get_params())

        results = []
        for row in rows:
            score = float(row["similarity"])
            if score >= min_score:
                doc = Document(
                    id=row["id"],
                    content=row["content"],
                    metadata=dict(row["metadata"]) if row["metadata"] else {},
                    content_hash=row["content_hash"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                results.append(SearchResult(document=doc, score=score))

        logger.info(f"Found {len(results)} results for query")
        return results

    async def get_document(self, document_id: str) -> Document | None:
        """
        Retrieve a specific document by ID.

        Args:
            document_id: The document identifier

        Returns:
            Document object if found, None otherwise
        """
        await self.initialize()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT id, content, metadata, content_hash, created_at, updated_at
                FROM {self.table_name}
                WHERE id = $1
                """,  # nosec B608
                document_id,
            )

        if not row:
            return None

        return Document(
            id=row["id"],
            content=row["content"],
            metadata=dict(row["metadata"]) if row["metadata"] else {},
            content_hash=row["content_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def delete_document(self, document_id: str) -> bool:
        """
        Delete a document from the RAG store.

        Args:
            document_id: The document identifier

        Returns:
            True if deleted, False if not found
        """
        await self.initialize()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            result = await conn.execute(f"DELETE FROM {self.table_name} WHERE id = $1", document_id)  # nosec B608

        deleted = result == "DELETE 1"
        if deleted:
            logger.info(f"Deleted document: {document_id}")
        else:
            logger.info(f"Document not found: {document_id}")

        return deleted

    async def list_documents(
        self,
        limit: int = 100,
        offset: int = 0,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[Document]:
        """
        List documents in the RAG store.

        Args:
            limit: Maximum number of documents to return
            offset: Number of documents to skip
            metadata_filter: Optional filter on metadata fields

        Returns:
            List of Document objects
        """
        await self.initialize()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        # table_name is validated in __init__ to be a safe SQL identifier
        base_query = f"""
            SELECT id, content, metadata, content_hash, created_at, updated_at
            FROM {self.table_name}
        """  # nosec B608

        # Use MetadataFilterBuilder for consistent query building
        builder = MetadataFilterBuilder()
        if metadata_filter:
            builder.add_metadata_filter(metadata_filter)

        query = builder.build_query_with_filter(
            base_query=base_query,
            order_by="created_at DESC",
            limit=limit,
            offset=offset,
        )

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *builder.get_params())

        return [
            Document(
                id=row["id"],
                content=row["content"],
                metadata=dict(row["metadata"]) if row["metadata"] else {},
                content_hash=row["content_hash"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def get_stats(self) -> dict[str, Any]:
        """Get statistics about the RAG store including content summary."""
        await self.initialize()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        # table_name is validated in __init__ to be a safe SQL identifier
        async with self._pool.acquire() as conn:
            total_count = await conn.fetchval(f"SELECT COUNT(*) FROM {self.table_name}")  # nosec B608

            oldest = await conn.fetchval(f"SELECT MIN(created_at) FROM {self.table_name}")  # nosec B608

            newest = await conn.fetchval(f"SELECT MAX(created_at) FROM {self.table_name}")  # nosec B608

            # Get category breakdown from metadata
            category_rows = await conn.fetch(f"""
                SELECT
                    COALESCE(metadata->>'category', 'uncategorized') as category,
                    COUNT(*) as count
                FROM {self.table_name}
                GROUP BY metadata->>'category'
                ORDER BY count DESC
                LIMIT 20
            """)  # nosec B608
            categories = {row["category"]: row["count"] for row in category_rows}

            # Get source breakdown from metadata
            source_rows = await conn.fetch(f"""
                SELECT
                    COALESCE(metadata->>'source', 'unknown') as source,
                    COUNT(*) as count
                FROM {self.table_name}
                GROUP BY metadata->>'source'
                ORDER BY count DESC
                LIMIT 10
            """)  # nosec B608
            sources = {row["source"]: row["count"] for row in source_rows}

            # Get recent document titles/previews
            recent_rows = await conn.fetch(f"""
                SELECT
                    id,
                    COALESCE(metadata->>'title', LEFT(content, 100)) as title,
                    created_at
                FROM {self.table_name}
                ORDER BY created_at DESC
                LIMIT 5
            """)  # nosec B608
            recent_documents = [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "created_at": row["created_at"].isoformat(),
                }
                for row in recent_rows
            ]

        return {
            "total_documents": total_count,
            "oldest_document": oldest.isoformat() if oldest else None,
            "newest_document": newest.isoformat() if newest else None,
            "categories": categories,
            "sources": sources,
            "recent_documents": recent_documents,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": EMBEDDING_DIMENSIONS,
        }
