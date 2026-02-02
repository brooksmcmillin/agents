"""SMS Phone Pool Manager for two-way agent-admin conversations.

This module provides a pool of Twilio phone numbers that can be dynamically
assigned to conversations. When an agent needs to request clarification from
the admin via SMS, it acquires a phone number from the pool. When the admin
replies, the webhook routes the reply back to the correct conversation based
on which Twilio number received the message.

Table Schema (created automatically on initialize()):

    CREATE TABLE sms_phone_pool (
        phone_number VARCHAR(20) PRIMARY KEY,
        status VARCHAR(20) NOT NULL DEFAULT 'available',
        locked_to_conversation_id VARCHAR(36),
        locked_to_agent VARCHAR(100),
        locked_at TIMESTAMP WITH TIME ZONE,
        lock_expires_at TIMESTAMP WITH TIME ZONE,
        question_text TEXT,
        message_sid VARCHAR(50),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );

Indexes:
    - idx_sms_pool_status ON sms_phone_pool(status)
    - idx_sms_pool_conversation ON sms_phone_pool(locked_to_conversation_id)
    - idx_sms_pool_expires ON sms_phone_pool(lock_expires_at)
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
from pydantic import BaseModel

from agent_framework.utils.errors import DatabaseNotInitializedError

logger = logging.getLogger(__name__)


def _sanitize_log_input(value: str) -> str:
    """Sanitize user input for safe logging."""
    sanitized = value.replace("\n", "\\n").replace("\r", "\\r")
    return "".join(c if c == "\t" or (ord(c) >= 0x20) else f"\\x{ord(c):02x}" for c in sanitized)


class PhonePoolEntry(BaseModel):
    """A phone number in the pool."""

    phone_number: str
    status: str  # "available" or "locked"
    locked_to_conversation_id: str | None = None
    locked_to_agent: str | None = None
    locked_at: datetime | None = None
    lock_expires_at: datetime | None = None
    question_text: str | None = None
    message_sid: str | None = None
    created_at: datetime | None = None


class SMSPhonePoolManager:
    """
    Manages a pool of Twilio phone numbers for two-way SMS conversations.

    When an agent needs to send an SMS clarification request to the admin,
    it acquires a phone number from the pool. The phone is locked to that
    conversation until the admin replies or the lock expires.

    This enables routing: when the admin replies, the webhook can look up
    which conversation the reply belongs to based on the Twilio number
    that received the message.
    """

    def __init__(
        self,
        database_url: str,
        phone_numbers: list[str] | None = None,
        default_lock_timeout_minutes: int = 30,
        min_pool_size: int = 2,
        max_pool_size: int = 10,
    ):
        """
        Initialize SMS phone pool manager.

        Args:
            database_url: PostgreSQL connection URL
            phone_numbers: List of Twilio phone numbers to add to pool
            default_lock_timeout_minutes: Default timeout for phone locks
            min_pool_size: Minimum connection pool size
            max_pool_size: Maximum connection pool size
        """
        self._database_url = database_url
        self._phone_numbers = phone_numbers or []
        self._default_lock_timeout = default_lock_timeout_minutes
        self._pool: asyncpg.Pool | None = None
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize connection pool, create tables, and seed phone numbers."""
        async with self._init_lock:
            if self._initialized:
                return

            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=self._min_pool_size,
                max_size=self._max_pool_size,
            )

            await self._create_tables()

            # Seed phone numbers if provided
            if self._phone_numbers:
                await self._seed_phone_numbers(self._phone_numbers)

            self._initialized = True
            logger.info("SMSPhonePoolManager initialized")

    async def _create_tables(self) -> None:
        """Create phone pool table if it doesn't exist."""
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sms_phone_pool (
                    phone_number VARCHAR(20) PRIMARY KEY,
                    status VARCHAR(20) NOT NULL DEFAULT 'available',
                    locked_to_conversation_id VARCHAR(36),
                    locked_to_agent VARCHAR(100),
                    locked_at TIMESTAMP WITH TIME ZONE,
                    lock_expires_at TIMESTAMP WITH TIME ZONE,
                    question_text TEXT,
                    message_sid VARCHAR(50),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)

            # Create indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sms_pool_status
                ON sms_phone_pool(status)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sms_pool_conversation
                ON sms_phone_pool(locked_to_conversation_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sms_pool_expires
                ON sms_phone_pool(lock_expires_at)
            """)

            logger.debug("SMS phone pool table and indexes ensured")

    async def _seed_phone_numbers(self, phone_numbers: list[str]) -> None:
        """Add phone numbers to pool if they don't exist."""
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            for phone in phone_numbers:
                await conn.execute(
                    """
                    INSERT INTO sms_phone_pool (phone_number, status, created_at)
                    VALUES ($1, 'available', NOW())
                    ON CONFLICT (phone_number) DO NOTHING
                    """,
                    phone,
                )
            logger.info(f"Seeded {len(phone_numbers)} phone numbers to pool")

    async def close(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized = False
            logger.info("SMSPhonePoolManager closed")

    async def _ensure_initialized(self) -> None:
        """Ensure the manager is initialized."""
        if not self._initialized:
            await self.initialize()

    async def acquire(
        self,
        conversation_id: str,
        agent_name: str,
        question_text: str,
        timeout_minutes: int | None = None,
    ) -> PhonePoolEntry | None:
        """
        Acquire an available phone number from the pool.

        First releases any expired locks, then tries to acquire an available number.

        Args:
            conversation_id: The conversation ID to lock the phone to
            agent_name: Name of the agent requesting the phone
            question_text: The clarification question being asked
            timeout_minutes: Lock timeout in minutes (defaults to pool default)

        Returns:
            PhonePoolEntry if a phone was acquired, None if pool exhausted
        """
        await self._ensure_initialized()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        timeout = timeout_minutes or self._default_lock_timeout

        async with self._pool.acquire() as conn:
            # Atomic operation: release expired locks AND acquire in single statement
            # This prevents race conditions where another request could grab a just-released phone
            now = datetime.now(UTC)
            expires_at = now + timedelta(minutes=timeout)

            row = await conn.fetchrow(
                """
                WITH release_expired AS (
                    -- First, release any expired locks atomically
                    UPDATE sms_phone_pool
                    SET status = 'available',
                        locked_to_conversation_id = NULL,
                        locked_to_agent = NULL,
                        locked_at = NULL,
                        lock_expires_at = NULL,
                        question_text = NULL,
                        message_sid = NULL
                    WHERE status = 'locked' AND lock_expires_at < NOW()
                    RETURNING phone_number
                ),
                acquire_phone AS (
                    -- Then acquire an available phone (including just-released ones)
                    UPDATE sms_phone_pool
                    SET status = 'locked',
                        locked_to_conversation_id = $1,
                        locked_to_agent = $2,
                        locked_at = $3,
                        lock_expires_at = $4,
                        question_text = $5,
                        message_sid = NULL
                    WHERE phone_number = (
                        SELECT phone_number FROM sms_phone_pool
                        WHERE status = 'available'
                        ORDER BY created_at
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING *
                )
                SELECT * FROM acquire_phone
                """,
                conversation_id,
                agent_name,
                now,
                expires_at,
                question_text,
            )

            if row is None:
                logger.warning(
                    f"Phone pool exhausted for conversation {_sanitize_log_input(conversation_id)}"
                )
                return None

            logger.info(
                f"Acquired phone {row['phone_number']} for conversation "
                f"{_sanitize_log_input(conversation_id)} (agent: {_sanitize_log_input(agent_name)})"
            )

            return self._row_to_entry(row)

    async def release(self, phone_number: str) -> bool:
        """
        Release a phone number back to the pool.

        Args:
            phone_number: The phone number to release

        Returns:
            True if released, False if not found or already available
        """
        await self._ensure_initialized()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE sms_phone_pool
                SET status = 'available',
                    locked_to_conversation_id = NULL,
                    locked_to_agent = NULL,
                    locked_at = NULL,
                    lock_expires_at = NULL,
                    question_text = NULL,
                    message_sid = NULL
                WHERE phone_number = $1 AND status = 'locked'
                """,
                phone_number,
            )

            released = result == "UPDATE 1"
            if released:
                logger.info(f"Released phone {phone_number} back to pool")
            return released

    async def update_message_sid(self, phone_number: str, message_sid: str) -> bool:
        """
        Update the message SID for a locked phone (after sending SMS).

        Args:
            phone_number: The phone number
            message_sid: The Twilio message SID

        Returns:
            True if updated, False if phone not found
        """
        await self._ensure_initialized()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE sms_phone_pool
                SET message_sid = $2
                WHERE phone_number = $1 AND status = 'locked'
                """,
                phone_number,
                message_sid,
            )
            return result == "UPDATE 1"

    async def get_by_phone_number(self, phone_number: str) -> PhonePoolEntry | None:
        """
        Get pool entry by phone number.

        Args:
            phone_number: The phone number to look up

        Returns:
            PhonePoolEntry if found, None otherwise
        """
        await self._ensure_initialized()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sms_phone_pool WHERE phone_number = $1",
                phone_number,
            )

        if row is None:
            return None

        return self._row_to_entry(row)

    async def get_by_conversation_id(self, conversation_id: str) -> PhonePoolEntry | None:
        """
        Get pool entry by conversation ID.

        Args:
            conversation_id: The conversation ID to look up

        Returns:
            PhonePoolEntry if found, None otherwise
        """
        await self._ensure_initialized()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM sms_phone_pool
                WHERE locked_to_conversation_id = $1 AND status = 'locked'
                """,
                conversation_id,
            )

        if row is None:
            return None

        return self._row_to_entry(row)

    async def list_all(self) -> list[PhonePoolEntry]:
        """
        List all phone numbers in the pool.

        Returns:
            List of all PhonePoolEntry objects
        """
        await self._ensure_initialized()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM sms_phone_pool ORDER BY created_at")

        return [self._row_to_entry(row) for row in rows]

    async def get_stats(self) -> dict[str, Any]:
        """
        Get statistics about the phone pool.

        Returns:
            Dictionary with pool statistics
        """
        await self._ensure_initialized()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            total = await conn.fetchval("SELECT COUNT(*) FROM sms_phone_pool")
            available = await conn.fetchval(
                "SELECT COUNT(*) FROM sms_phone_pool WHERE status = 'available'"
            )
            locked = await conn.fetchval(
                "SELECT COUNT(*) FROM sms_phone_pool WHERE status = 'locked'"
            )
            expired = await conn.fetchval(
                """
                SELECT COUNT(*) FROM sms_phone_pool
                WHERE status = 'locked' AND lock_expires_at < NOW()
                """
            )

        return {
            "total_phones": total,
            "available": available,
            "locked": locked,
            "expired_locks": expired,
        }

    async def add_phone_number(self, phone_number: str) -> PhonePoolEntry:
        """
        Add a new phone number to the pool.

        Args:
            phone_number: Phone number in E.164 format

        Returns:
            The created PhonePoolEntry

        Raises:
            ValueError: If phone number already exists
        """
        await self._ensure_initialized()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO sms_phone_pool (phone_number, status, created_at)
                    VALUES ($1, 'available', NOW())
                    RETURNING *
                    """,
                    phone_number,
                )
                logger.info(f"Added phone {phone_number} to pool")
                return self._row_to_entry(row)
            except asyncpg.UniqueViolationError:
                raise ValueError(f"Phone number {phone_number} already exists in pool")

    async def remove_phone_number(self, phone_number: str, force: bool = False) -> bool:
        """
        Remove a phone number from the pool.

        Args:
            phone_number: Phone number to remove
            force: If True, remove even if locked

        Returns:
            True if removed, False if not found

        Raises:
            ValueError: If phone is locked and force=False
        """
        await self._ensure_initialized()
        if self._pool is None:
            raise DatabaseNotInitializedError()

        async with self._pool.acquire() as conn:
            # Check if locked
            entry = await self.get_by_phone_number(phone_number)
            if entry is None:
                return False

            if entry.status == "locked" and not force:
                raise ValueError(
                    f"Phone {phone_number} is locked to conversation "
                    f"{entry.locked_to_conversation_id}. Use force=True to remove."
                )

            result = await conn.execute(
                "DELETE FROM sms_phone_pool WHERE phone_number = $1",
                phone_number,
            )

            removed = result == "DELETE 1"
            if removed:
                logger.info(f"Removed phone {phone_number} from pool")
            return removed

    async def _release_expired_locks(self, conn: asyncpg.Connection) -> int:
        """
        Release all expired locks.

        Args:
            conn: Database connection to use

        Returns:
            Number of locks released
        """
        result = await conn.execute(
            """
            UPDATE sms_phone_pool
            SET status = 'available',
                locked_to_conversation_id = NULL,
                locked_to_agent = NULL,
                locked_at = NULL,
                lock_expires_at = NULL,
                question_text = NULL,
                message_sid = NULL
            WHERE status = 'locked' AND lock_expires_at < NOW()
            """
        )

        # Parse "UPDATE N" result
        count = int(result.split()[1]) if result.startswith("UPDATE") else 0
        if count > 0:
            logger.info(f"Released {count} expired phone locks")
        return count

    def _row_to_entry(self, row: asyncpg.Record) -> PhonePoolEntry:
        """Convert a database row to PhonePoolEntry.

        Preserves timezone info from database (TIMESTAMP WITH TIME ZONE).
        All datetime fields are kept as timezone-aware UTC.
        """
        return PhonePoolEntry(
            phone_number=row["phone_number"],
            status=row["status"],
            locked_to_conversation_id=row["locked_to_conversation_id"],
            locked_to_agent=row["locked_to_agent"],
            locked_at=row["locked_at"].astimezone(UTC) if row["locked_at"] else None,
            lock_expires_at=row["lock_expires_at"].astimezone(UTC)
            if row["lock_expires_at"]
            else None,
            question_text=row["question_text"],
            message_sid=row["message_sid"],
            created_at=row["created_at"].astimezone(UTC) if row["created_at"] else None,
        )
