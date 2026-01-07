"""Memory tools for the agent.

These tools allow the agent to save and retrieve important information
across conversations and sessions.
"""

import logging
from typing import Any

from ..memory_store import MemoryStore


logger = logging.getLogger(__name__)

# Global memory store instance
_memory_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """Get or create the global memory store instance."""
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store


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
            "action": "updated"
            if memory.created_at != memory.updated_at
            else "created",
            "memory": {
                "key": memory.key,
                "value": memory.value,
                "category": memory.category,
                "tags": memory.tags,
                "importance": memory.importance,
                "created_at": memory.created_at.isoformat(),
                "updated_at": memory.updated_at.isoformat(),
            },
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
            "memories": [
                {
                    "key": m.key,
                    "value": m.value,
                    "category": m.category,
                    "tags": m.tags,
                    "importance": m.importance,
                    "created_at": m.created_at.isoformat(),
                    "updated_at": m.updated_at.isoformat(),
                }
                for m in memories
            ],
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
        store = get_memory_store()
        memories = store.search_memories(query)

        # Limit results
        memories = memories[:limit]

        return {
            "status": "success",
            "query": query,
            "count": len(memories),
            "memories": [
                {
                    "key": m.key,
                    "value": m.value,
                    "category": m.category,
                    "tags": m.tags,
                    "importance": m.importance,
                    "created_at": m.created_at.isoformat(),
                    "updated_at": m.updated_at.isoformat(),
                }
                for m in memories
            ],
            "message": f"Found {len(memories)} memories matching '{query}'",
        }

    except Exception as e:
        logger.error(f"Failed to search memories: {e}")
        return {
            "status": "error",
            "message": f"Failed to search memories: {e}",
            "memories": [],
        }


# Usage examples for the agent:
#
# Save user's blog URL:
# save_memory(
#     key="user_blog_url",
#     value="https://example.com/blog",
#     category="user_preference",
#     importance=8
# )
#
# Save brand voice insights:
# save_memory(
#     key="brand_voice",
#     value="Professional but conversational, uses technical terms but explains them clearly",
#     category="insight",
#     tags=["branding", "tone"],
#     importance=9
# )
#
# Save ongoing goal:
# save_memory(
#     key="current_goal",
#     value="Increase Twitter engagement by focusing on video content and posting during peak hours",
#     category="goal",
#     tags=["twitter", "engagement"],
#     importance=10
# )
#
# Retrieve all high-importance memories:
# get_memories(min_importance=7)
#
# Get all Twitter-related memories:
# get_memories(tags=["twitter"])
#
# Search for blog-related info:
# search_memories(query="blog")
