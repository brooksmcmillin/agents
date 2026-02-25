"""Shared embedding client for generating and formatting vector embeddings.

Reusable across RAGStore, DatabaseMemoryStore, and any future
component that needs OpenAI embeddings with pgvector storage.

Note: ``EMBEDDING_DIMENSIONS`` is fixed at 1536, which matches the default
``text-embedding-3-small`` model.  If you use a different model (e.g.
``text-embedding-3-large`` with 3072 dimensions), the pgvector column
DDL and HNSW index must be updated to match.
"""

import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Default embedding model and dimensions.
# The pgvector column DDL uses this constant; changing the model without
# updating the column size will cause insert failures.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Maximum characters sent to the embedding API to avoid token-limit errors
# and unexpected cost.  OpenAI's text-embedding-3-small supports ~8 191
# tokens (~32 K chars); we use a conservative cap.
MAX_EMBEDDING_INPUT_CHARS = 16_000


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
        """Generate an embedding vector for *text*.

        Input is truncated to ``MAX_EMBEDDING_INPUT_CHARS`` to stay within
        the model's token limit and control API costs.
        """
        if len(text) > MAX_EMBEDDING_INPUT_CHARS:
            text = text[:MAX_EMBEDDING_INPUT_CHARS]
        response = await self._openai.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding

    @staticmethod
    def embedding_to_pgvector(embedding: list[float]) -> str:
        """Convert an embedding list to pgvector string format."""
        return "[" + ",".join(str(x) for x in embedding) + "]"
