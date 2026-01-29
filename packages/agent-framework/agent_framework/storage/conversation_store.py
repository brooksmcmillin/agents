"""PostgreSQL-backed conversation storage for persistent chat sessions.

This module provides database-backed conversation storage that enables
saving, resuming, and managing multi-turn agent conversations.

Table Schema (created automatically on initialize()):

    CREATE TABLE conversations (
        id VARCHAR(36) PRIMARY KEY,
        agent_name VARCHAR(100) NOT NULL,
        title VARCHAR(255),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        metadata JSONB DEFAULT '{}'::jsonb
    );

    CREATE TABLE conversation_messages (
        id SERIAL PRIMARY KEY,
        conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        turn_number INTEGER NOT NULL,
        role VARCHAR(20) NOT NULL,
        content JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        token_count INTEGER,
        UNIQUE(conversation_id, turn_number)
    );

Indexes:
    - idx_conversations_agent_name ON conversations(agent_name)
    - idx_conversations_updated_at ON conversations(updated_at DESC)
    - idx_messages_conversation_id ON conversation_messages(conversation_id)
    - idx_messages_turn ON conversation_messages(conversation_id, turn_number)
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import asyncpg
from pydantic import BaseModel, Field

from agent_framework.utils.errors import DatabaseNotInitializedError

logger = logging.getLogger(__name__)


class Message(BaseModel):
    """A single message in a conversation."""

    role: str  # "user", "assistant"
    content: Any  # str or list of content blocks (for tool use)
    turn_number: int
    created_at: datetime
    token_count: int | None = None


class Conversation(BaseModel):
    """A conversation with metadata."""

    id: str
    agent_name: str
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    message_count: int = 0


class ConversationWithMessages(Conversation):
    """A conversation with its full message history."""

    messages: list[Message] = Field(default_factory=list)


class DatabaseConversationStore:
    """
    PostgreSQL-backed conversation storage.

    Provides persistent storage for multi-turn agent conversations,
    allowing users to save, resume, and manage chat sessions.
    """

    def __init__(
        self,
        database_url: str,
        min_pool_size: int = 2,
        max_pool_size: int = 10,
    ):
        """
        Initialize database conversation store.

        Args:
            database_url: PostgreSQL connection URL
                         (e.g., postgresql://user:pass@host:5432/dbname)  # pragma: allowlist secret
            min_pool_size: Minimum connection pool size
            max_pool_size: Maximum connection pool size
        """
        self._database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize connection pool and create tables if needed."""
        async with self._init_lock:
            if self._initialized:
                return

            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=self._min_pool_size,
                max_size=self._max_pool_size,
            )

            await self._create_tables()
            self._initialized = True
            logger.info("DatabaseConversationStore initialized")

    async def _create_tables(self) -> None:
        """Create conversations and messages tables if they don't exist."""
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            # Create conversations table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id VARCHAR(36) PRIMARY KEY,
                    agent_name VARCHAR(100) NOT NULL,
                    title VARCHAR(255),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    metadata JSONB DEFAULT '{}'::jsonb
                )
            """)

            # Create messages table
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id SERIAL PRIMARY KEY,
                    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    turn_number INTEGER NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content JSONB NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    token_count INTEGER,
                    UNIQUE(conversation_id, turn_number)
                )
            """)

            # Create indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_agent_name
                ON conversations(agent_name)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
                ON conversations(updated_at DESC)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
                ON conversation_messages(conversation_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_turn
                ON conversation_messages(conversation_id, turn_number)
            """)

            logger.debug("Database tables and indexes ensured")

    @asynccontextmanager
    async def _get_connection(self) -> AsyncGenerator[Any, None]:
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
            logger.info("DatabaseConversationStore closed")

    # -------------------------------------------------------------------------
    # Conversation CRUD
    # -------------------------------------------------------------------------

    async def create_conversation(
        self,
        agent_name: str,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
        conversation_id: str | None = None,
    ) -> Conversation:
        """
        Create a new conversation.

        Args:
            agent_name: Name of the agent for this conversation
            title: Optional title/name for the conversation
            metadata: Optional metadata dict
            conversation_id: Optional specific ID (generates UUID if not provided)

        Returns:
            The created Conversation object
        """
        conv_id = conversation_id or str(uuid.uuid4())
        metadata = metadata or {}
        now = datetime.now(UTC)

        async with self._get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO conversations (id, agent_name, title, created_at, updated_at, metadata)
                VALUES ($1, $2, $3, $4, $4, $5::jsonb)
                """,
                conv_id,
                agent_name,
                title,
                now,
                json.dumps(metadata),
            )

        logger.info(f"Created conversation: {conv_id} for agent {agent_name}")

        return Conversation(
            id=conv_id,
            agent_name=agent_name,
            title=title,
            created_at=now,
            updated_at=now,
            metadata=metadata,
            message_count=0,
        )

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        """
        Get a conversation by ID (without messages).

        Args:
            conversation_id: The conversation ID

        Returns:
            Conversation object if found, None otherwise
        """
        async with self._get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT c.*, COUNT(m.id) as message_count
                FROM conversations c
                LEFT JOIN conversation_messages m ON c.id = m.conversation_id
                WHERE c.id = $1
                GROUP BY c.id
                """,
                conversation_id,
            )

        if row is None:
            return None

        return self._row_to_conversation(row)

    async def get_conversation_with_messages(
        self, conversation_id: str
    ) -> ConversationWithMessages | None:
        """
        Get a conversation with its full message history.

        Args:
            conversation_id: The conversation ID

        Returns:
            ConversationWithMessages if found, None otherwise
        """
        conv = await self.get_conversation(conversation_id)
        if conv is None:
            return None

        messages = await self.get_messages(conversation_id)

        return ConversationWithMessages(
            id=conv.id,
            agent_name=conv.agent_name,
            title=conv.title,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            metadata=conv.metadata,
            message_count=conv.message_count,
            messages=messages,
        )

    async def list_conversations(
        self,
        agent_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        """
        List conversations, optionally filtered by agent.

        Args:
            agent_name: Filter by agent name (optional)
            limit: Maximum number to return
            offset: Number to skip (for pagination)

        Returns:
            List of Conversation objects, ordered by updated_at DESC
        """
        query = """
            SELECT c.*, COUNT(m.id) as message_count
            FROM conversations c
            LEFT JOIN conversation_messages m ON c.id = m.conversation_id
        """
        params: list[Any] = []

        if agent_name:
            query += " WHERE c.agent_name = $1"
            params.append(agent_name)

        limit_param = len(params) + 1
        offset_param = len(params) + 2
        query += (
            f" GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ${limit_param} OFFSET ${offset_param}"
        )
        params.extend([limit, offset])

        async with self._get_connection() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_conversation(row) for row in rows]

    async def update_conversation(
        self,
        conversation_id: str,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation | None:
        """
        Update conversation metadata.

        Args:
            conversation_id: The conversation ID
            title: New title (None to keep existing)
            metadata: New metadata (None to keep existing)

        Returns:
            Updated Conversation if found, None otherwise
        """
        updates = []
        params: list[Any] = []
        param_count = 0

        if title is not None:
            param_count += 1
            updates.append(f"title = ${param_count}")
            params.append(title)

        if metadata is not None:
            param_count += 1
            updates.append(f"metadata = ${param_count}::jsonb")
            params.append(json.dumps(metadata))

        if not updates:
            return await self.get_conversation(conversation_id)

        param_count += 1
        updates.append(f"updated_at = ${param_count}")
        params.append(datetime.now(UTC))

        param_count += 1
        params.append(conversation_id)

        # Safe: updates list contains only validated column names with parameterized values
        query = f"""
            UPDATE conversations
            SET {", ".join(updates)}
            WHERE id = ${param_count}
        """  # nosec B608

        async with self._get_connection() as conn:
            result = await conn.execute(query, *params)

        if result == "UPDATE 0":
            return None

        return await self.get_conversation(conversation_id)

    async def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation and all its messages.

        Args:
            conversation_id: The conversation ID

        Returns:
            True if deleted, False if not found
        """
        async with self._get_connection() as conn:
            result = await conn.execute("DELETE FROM conversations WHERE id = $1", conversation_id)

        deleted = result == "DELETE 1"
        if deleted:
            logger.info(f"Deleted conversation: {conversation_id}")

        return deleted

    # -------------------------------------------------------------------------
    # Message Operations
    # -------------------------------------------------------------------------

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: Any,
        token_count: int | None = None,
    ) -> Message:
        """
        Add a message to a conversation.

        Args:
            conversation_id: The conversation ID
            role: Message role ("user" or "assistant")
            content: Message content (str or list of content blocks)
            token_count: Optional token count for this message

        Returns:
            The created Message object
        """
        now = datetime.now(UTC)
        content_json = json.dumps(content)

        async with self._get_connection() as conn:
            # Get next turn number
            turn_result = await conn.fetchval(
                """
                SELECT COALESCE(MAX(turn_number), -1) + 1
                FROM conversation_messages
                WHERE conversation_id = $1
                """,
                conversation_id,
            )
            turn: int = int(turn_result) if turn_result is not None else 0

            # Insert message
            await conn.execute(
                """
                INSERT INTO conversation_messages
                    (conversation_id, turn_number, role, content, created_at, token_count)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                """,
                conversation_id,
                turn,
                role,
                content_json,
                now,
                token_count,
            )

            # Update conversation timestamp
            await conn.execute(
                "UPDATE conversations SET updated_at = $1 WHERE id = $2",
                now,
                conversation_id,
            )

        return Message(
            role=role,
            content=content,
            turn_number=turn,
            created_at=now,
            token_count=token_count,
        )

    async def add_messages_batch(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
    ) -> list[Message]:
        """
        Add multiple messages to a conversation efficiently.

        Args:
            conversation_id: The conversation ID
            messages: List of dicts with 'role', 'content', and optional 'token_count'

        Returns:
            List of created Message objects
        """
        if not messages:
            return []

        now = datetime.now(UTC)
        result_messages = []

        async with self._get_connection() as conn:
            # Get starting turn number
            start_turn_result = await conn.fetchval(
                """
                SELECT COALESCE(MAX(turn_number), -1) + 1
                FROM conversation_messages
                WHERE conversation_id = $1
                """,
                conversation_id,
            )
            start_turn: int = int(start_turn_result) if start_turn_result is not None else 0

            # Prepare batch insert
            values = []
            for i, msg in enumerate(messages):
                turn = start_turn + i
                values.append(
                    (
                        conversation_id,
                        turn,
                        msg["role"],
                        json.dumps(msg["content"]),
                        now,
                        msg.get("token_count"),
                    )
                )
                result_messages.append(
                    Message(
                        role=msg["role"],
                        content=msg["content"],
                        turn_number=turn,
                        created_at=now,
                        token_count=msg.get("token_count"),
                    )
                )

            # Batch insert
            await conn.executemany(
                """
                INSERT INTO conversation_messages
                    (conversation_id, turn_number, role, content, created_at, token_count)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6)
                """,
                values,
            )

            # Update conversation timestamp
            await conn.execute(
                "UPDATE conversations SET updated_at = $1 WHERE id = $2",
                now,
                conversation_id,
            )

        return result_messages

    async def get_messages(
        self,
        conversation_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Message]:
        """
        Get messages for a conversation.

        Args:
            conversation_id: The conversation ID
            limit: Maximum messages to return (None for all)
            offset: Number to skip (for pagination)

        Returns:
            List of Message objects ordered by turn_number
        """
        query = """
            SELECT turn_number, role, content, created_at, token_count
            FROM conversation_messages
            WHERE conversation_id = $1
            ORDER BY turn_number
        """
        params: list[Any] = [conversation_id]

        if limit is not None:
            query += f" LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}"
            params.extend([limit, offset])

        async with self._get_connection() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_message(row) for row in rows]

    async def clear_messages(self, conversation_id: str) -> int:
        """
        Clear all messages from a conversation (keeps the conversation).

        Args:
            conversation_id: The conversation ID

        Returns:
            Number of messages deleted
        """
        async with self._get_connection() as conn:
            result = await conn.execute(
                "DELETE FROM conversation_messages WHERE conversation_id = $1",
                conversation_id,
            )
            # Update conversation timestamp
            await conn.execute(
                "UPDATE conversations SET updated_at = $1 WHERE id = $2",
                datetime.now(UTC),
                conversation_id,
            )

        # Parse "DELETE N" result
        count = int(result.split()[1]) if result.startswith("DELETE") else 0
        logger.info(f"Cleared {count} messages from conversation {conversation_id}")
        return count

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored conversations."""
        async with self._get_connection() as conn:
            total_convs = await conn.fetchval("SELECT COUNT(*) FROM conversations")
            total_msgs = await conn.fetchval("SELECT COUNT(*) FROM conversation_messages")

            # Agent breakdown
            agent_rows = await conn.fetch(
                """
                SELECT agent_name, COUNT(*) as cnt
                FROM conversations
                GROUP BY agent_name
                """
            )

            # Recent activity
            recent = await conn.fetchrow(
                """
                SELECT MIN(created_at) as oldest, MAX(updated_at) as newest
                FROM conversations
                """
            )

        oldest = None
        newest = None
        if recent is not None:
            if recent["oldest"]:
                oldest = recent["oldest"].replace(tzinfo=None)
            if recent["newest"]:
                newest = recent["newest"].replace(tzinfo=None)

        return {
            "total_conversations": total_convs,
            "total_messages": total_msgs,
            "conversations_by_agent": {row["agent_name"]: row["cnt"] for row in agent_rows},
            "oldest_conversation": oldest,
            "newest_activity": newest,
        }

    def _row_to_conversation(self, row: asyncpg.Record) -> Conversation:
        """Convert a database row to a Conversation object."""
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        elif metadata is None:
            metadata = {}

        return Conversation(
            id=row["id"],
            agent_name=row["agent_name"],
            title=row["title"],
            created_at=row["created_at"].replace(tzinfo=None),
            updated_at=row["updated_at"].replace(tzinfo=None),
            metadata=metadata,
            message_count=row.get("message_count", 0),
        )

    def _row_to_message(self, row: asyncpg.Record) -> Message:
        """Convert a database row to a Message object."""
        content = row["content"]
        if isinstance(content, str):
            content = json.loads(content)

        return Message(
            role=row["role"],
            content=content,
            turn_number=row["turn_number"],
            created_at=row["created_at"].replace(tzinfo=None),
            token_count=row["token_count"],
        )
