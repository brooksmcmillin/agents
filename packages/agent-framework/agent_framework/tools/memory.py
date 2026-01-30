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

import logging
import os
import re
import threading
from typing import Any

from ..storage.database_memory_store import DatabaseMemoryStore
from ..storage.memory_store import DEFAULT_AGENT_NAME, Memory, MemoryStore

logger = logging.getLogger(__name__)

# Validation constants
MAX_AGENT_NAME_LENGTH = 100  # Matches VARCHAR(100) in database schema
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
        raise InvalidAgentNameError(
            f"agent_name cannot exceed {MAX_AGENT_NAME_LENGTH} characters"
        )

    # Check for valid characters (alphanumeric, underscore, hyphen)
    if not AGENT_NAME_PATTERN.match(agent_name):
        raise InvalidAgentNameError(
            "agent_name must contain only alphanumeric characters, underscores, and hyphens"
        )

    return agent_name

# Global store instances - keyed by agent_name for isolation
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
                database_url = os.environ.get("MEMORY_DATABASE_URL") or os.environ.get("DATABASE_URL")
                if not database_url:
                    raise ValueError(
                        "MEMORY_DATABASE_URL or DATABASE_URL environment variable required when using database backend"
                    )
                _database_memory_stores[validated_name] = DatabaseMemoryStore(
                    database_url, agent_name=validated_name
                )
                await _database_memory_stores[validated_name].initialize()
    return _database_memory_stores[validated_name]


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
        ValueError: If database backend is selected but database_url is not provided
    """
    # Validate agent_name first
    validated_name = validate_agent_name(agent_name)

    os.environ["MEMORY_BACKEND"] = backend

    if backend == "database":
        if not database_url:
            raise ValueError("database_url required for database backend")
        os.environ["MEMORY_DATABASE_URL"] = database_url
        with _database_stores_lock:
            _database_memory_stores[validated_name] = DatabaseMemoryStore(
                database_url, agent_name=validated_name, cache_ttl=cache_ttl
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
    logger.info(f"Saving memory for agent '{agent_name}': {key}")

    try:
        backend = _get_backend()

        if backend == "database":
            store = await get_database_memory_store(agent_name)
            memory = await store.save_memory(
                key=key,
                value=value,
                category=category,
                tags=tags,
                importance=importance,
            )
        else:
            store = get_memory_store(agent_name)
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
            "agent_name": agent_name,
            "memory": _memory_to_dict(memory),
            "message": f"Successfully saved memory: {key}",
        }

    except Exception as e:
        logger.error(f"Failed to save memory {key} for agent '{agent_name}': {e}")
        return {
            "status": "error",
            "message": f"Failed to save memory: {e}",
        }


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

    try:
        backend = _get_backend()

        if backend == "database":
            store = await get_database_memory_store(agent_name)
            memories = await store.get_all_memories(
                category=category,
                tags=tags,
                min_importance=min_importance,
            )
        else:
            store = get_memory_store(agent_name)
            memories = store.get_all_memories(
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

    except Exception as e:
        logger.error(f"Failed to get memories for agent '{agent_name}': {e}")
        return {
            "status": "error",
            "message": f"Failed to retrieve memories: {e}",
            "memories": [],
        }


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

    try:
        backend = _get_backend()

        if backend == "database":
            store = await get_database_memory_store(agent_name)
            memories = await store.search_memories(query)
        else:
            store = get_memory_store(agent_name)
            memories = store.search_memories(query)

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

    except Exception as e:
        logger.error(f"Failed to search memories for agent '{agent_name}': {e}")
        return {
            "status": "error",
            "message": f"Failed to search memories: {e}",
            "memories": [],
        }


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

    try:
        backend = _get_backend()

        if backend == "database":
            store = await get_database_memory_store(agent_name)
            deleted = await store.delete_memory(key)
        else:
            store = get_memory_store(agent_name)
            deleted = store.delete_memory(key)

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

    except Exception as e:
        logger.error(f"Failed to delete memory {key} for agent '{agent_name}': {e}")
        return {
            "status": "error",
            "message": f"Failed to delete memory: {e}",
        }


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
    try:
        backend = _get_backend()

        if backend == "database":
            store = await get_database_memory_store(agent_name)
            stats = await store.get_stats()
        else:
            store = get_memory_store(agent_name)
            stats = store.get_stats()

        return {
            "status": "success",
            "backend": backend,
            **stats,
        }

    except Exception as e:
        logger.error(f"Failed to get memory stats for agent '{agent_name}': {e}")
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
        "description": (
            "Delete a memory by key. Memories are isolated per agent."
        ),
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
]
