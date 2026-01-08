"""Memory tools for the agent.

These tools allow the agent to save and retrieve important information
across conversations and sessions.

This module wraps the agent_framework's memory tools, which support
both file-based and database-backed storage. Configure the backend
using configure_memory_store() at application startup.
"""

import logging
from typing import Any

from agent_framework.tools.memory import (
    save_memory as af_save_memory,
    get_memories as af_get_memories,
    search_memories as af_search_memories,
)


logger = logging.getLogger(__name__)


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
    return await af_save_memory(
        key=key,
        value=value,
        category=category,
        tags=tags,
        importance=importance,
    )


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
    return await af_get_memories(
        category=category,
        tags=tags,
        min_importance=min_importance,
        limit=limit,
    )


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
    return await af_search_memories(
        query=query,
        limit=limit,
    )
