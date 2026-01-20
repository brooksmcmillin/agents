"""PostgreSQL-backed memory storage with caching.

This module provides a database-backed memory store that enables
agent memory portability across machines while maintaining good
performance through local caching.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import asyncpg

from agent_framework.utils.errors import DatabaseNotInitializedError

from .memory_store import Memory

logger = logging.getLogger(__name__)

# Cache TTL constants (in seconds)
DEFAULT_CACHE_TTL = 300.0  # 5 minutes - TTL for individual memory items
ALL_MEMORIES_CACHE_TTL = 60.0  # 1 minute - shorter TTL for full list queries


class MemoryCache:
    """Simple TTL-based in-memory cache for Memory objects."""

    def __init__(self, default_ttl: float = DEFAULT_CACHE_TTL):
        """
        Initialize cache.

        Args:
            default_ttl: Default time-to-live in seconds (default: 5 minutes)
        """
        self._cache: dict[str, tuple[Memory, float]] = {}  # key -> (memory, expiry_time)
        self._default_ttl = default_ttl
        self._all_memories_cache: tuple[list[Memory], float] | None = None
        self._all_memories_ttl = ALL_MEMORIES_CACHE_TTL

    def get(self, key: str) -> Memory | None:
        """Get a memory from cache if not expired."""
        if key in self._cache:
            memory, expiry = self._cache[key]
            if time.time() < expiry:
                return memory
            else:
                del self._cache[key]
        return None

    def set(self, key: str, memory: Memory, ttl: float | None = None) -> None:
        """Cache a memory with TTL."""
        expiry = time.time() + (ttl if ttl is not None else self._default_ttl)
        self._cache[key] = (memory, expiry)

    def delete(self, key: str) -> None:
        """Remove a memory from cache."""
        self._cache.pop(key, None)
        self._invalidate_all_memories()

    def invalidate(self, key: str) -> None:
        """Invalidate a specific key and the all-memories cache."""
        self.delete(key)

    def _invalidate_all_memories(self) -> None:
        """Invalidate the all-memories cache."""
        self._all_memories_cache = None

    def get_all_memories(self) -> list[Memory] | None:
        """Get cached list of all memories if not expired."""
        if self._all_memories_cache is not None:
            memories, expiry = self._all_memories_cache
            if time.time() < expiry:
                return memories
            else:
                self._all_memories_cache = None
        return None

    def set_all_memories(self, memories: list[Memory]) -> None:
        """Cache the full list of memories."""
        expiry = time.time() + self._all_memories_ttl
        self._all_memories_cache = (memories, expiry)

    def clear(self) -> None:
        """Clear entire cache."""
        self._cache.clear()
        self._all_memories_cache = None


class DatabaseMemoryStore:
    """
    PostgreSQL-backed memory storage with local caching.

    Provides the same interface as MemoryStore but persists data
    to PostgreSQL for cross-machine portability.
    """

    def __init__(
        self,
        database_url: str,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        min_pool_size: int = 2,
        max_pool_size: int = 10,
    ):
        """
        Initialize database memory store.

        Args:
            database_url: PostgreSQL connection URL
                         (e.g., postgresql://user:pass@host:5432/dbname)  # pragma: allowlist secret
            cache_ttl: Cache time-to-live in seconds (default: 5 minutes)
            min_pool_size: Minimum connection pool size
            max_pool_size: Maximum connection pool size
        """
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._cache = MemoryCache(default_ttl=cache_ttl)
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize connection pool and create table if needed."""
        async with self._init_lock:
            if self._initialized:
                return

            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=self._min_pool_size,
                max_size=self._max_pool_size,
            )

            await self._create_table()
            self._initialized = True
            logger.info("DatabaseMemoryStore initialized")

    async def _create_table(self) -> None:
        """Create memories table if it doesn't exist.

        Note: This is called from initialize() before _initialized is set to True,
        so we use self._pool directly instead of _get_connection() to avoid deadlock.
        """
        if self._pool is None:
            raise DatabaseNotInitializedError()
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    key VARCHAR(255) PRIMARY KEY,
                    value TEXT NOT NULL,
                    category VARCHAR(100),
                    tags JSONB DEFAULT '[]'::jsonb,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    importance INTEGER DEFAULT 5 CHECK (importance >= 1 AND importance <= 10)
                )
            """)
            # Create indexes for common queries
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at)
            """)
            logger.debug("Database table and indexes ensured")

    @asynccontextmanager
    async def _get_connection(self) -> AsyncGenerator[asyncpg.Connection, None]:
        """Get a connection from the pool."""
        if not self._initialized:
            await self.initialize()
        if self._pool is None:
            raise DatabaseNotInitializedError()
        async with self._pool.acquire() as conn:
            yield conn

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized = False
            logger.info("DatabaseMemoryStore closed")

    async def save_memory(
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
        # Note: _get_connection() handles initialization automatically
        tags = tags or []
        tags_json = json.dumps(tags)  # Convert list to JSON string for JSONB
        now = datetime.utcnow()

        async with self._get_connection() as conn:
            # Check if exists to determine created_at
            existing = await conn.fetchrow("SELECT created_at FROM memories WHERE key = $1", key)

            if existing:
                # Update existing memory
                await conn.execute(
                    """
                    UPDATE memories
                    SET value = $2, category = $3, tags = $4::jsonb,
                        updated_at = $5, importance = $6
                    WHERE key = $1
                    """,
                    key,
                    value,
                    category,
                    tags_json,
                    now,
                    importance,
                )
                created_at = existing["created_at"].replace(tzinfo=None)
                logger.info(f"Updated memory: {key}")
            else:
                # Insert new memory
                await conn.execute(
                    """
                    INSERT INTO memories (key, value, category, tags, created_at, updated_at, importance)
                    VALUES ($1, $2, $3, $4::jsonb, $5, $5, $6)
                    """,
                    key,
                    value,
                    category,
                    tags_json,
                    now,
                    importance,
                )
                created_at = now
                logger.info(f"Created new memory: {key}")

        memory = Memory(
            key=key,
            value=value,
            category=category,
            tags=tags,
            created_at=created_at,
            updated_at=now,
            importance=importance,
        )

        # Update cache
        self._cache.set(key, memory)
        self._cache._invalidate_all_memories()

        return memory

    async def get_memory(self, key: str) -> Memory | None:
        """
        Retrieve a specific memory by key.

        Args:
            key: Memory identifier

        Returns:
            Memory object if found, None otherwise
        """
        # Check cache first
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        # Note: _get_connection() handles initialization automatically
        async with self._get_connection() as conn:
            row = await conn.fetchrow("SELECT * FROM memories WHERE key = $1", key)

        if row is None:
            return None

        memory = self._row_to_memory(row)
        self._cache.set(key, memory)
        return memory

    async def get_all_memories(
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
        # For unfiltered queries, check cache
        if category is None and tags is None and min_importance is None:
            cached = self._cache.get_all_memories()
            if cached is not None:
                return cached

        # Build query with filters
        query = "SELECT * FROM memories WHERE 1=1"
        params: list[Any] = []
        param_count = 0

        if category is not None:
            param_count += 1
            query += f" AND category = ${param_count}"
            params.append(category)

        if tags is not None:
            param_count += 1
            # Check if any tag matches using JSONB overlap
            # The ?| operator expects a text[] array
            query += f" AND tags ?| ${param_count}::text[]"
            params.append(tags)

        if min_importance is not None:
            param_count += 1
            query += f" AND importance >= ${param_count}"
            params.append(min_importance)

        query += " ORDER BY importance DESC, updated_at DESC"

        async with self._get_connection() as conn:
            rows = await conn.fetch(query, *params)

        memories = [self._row_to_memory(row) for row in rows]

        # Cache unfiltered results
        if category is None and tags is None and min_importance is None:
            self._cache.set_all_memories(memories)

        return memories

    async def search_memories(self, query: str) -> list[Memory]:
        """
        Search memories by text in key or value.

        Args:
            query: Search query (case-insensitive)

        Returns:
            List of matching Memory objects
        """
        # Note: _get_connection() handles initialization automatically
        # Escape SQL wildcards to prevent wildcard injection attacks
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search_pattern = f"%{escaped_query}%"

        async with self._get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM memories
                WHERE key ILIKE $1 ESCAPE '\\' OR value ILIKE $1 ESCAPE '\\'
                ORDER BY importance DESC, updated_at DESC
                """,
                search_pattern,
            )

        return [self._row_to_memory(row) for row in rows]

    async def delete_memory(self, key: str) -> bool:
        """
        Delete a memory.

        Args:
            key: Memory identifier

        Returns:
            True if deleted, False if not found
        """
        # Note: _get_connection() handles initialization automatically
        async with self._get_connection() as conn:
            result = await conn.execute("DELETE FROM memories WHERE key = $1", key)

        deleted = result == "DELETE 1"
        if deleted:
            self._cache.invalidate(key)
            logger.info(f"Deleted memory: {key}")

        return deleted

    async def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored memories."""
        # Note: _get_connection() handles initialization automatically
        async with self._get_connection() as conn:
            # Get total count
            total = await conn.fetchval("SELECT COUNT(*) FROM memories")

            # Get category counts
            category_rows = await conn.fetch(
                """
                SELECT COALESCE(category, 'uncategorized') as cat, COUNT(*) as cnt
                FROM memories
                GROUP BY category
                """
            )

            # Get date range
            dates = await conn.fetchrow(
                "SELECT MIN(created_at) as oldest, MAX(created_at) as newest FROM memories"
            )

        categories = {row["cat"]: row["cnt"] for row in category_rows}

        return {
            "total_memories": total,
            "categories": categories,
            "oldest_memory": dates["oldest"].replace(tzinfo=None) if dates["oldest"] else None,
            "newest_memory": dates["newest"].replace(tzinfo=None) if dates["newest"] else None,
        }

    def _row_to_memory(self, row: asyncpg.Record) -> Memory:
        """Convert a database row to a Memory object."""
        # Parse tags - asyncpg may return JSONB as string or list depending on version
        tags = row["tags"]
        if isinstance(tags, str):
            tags = json.loads(tags)
        elif tags is None:
            tags = []
        return Memory(
            key=row["key"],
            value=row["value"],
            category=row["category"],
            tags=tags,
            created_at=row["created_at"].replace(tzinfo=None),
            updated_at=row["updated_at"].replace(tzinfo=None),
            importance=row["importance"],
        )
