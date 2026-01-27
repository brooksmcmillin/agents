"""Memory tools for the agent.

These tools allow the agent to save and retrieve important information
across conversations and sessions.

Supports two backends:
- File-based (default): Local JSON storage, good for single-machine use
- Database: PostgreSQL storage, enables cross-machine memory portability

Configure via environment variables:
    MEMORY_BACKEND=database  # or 'file' (default)
    MEMORY_DATABASE_URL=postgresql://user:pass@host:5432/dbname  # pragma: allowlist secret
"""

import logging
import os
from typing import Any

from ..storage.database_memory_store import DatabaseMemoryStore
from ..storage.memory_store import Memory, MemoryStore

logger = logging.getLogger(__name__)

# Global store instances
_file_memory_store: MemoryStore | None = None
_database_memory_store: DatabaseMemoryStore | None = None


def _get_backend() -> str:
    """Get configured memory backend."""
    return os.environ.get("MEMORY_BACKEND", "file").lower()


def get_memory_store() -> MemoryStore:
    """Get or create the file-based memory store instance."""
    global _file_memory_store
    if _file_memory_store is None:
        _file_memory_store = MemoryStore()
    return _file_memory_store


async def get_database_memory_store() -> DatabaseMemoryStore:
    """Get or create the database memory store instance."""
    global _database_memory_store
    if _database_memory_store is None:
        # Check both MEMORY_DATABASE_URL and DATABASE_URL for flexibility
        database_url = os.environ.get("MEMORY_DATABASE_URL") or os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError(
                "MEMORY_DATABASE_URL or DATABASE_URL environment variable required when using database backend"
            )
        _database_memory_store = DatabaseMemoryStore(database_url)
        await _database_memory_store.initialize()
    return _database_memory_store


async def configure_memory_store(
    backend: str = "file",
    database_url: str | None = None,
    storage_path: str | None = None,
    cache_ttl: float = 300.0,
) -> None:
    """
    Explicitly configure the memory store.

    Call this at application startup to configure the memory backend
    before any memory operations occur.

    Args:
        backend: 'file' or 'database'
        database_url: PostgreSQL URL (required if backend='database')
        storage_path: File storage path (optional, default: ./memories)
        cache_ttl: Cache TTL in seconds for database backend (default: 5 minutes)
    """
    global _file_memory_store, _database_memory_store

    os.environ["MEMORY_BACKEND"] = backend

    if backend == "database":
        if not database_url:
            raise ValueError("database_url required for database backend")
        os.environ["MEMORY_DATABASE_URL"] = database_url
        _database_memory_store = DatabaseMemoryStore(database_url, cache_ttl=cache_ttl)
        await _database_memory_store.initialize()
        logger.info("Configured database memory backend")
    else:
        path = storage_path or "./memories"
        _file_memory_store = MemoryStore(storage_path=path)
        logger.info(f"Configured file memory backend at {path}")


