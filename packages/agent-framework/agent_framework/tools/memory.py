"""Memory tools for the agent.

These tools allow the agent to save and retrieve important information
across conversations and sessions.

Supports two backends:
- File-based (default): Local JSON storage, good for single-machine use
- Database: PostgreSQL storage, enables cross-machine memory portability

Supports agent-level isolation:
- Each agent can have its own memory namespace
- Memories saved by one agent won't be visible to other agents
- Use agent_name parameter to specify which agent's memories to access

Configure via environment variables:
    MEMORY_BACKEND=database  # or 'file' (default)
    MEMORY_DATABASE_URL=postgresql://user:pass@host:5432/dbname  # pragma: allowlist secret
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any, Protocol, runtime_checkable

from ..storage.database_memory_store import DatabaseMemoryStore
from ..storage.embedding import EmbeddingClient
from ..storage.memory_store import DEFAULT_AGENT_NAME, Memory, MemoryStore
from ..utils.tool_decorators import handle_tool_errors

logger = logging.getLogger(__name__)

# Validation constants
MAX_AGENT_NAME_LENGTH = 100  # Matches VARCHAR(100) in database schema
MAX_KEY_LENGTH = 256  # Prevents resource exhaustion via oversized keys
MAX_VALUE_LENGTH = 10000  # Prevents resource exhaustion via oversized values
AGENT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Thread locks for store registry access
_file_stores_lock = threading.Lock()
_database_stores_lock = threading.Lock()


class InvalidAgentNameError(ValueError):
    """Raised when an invalid agent_name is provided."""

    pass


def validate_agent_name(agent_name: str) -> str:
    """Validate and sanitize agent_name to prevent security issues.

    Args:
        agent_name: The agent name to validate

    Returns:
        The validated agent name (unchanged if valid)

    Raises:
        InvalidAgentNameError: If the agent name is invalid
    """
    if not agent_name:
        raise InvalidAgentNameError("agent_name cannot be empty")

    # Check for null bytes (could cause issues in file paths and C libraries)
    if "\x00" in agent_name:
        raise InvalidAgentNameError("agent_name cannot contain null bytes")

    # Check for path traversal attempts
    if ".." in agent_name or "/" in agent_name or "\\" in agent_name:
        raise InvalidAgentNameError(
            "agent_name cannot contain path traversal characters (../, /, \\)"
        )

    # Check length (matches database VARCHAR(100))
    if len(agent_name) > MAX_AGENT_NAME_LENGTH:
        raise InvalidAgentNameError(f"agent_name cannot exceed {MAX_AGENT_NAME_LENGTH} characters")

    # Check for valid characters (alphanumeric, underscore, hyphen)
    if not AGENT_NAME_PATTERN.match(agent_name):
        raise InvalidAgentNameError(
            "agent_name must contain only alphanumeric characters, underscores, and hyphens"
        )

    return agent_name


# ---------------------------------------------------------------------------
# Unified memory store protocol and async adapter
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryStoreProtocol(Protocol):
    """Async protocol shared by both file and database memory backends.

    Every tool function calls ``get_active_memory_store()`` which returns
    an object satisfying this protocol, eliminating per-call backend
    dispatch.
    """

    async def save_memory(
        self,
        key: str,
        value: str,
        category: str | None = None,
        tags: list[str] | None = None,
        importance: int = 5,
    ) -> Memory: ...

    async def get_all_memories(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        min_importance: int | None = None,
    ) -> list[Memory]: ...

    async def search_memories(self, query: str) -> list[Memory]: ...

    async def delete_memory(self, key: str) -> bool: ...

    async def get_stats(self) -> dict[str, Any]: ...

    async def recall_memories(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.3,
        category: str | None = None,
    ) -> list[tuple[Memory, float]]: ...

    @property
    def has_embeddings(self) -> bool: ...


class AsyncFileMemoryAdapter:
    """Wraps a synchronous :class:`MemoryStore` behind the async
    :class:`MemoryStoreProtocol` interface.

    All methods delegate to the underlying sync store so existing
    file-based storage logic is unchanged.
    """

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    @property
    def has_embeddings(self) -> bool:
        """File backend never has embedding support."""
        return False

    async def save_memory(
        self,
        key: str,
        value: str,
        category: str | None = None,
        tags: list[str] | None = None,
        importance: int = 5,
    ) -> Memory:
        return self._store.save_memory(
            key=key, value=value, category=category, tags=tags, importance=importance
        )

    async def get_all_memories(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        min_importance: int | None = None,
    ) -> list[Memory]:
        return self._store.get_all_memories(
            category=category, tags=tags, min_importance=min_importance
        )

    async def search_memories(self, query: str) -> list[Memory]:
        return self._store.search_memories(query)

    async def delete_memory(self, key: str) -> bool:
        return self._store.delete_memory(key)

    async def get_stats(self) -> dict[str, Any]:
        return self._store.get_stats()

    async def recall_memories(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.3,
        category: str | None = None,
    ) -> list[tuple[Memory, float]]:
        """File backend: fall back to keyword search with score=0."""
        results = self._store.search_memories(query)
        if category is not None:
            results = [m for m in results if m.category == category]
        return [(m, 0.0) for m in results[:limit]]


# ---------------------------------------------------------------------------
# Global store instances - keyed by agent_name for isolation
# ---------------------------------------------------------------------------

_file_memory_stores: dict[str, MemoryStore] = {}
_database_memory_stores: dict[str, DatabaseMemoryStore] = {}


def _get_backend() -> str:
    """Get configured memory backend."""
    return os.environ.get("MEMORY_BACKEND", "file").lower()


def get_memory_store(agent_name: str = DEFAULT_AGENT_NAME) -> MemoryStore:
    """Get or create a file-based memory store instance for the specified agent.

    Thread-safe: uses locking to prevent race conditions when multiple threads
    request the same agent's store simultaneously.

    Args:
        agent_name: Agent identifier for memory isolation (default: "shared")

    Returns:
        MemoryStore instance for the specified agent

    Raises:
        InvalidAgentNameError: If the agent name contains invalid characters
    """
    # Validate agent_name to prevent path traversal and other security issues
    validated_name = validate_agent_name(agent_name)

    # Thread-safe store creation using double-checked locking pattern
    if validated_name not in _file_memory_stores:
        with _file_stores_lock:
            # Double-check after acquiring lock
            if validated_name not in _file_memory_stores:
                _file_memory_stores[validated_name] = MemoryStore(agent_name=validated_name)
    return _file_memory_stores[validated_name]


async def get_database_memory_store(agent_name: str = DEFAULT_AGENT_NAME) -> DatabaseMemoryStore:
    """Get or create a database memory store instance for the specified agent.

    Thread-safe: uses locking to prevent race conditions when multiple threads
    request the same agent's store simultaneously.

    Args:
        agent_name: Agent identifier for memory isolation (default: "shared")

    Returns:
        DatabaseMemoryStore instance for the specified agent

    Raises:
        InvalidAgentNameError: If the agent name contains invalid characters
        ValueError: If DATABASE_URL is not configured
    """
    # Validate agent_name to prevent security issues
    validated_name = validate_agent_name(agent_name)

    # Thread-safe store creation using double-checked locking pattern
    if validated_name not in _database_memory_stores:
        with _database_stores_lock:
            # Double-check after acquiring lock
            if validated_name not in _database_memory_stores:
                # Check both MEMORY_DATABASE_URL and DATABASE_URL for flexibility
                database_url = os.environ.get("MEMORY_DATABASE_URL") or os.environ.get(
                    "DATABASE_URL"
                )
                if not database_url:
                    raise ValueError(
                        "MEMORY_DATABASE_URL or DATABASE_URL environment variable required when using database backend"
                    )
                # Construct optional embedding client for semantic recall
                openai_key = os.environ.get("OPENAI_API_KEY")
                embedding_client = EmbeddingClient(api_key=openai_key) if openai_key else None
                _database_memory_stores[validated_name] = DatabaseMemoryStore(
                    database_url, agent_name=validated_name, embedding_client=embedding_client
                )
                await _database_memory_stores[validated_name].initialize()
    return _database_memory_stores[validated_name]


async def get_active_memory_store(
    agent_name: str = DEFAULT_AGENT_NAME,
) -> MemoryStoreProtocol:
    """Return the appropriate memory store for the configured backend.

    This is the single entry point used by all tool functions.  It
    checks ``MEMORY_BACKEND`` and returns either a
    :class:`DatabaseMemoryStore` (which already satisfies the async
    protocol) or an :class:`AsyncFileMemoryAdapter` wrapping the sync
    file store.

    Args:
        agent_name: Agent identifier for memory isolation (default: "shared")

    Returns:
        An object satisfying :class:`MemoryStoreProtocol`.
    """
    backend = _get_backend()

    if backend == "database":
        return await get_database_memory_store(agent_name)

    return AsyncFileMemoryAdapter(get_memory_store(agent_name))


async def configure_memory_store(
    backend: str = "file",
    database_url: str | None = None,
    storage_path: str | None = None,
    cache_ttl: float = 300.0,
    agent_name: str = DEFAULT_AGENT_NAME,
) -> None:
    """
    Explicitly configure the memory store for a specific agent.

    Call this at application startup to configure the memory backend
    before any memory operations occur.

    Args:
        backend: 'file' or 'database'
        database_url: PostgreSQL URL (required if backend='database')
        storage_path: File storage path (optional, default: ./memories)
        cache_ttl: Cache TTL in seconds for database backend (default: 5 minutes)
        agent_name: Agent identifier for memory isolation (default: "shared")

    Raises:
        InvalidAgentNameError: If the agent name contains invalid characters
        ValueError: If backend is not 'file' or 'database', or if database
            backend is selected but database_url is not provided
    """
    _VALID_BACKENDS = ("file", "database")
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"Invalid backend '{backend}'. Must be one of {_VALID_BACKENDS}.")

    # Validate agent_name first
    validated_name = validate_agent_name(agent_name)

    os.environ["MEMORY_BACKEND"] = backend

    if backend == "database":
        if not database_url:
            raise ValueError("database_url required for database backend")
        os.environ["MEMORY_DATABASE_URL"] = database_url
        openai_key = os.environ.get("OPENAI_API_KEY")
        embedding_client = EmbeddingClient(api_key=openai_key) if openai_key else None
        with _database_stores_lock:
            _database_memory_stores[validated_name] = DatabaseMemoryStore(
                database_url,
                agent_name=validated_name,
                cache_ttl=cache_ttl,
                embedding_client=embedding_client,
            )
            await _database_memory_stores[validated_name].initialize()
        logger.info(f"Configured database memory backend for agent '{validated_name}'")
    else:
        path = storage_path or "./memories"
        with _file_stores_lock:
            _file_memory_stores[validated_name] = MemoryStore(
                storage_path=path, agent_name=validated_name
            )
        logger.info(f"Configured file memory backend at {path} for agent '{validated_name}'")


@handle_tool_errors(operation="save memory")
async def save_memory(
    key: str,
    value: str,
    category: str | None = None,
    tags: list[str] | None = None,
    importance: int = 5,
    agent_name: str = DEFAULT_AGENT_NAME,
) -> dict[str, Any]:
    """
    Save important information to memory.

    Use this to remember:
    - User preferences and goals
    - Important facts about their content/brand
    - Ongoing tasks or projects
    - Decisions made during conversations
    - Insights from previous analyses

    Args:
        key: A unique identifier for this memory (e.g., "user_blog_url", "brand_voice")
        value: The information to remember
        category: Optional category (e.g., "user_preference", "fact", "goal", "insight")
        tags: Optional tags for organization (e.g., ["seo", "twitter"])
        importance: How important is this? 1-10 (default: 5)
            - 1-3: Low importance (minor details)
            - 4-6: Medium importance (useful context)
            - 7-10: High importance (critical information)
        agent_name: Agent identifier for memory isolation (default: "shared")

    Returns:
        Confirmation with the saved memory details
    """
    # Validate key and value lengths to prevent resource exhaustion
    if len(key) > MAX_KEY_LENGTH:
        return {
            "status": "error",
            "message": f"key exceeds maximum length of {MAX_KEY_LENGTH} characters (got {len(key)})",
        }
    if len(value) > MAX_VALUE_LENGTH:
        return {
            "status": "error",
            "message": f"value exceeds maximum length of {MAX_VALUE_LENGTH} characters (got {len(value)})",
        }

    logger.info(f"Saving memory for agent '{agent_name}': {key}")

    store = await get_active_memory_store(agent_name)
    memory = await store.save_memory(
        key=key,
        value=value,
        category=category,
        tags=tags,
        importance=importance,
    )

    return {
        "status": "success",
        "action": "updated" if memory.created_at != memory.updated_at else "created",
        "agent_name": agent_name,
        "memory": _memory_to_dict(memory),
        "message": f"Successfully saved memory: {key}",
    }


@handle_tool_errors(operation="get memories")
async def get_memories(
    category: str | None = None,
    tags: list[str] | None = None,
    min_importance: int | None = None,
    limit: int = 20,
    agent_name: str = DEFAULT_AGENT_NAME,
) -> dict[str, Any]:
    """
    Retrieve stored memories.

    Use this to recall information from previous conversations,
    including user preferences, facts, goals, and insights.

    Args:
        category: Filter by category (e.g., "user_preference", "fact", "goal")
        tags: Filter by tags (returns memories with any matching tag)
        min_importance: Only return memories with importance >= this value
        limit: Maximum number of memories to return (default: 20)
        agent_name: Agent identifier for memory isolation (default: "shared")

    Returns:
        List of matching memories, sorted by importance
    """
    logger.info(
        f"Retrieving memories for agent '{agent_name}' "
        f"(category={category}, tags={tags}, min_importance={min_importance})"
    )

    store = await get_active_memory_store(agent_name)
    memories = await store.get_all_memories(
        category=category,
        tags=tags,
        min_importance=min_importance,
    )

    # Limit results
    memories = memories[:limit]

    return {
        "status": "success",
        "agent_name": agent_name,
        "count": len(memories),
        "memories": [_memory_to_dict(m) for m in memories],
        "message": f"Found {len(memories)} memories",
    }


@handle_tool_errors(operation="search memories")
async def search_memories(
    query: str,
    limit: int = 10,
    agent_name: str = DEFAULT_AGENT_NAME,
) -> dict[str, Any]:
    """
    Search for memories by keyword.

    Searches both keys and values for the query text.
    Useful when you're not sure of the exact memory key.

    Args:
        query: Search term (case-insensitive)
        limit: Maximum number of results (default: 10)
        agent_name: Agent identifier for memory isolation (default: "shared")

    Returns:
        List of matching memories, sorted by importance
    """
    logger.info(f"Searching memories for agent '{agent_name}': {query}")

    store = await get_active_memory_store(agent_name)
    memories = await store.search_memories(query)

    # Limit results
    memories = memories[:limit]

    return {
        "status": "success",
        "agent_name": agent_name,
        "query": query,
        "count": len(memories),
        "memories": [_memory_to_dict(m) for m in memories],
        "message": f"Found {len(memories)} memories matching '{query}'",
    }


@handle_tool_errors(operation="delete memory")
async def delete_memory(
    key: str,
    agent_name: str = DEFAULT_AGENT_NAME,
) -> dict[str, Any]:
    """
    Delete a memory by key.

    Args:
        key: The unique identifier of the memory to delete
        agent_name: Agent identifier for memory isolation (default: "shared")

    Returns:
        Confirmation of deletion
    """
    logger.info(f"Deleting memory for agent '{agent_name}': {key}")

    store = await get_active_memory_store(agent_name)
    deleted = await store.delete_memory(key)

    if deleted:
        return {
            "status": "success",
            "agent_name": agent_name,
            "message": f"Successfully deleted memory: {key}",
        }
    else:
        return {
            "status": "not_found",
            "agent_name": agent_name,
            "message": f"Memory not found: {key}",
        }


@handle_tool_errors(operation="get memory stats")
async def get_memory_stats(
    agent_name: str = DEFAULT_AGENT_NAME,
) -> dict[str, Any]:
    """
    Get statistics about stored memories for a specific agent.

    Args:
        agent_name: Agent identifier for memory isolation (default: "shared")

    Returns:
        Statistics including total count, categories, and date range
    """
    store = await get_active_memory_store(agent_name)
    stats = await store.get_stats()

    return {
        "status": "success",
        "backend": _get_backend(),
        **stats,
    }


@handle_tool_errors(operation="recall memories")
async def recall_memories(
    query: str,
    limit: int = 10,
    min_score: float = 0.3,
    category: str | None = None,
    agent_name: str = DEFAULT_AGENT_NAME,
) -> dict[str, Any]:
    """Retrieve memories by semantic similarity to a natural-language query.

    When the database backend is configured with embeddings, performs vector
    cosine-similarity search for accurate contextual recall.  Falls back to
    keyword search (search_memories) when embeddings are unavailable or the
    file backend is in use.

    Args:
        query: Natural-language description of what you're looking for.
        limit: Maximum number of memories to return (default: 10).
        min_score: Minimum similarity score 0-1 (default: 0.3, ignored for
                   keyword fallback).
        category: Optional category filter.
        agent_name: Agent identifier for memory isolation (default: "shared").

    Returns:
        List of matching memories with similarity scores (if available).
    """
    logger.info(f"Recalling memories for agent '{agent_name}': {query}")

    store = await get_active_memory_store(agent_name)
    results = await store.recall_memories(
        query=query,
        limit=limit,
        min_score=min_score,
        category=category,
    )

    memories_out = []
    for memory, score in results:
        d = _memory_to_dict(memory)
        d["score"] = round(score, 4)
        memories_out.append(d)

    return {
        "status": "success",
        "agent_name": agent_name,
        "query": query,
        "method": "semantic" if store.has_embeddings else "keyword",
        "count": len(memories_out),
        "memories": memories_out,
        "message": f"Found {len(memories_out)} memories matching '{query}'",
    }


def _memory_to_dict(memory: Memory) -> dict[str, Any]:
    """Convert a Memory object to a dictionary for API responses."""
    return {
        "key": memory.key,
        "value": memory.value,
        "category": memory.category,
        "tags": memory.tags,
        "importance": memory.importance,
        "created_at": memory.created_at.isoformat(),
        "updated_at": memory.updated_at.isoformat(),
    }


def reset_memory_stores() -> None:
    """Reset all global memory store instances. Useful for testing."""
    global _file_memory_stores, _database_memory_stores
    _file_memory_stores.clear()
    _database_memory_stores.clear()


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "save_memory",
        "description": (
            "Save important information to persistent memory. Use this to remember "
            "user preferences, goals, insights from analyses, brand voice, and any "
            "other details that should be recalled in future conversations. "
            "Memories are isolated per agent - each agent has its own memory namespace."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "maxLength": 256,
                    "description": "Unique identifier (e.g., 'user_blog_url', 'brand_voice', 'twitter_goal')",
                },
                "value": {
                    "type": "string",
                    "maxLength": 10000,
                    "description": "The information to remember",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category: 'user_preference', 'fact', 'goal', 'insight', etc.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for organization (e.g., ['seo', 'twitter'])",
                },
                "importance": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                    "description": "Importance level 1-10 (1=low, 5=medium, 10=critical)",
                },
                "agent_name": {
                    "type": "string",
                    "default": "shared",
                    "maxLength": 100,
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Agent identifier for memory isolation (e.g., 'chatbot', 'pr_agent'). Must contain only alphanumeric characters, underscores, and hyphens. Default: 'shared'",
                },
            },
            "required": ["key", "value"],
        },
        "handler": save_memory,
    },
    {
        "name": "get_memories",
        "description": (
            "Retrieve stored memories from previous conversations. Returns memories "
            "sorted by importance. Use this at the start of conversations to recall "
            "context about the user. Memories are isolated per agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category (e.g., 'user_preference', 'goal')",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags (returns memories with any matching tag)",
                },
                "min_importance": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Only return memories with importance >= this value",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "description": "Maximum number of memories to return",
                },
                "agent_name": {
                    "type": "string",
                    "default": "shared",
                    "maxLength": 100,
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Agent identifier for memory isolation (e.g., 'chatbot', 'pr_agent'). Must contain only alphanumeric characters, underscores, and hyphens. Default: 'shared'",
                },
            },
            "required": [],
        },
        "handler": get_memories,
    },
    {
        "name": "search_memories",
        "description": (
            "Search for memories by keyword. Searches both keys and values. "
            "Useful when you don't know the exact memory key. Memories are isolated per agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term (case-insensitive)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "Maximum number of results",
                },
                "agent_name": {
                    "type": "string",
                    "default": "shared",
                    "maxLength": 100,
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Agent identifier for memory isolation (e.g., 'chatbot', 'pr_agent'). Must contain only alphanumeric characters, underscores, and hyphens. Default: 'shared'",
                },
            },
            "required": ["query"],
        },
        "handler": search_memories,
    },
    {
        "name": "delete_memory",
        "description": ("Delete a memory by key. Memories are isolated per agent."),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The unique identifier of the memory to delete",
                },
                "agent_name": {
                    "type": "string",
                    "default": "shared",
                    "maxLength": 100,
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Agent identifier for memory isolation (e.g., 'chatbot', 'pr_agent'). Must contain only alphanumeric characters, underscores, and hyphens. Default: 'shared'",
                },
            },
            "required": ["key"],
        },
        "handler": delete_memory,
    },
    {
        "name": "get_memory_stats",
        "description": (
            "Get statistics about stored memories for a specific agent, including "
            "total count, categories, and date range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "default": "shared",
                    "maxLength": 100,
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Agent identifier for memory isolation (e.g., 'chatbot', 'pr_agent'). Must contain only alphanumeric characters, underscores, and hyphens. Default: 'shared'",
                },
            },
            "required": [],
        },
        "handler": get_memory_stats,
    },
    {
        "name": "recall_memories",
        "description": (
            "Retrieve memories by semantic similarity to a natural-language query. "
            "Uses embedding-based vector search when available (database backend with "
            "OPENAI_API_KEY), otherwise falls back to keyword search. Use this for "
            "contextual recall — e.g. 'What does the user prefer for deployment?' "
            "rather than exact key lookups."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "maxLength": 4000,
                    "description": "Natural-language description of what you're looking for",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "Maximum number of results",
                },
                "min_score": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": 0.3,
                    "description": "Minimum similarity score (0-1). Only used for semantic search.",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category filter (e.g., 'user_preference', 'goal')",
                },
                "agent_name": {
                    "type": "string",
                    "default": "shared",
                    "maxLength": 100,
                    "pattern": "^[a-zA-Z0-9_-]+$",
                    "description": "Agent identifier for memory isolation. Default: 'shared'",
                },
            },
            "required": ["query"],
        },
        "handler": recall_memories,
    },
]
