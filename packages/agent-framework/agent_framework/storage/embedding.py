"""Shared embedding client for generating and formatting vector embeddings.

Reusable across RAGStore, DatabaseMemoryStore, and any future
component that needs OpenAI embeddings with pgvector storage.
"""

import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Default embedding model and dimensions
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


class EmbeddingClient:
    """Client for generating text embeddings via OpenAI API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_EMBEDDING_MODEL,
    ) -> None:
        self._openai = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def get_embedding(self, text: str) -> list[float]:
        """Generate an embedding vector for *text*."""
        response = await self._openai.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding

    @staticmethod
    def embedding_to_pgvector(embedding: list[float]) -> str:
        """Convert an embedding list to pgvector string format."""
        return "[" + ",".join(str(x) for x in embedding) + "]"