async def save_memory(
    key: str,
    value: str,
    category: str | None = None,
    tags: list[str] | None = None,
    importance: int = 5,
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

    Returns:
        Confirmation with the saved memory details
    """
    logger.info(f"Saving memory: {key}")

    try:
        backend = _get_backend()

        if backend == "database":
            store = await get_database_memory_store()
            memory = await store.save_memory(
                key=key,
                value=value,
                category=category,
                tags=tags,
                importance=importance,
            )
        else:
            store = get_memory_store()
            memory = store.save_memory(
                key=key,
                value=value,
                category=category,
                tags=tags,
                importance=importance,
            )

        return {
            "status": "success",
            "action": "updated" if memory.created_at != memory.updated_at else "created",
            "memory": _memory_to_dict(memory),
            "message": f"Successfully saved memory: {key}",
        }

    except Exception as e:
        logger.error(f"Failed to save memory {key}: {e}")
        return {
            "status": "error",
            "message": f"Failed to save memory: {e}",
        }


async def get_memories(
    category: str | None = None,
    tags: list[str] | None = None,
    min_importance: int | None = None,
    limit: int = 20,
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

    Returns:
        List of matching memories, sorted by importance
    """
    logger.info(
        f"Retrieving memories (category={category}, tags={tags}, min_importance={min_importance})"
    )

    try:
        backend = _get_backend()

        if backend == "database":
            store = await get_database_memory_store()
            memories = await store.get_all_memories(
                category=category,
                tags=tags,
                min_importance=min_importance,
            )
        else:
            store = get_memory_store()
            memories = store.get_all_memories(
                category=category,
                tags=tags,
                min_importance=min_importance,
            )

        # Limit results
        memories = memories[:limit]

        return {
            "status": "success",
            "count": len(memories),
            "memories": [_memory_to_dict(m) for m in memories],
            "message": f"Found {len(memories)} memories",
        }

    except Exception as e:
        logger.error(f"Failed to get memories: {e}")
        return {
            "status": "error",
            "message": f"Failed to retrieve memories: {e}",
            "memories": [],
        }


async def search_memories(
    query: str,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Search for memories by keyword.

    Searches both keys and values for the query text.
    Useful when you're not sure of the exact memory key.

    Args:
        query: Search term (case-insensitive)
        limit: Maximum number of results (default: 10)

    Returns:
        List of matching memories, sorted by importance
    """
    logger.info(f"Searching memories for: {query}")

    try:
        backend = _get_backend()

        if backend == "database":
            store = await get_database_memory_store()
            memories = await store.search_memories(query)
        else:
            store = get_memory_store()
            memories = store.search_memories(query)

        # Limit results
        memories = memories[:limit]

        return {
            "status": "success",
            "query": query,
            "count": len(memories),
            "memories": [_memory_to_dict(m) for m in memories],
            "message": f"Found {len(memories)} memories matching '{query}'",
        }

    except Exception as e:
        logger.error(f"Failed to search memories: {e}")
        return {
            "status": "error",
            "message": f"Failed to search memories: {e}",
            "memories": [],
        }


async def delete_memory(key: str) -> dict[str, Any]:
    """
    Delete a memory by key.

    Args:
        key: The unique identifier of the memory to delete

    Returns:
        Confirmation of deletion
    """
    logger.info(f"Deleting memory: {key}")

    try:
        backend = _get_backend()

        if backend == "database":
            store = await get_database_memory_store()
            deleted = await store.delete_memory(key)
        else:
            store = get_memory_store()
            deleted = store.delete_memory(key)

        if deleted:
            return {
                "status": "success",
                "message": f"Successfully deleted memory: {key}",
            }
        else:
            return {
                "status": "not_found",
                "message": f"Memory not found: {key}",
            }

    except Exception as e:
        logger.error(f"Failed to delete memory {key}: {e}")
        return {
            "status": "error",
            "message": f"Failed to delete memory: {e}",
        }


async def get_memory_stats() -> dict[str, Any]:
    """
    Get statistics about stored memories.

    Returns:
        Statistics including total count, categories, and date range
    """
    try:
        backend = _get_backend()

        if backend == "database":
            store = await get_database_memory_store()
            stats = await store.get_stats()
        else:
            store = get_memory_store()
            stats = store.get_stats()

        return {
            "status": "success",
            "backend": backend,
            **stats,
        }

    except Exception as e:
        logger.error(f"Failed to get memory stats: {e}")
        return {
            "status": "error",
            "message": f"Failed to get memory stats: {e}",
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
    """Reset global memory store instances. Useful for testing."""
    global _file_memory_store, _database_memory_store
    _file_memory_store = None
    _database_memory_store = None


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "save_memory",
        "description": (
            "Save important information to persistent memory. Use this to remember "
            "user preferences, goals, insights from analyses, brand voice, and any "
            "other details that should be recalled in future conversations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Unique identifier (e.g., 'user_blog_url', 'brand_voice', 'twitter_goal')",
                },
                "value": {
                    "type": "string",
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
            "context about the user."
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
            },
            "required": [],
        },
        "handler": get_memories,
    },
    {
        "name": "search_memories",
        "description": (
            "Search for memories by keyword. Searches both keys and values. "
            "Useful when you don't know the exact memory key."
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
            },
            "required": ["query"],
        },
        "handler": search_memories,
    },
]
