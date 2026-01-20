"""Simple memory storage for the agent.

This module provides persistent memory storage that allows the agent
to save and retrieve important information across sessions.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Memory(BaseModel):
    """A single memory entry."""

    key: str = Field(..., description="Unique identifier for this memory")
    value: str = Field(..., description="The memory content")
    category: str | None = Field(
        None, description="Optional category (e.g., 'user_preference', 'fact', 'goal')"
    )
    tags: list[str] = Field(default_factory=list, description="Optional tags for filtering")
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="When this memory was created"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="When this memory was last updated"
    )
    importance: int = Field(default=5, description="Importance level 1-10")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "key": self.key,
            "value": self.value,
            "category": self.category,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "importance": self.importance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Memory":
        """Create from dictionary."""
        return cls(
            key=data["key"],
            value=data["value"],
            category=data.get("category"),
            tags=data.get("tags", []),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            importance=data.get("importance", 5),
        )


class MemoryStore:
    """
    File-based memory storage for the agent.

    Stores memories as JSON for easy inspection and portability.
    Can be easily migrated to a database later.

    TODO: Consider unifying the interface with DatabaseMemoryStore.
    Currently MemoryStore uses sync methods while DatabaseMemoryStore uses async.
    Options:
    1. Make both async (wrap sync operations in asyncio.to_thread)
    2. Create a MemoryStoreProtocol for type checking
    3. Add a sync wrapper for DatabaseMemoryStore
    See code optimizer report for detailed recommendations.
    """

    def __init__(self, storage_path: Path | str = "./memories"):
        """
        Initialize memory store.

        Args:
            storage_path: Directory to store memory files
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.storage_path / "memories.json"

        # Load existing memories
        self.memories: dict[str, Memory] = {}
        self._load()

        logger.info(f"Initialized memory store with {len(self.memories)} memories")

    def _load(self) -> None:
        """Load memories from file."""
        if not self.memory_file.exists():
            return

        try:
            with open(self.memory_file) as f:
                data = json.load(f)
                for key, mem_data in data.items():
                    self.memories[key] = Memory.from_dict(mem_data)
            logger.debug(f"Loaded {len(self.memories)} memories from {self.memory_file}")
        except Exception as e:
            logger.error(f"Failed to load memories: {e}")

    def _save(self) -> None:
        """Save memories to file."""
        try:
            data = {key: mem.to_dict() for key, mem in self.memories.items()}
            with open(self.memory_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved {len(self.memories)} memories to {self.memory_file}")
        except Exception as e:
            logger.error(f"Failed to save memories: {e}")

    def save_memory(
        self,
        key: str,
        value: str,
        category: str | None = None,
        tags: list[str] | None = None,
        importance: int = 5,
    ) -> Memory:
        """
        Save or update a memory.

        Args:
            key: Unique identifier for this memory
            value: The memory content
            category: Optional category
            tags: Optional tags for filtering
            importance: Importance level 1-10

        Returns:
            The saved Memory object
        """
        # Check if updating existing memory
        if key in self.memories:
            memory = self.memories[key]
            memory.value = value
            memory.updated_at = datetime.utcnow()
            if category is not None:
                memory.category = category
            if tags is not None:
                memory.tags = tags
            if importance != 5:  # Only update if non-default
                memory.importance = importance
            logger.info(f"Updated memory: {key}")
        else:
            # Create new memory
            memory = Memory(
                key=key,
                value=value,
                category=category,
                tags=tags or [],
                importance=importance,
            )
            self.memories[key] = memory
            logger.info(f"Created new memory: {key}")

        self._save()
        return memory

    def get_memory(self, key: str) -> Memory | None:
        """
        Retrieve a specific memory by key.

        Args:
            key: Memory identifier

        Returns:
            Memory object if found, None otherwise
        """
        return self.memories.get(key)

    def get_all_memories(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        min_importance: int | None = None,
    ) -> list[Memory]:
        """
        Get all memories, optionally filtered.

        Args:
            category: Filter by category
            tags: Filter by tags (must have at least one matching tag)
            min_importance: Minimum importance level

        Returns:
            List of matching Memory objects, sorted by importance (high to low)
        """
        results = list(self.memories.values())

        # Apply filters
        if category is not None:
            results = [m for m in results if m.category == category]

        if tags is not None:
            results = [m for m in results if any(tag in m.tags for tag in tags)]

        if min_importance is not None:
            results = [m for m in results if m.importance >= min_importance]

        # Sort by importance (high to low), then by updated_at (recent first)
        results.sort(key=lambda m: (-m.importance, -m.updated_at.timestamp()))

        return results

    def search_memories(self, query: str) -> list[Memory]:
        """
        Search memories by text in key or value.

        Args:
            query: Search query (case-insensitive)

        Returns:
            List of matching Memory objects
        """
        query_lower = query.lower()
        results = [
            m
            for m in self.memories.values()
            if query_lower in m.key.lower() or query_lower in m.value.lower()
        ]

        # Sort by importance
        results.sort(key=lambda m: (-m.importance, -m.updated_at.timestamp()))

        return results

    def delete_memory(self, key: str) -> bool:
        """
        Delete a memory.

        Args:
            key: Memory identifier

        Returns:
            True if deleted, False if not found
        """
        if key in self.memories:
            del self.memories[key]
            self._save()
            logger.info(f"Deleted memory: {key}")
            return True
        return False

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored memories."""
        categories = {}
        for memory in self.memories.values():
            cat = memory.category or "uncategorized"
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "total_memories": len(self.memories),
            "categories": categories,
            "oldest_memory": min((m.created_at for m in self.memories.values()), default=None),
            "newest_memory": max((m.created_at for m in self.memories.values()), default=None),
        }


# Example usage and migration guide:
#
# To migrate to database storage, implement the same interface:
# - save_memory(key, value, category, tags, importance) -> Memory
# - get_memory(key) -> Memory | None
# - get_all_memories(category, tags, min_importance) -> list[Memory]
# - search_memories(query) -> list[Memory]
# - delete_memory(key) -> bool
# - get_stats() -> dict
#
# Example SQL schema:
# CREATE TABLE memories (
#     key VARCHAR(255) PRIMARY KEY,
#     value TEXT NOT NULL,
#     category VARCHAR(100),
#     tags JSON,
#     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
#     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
#     importance INTEGER DEFAULT 5 CHECK (importance >= 1 AND importance <= 10)
# );
# CREATE INDEX idx_category ON memories(category);
# CREATE INDEX idx_importance ON memories(importance);
# CREATE FULLTEXT INDEX idx_search ON memories(key, value);
