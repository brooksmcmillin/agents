"""In-memory session manager for stateful agent conversations.

Sessions hold a reference to an instantiated Agent and are evicted
after a configurable TTL of inactivity.  This keeps the REST layer
stateless-friendly (no session = fire-and-forget) while still
supporting multi-turn conversations when needed.

For horizontal scaling or persistence across restarts, swap this
store for a Redis-backed implementation with the same interface.
"""

import asyncio
import logging
import time
import uuid

from agent_framework import Agent

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL = 3600  # 1 hour


class Session:
    """A single agent conversation session."""

    __slots__ = ("id", "agent", "created_at", "last_active")

    def __init__(self, session_id: str, agent: Agent) -> None:
        self.id = session_id
        self.agent = agent
        self.created_at = time.monotonic()
        self.last_active = self.created_at

    def touch(self) -> None:
        """Update last-active timestamp."""
        self.last_active = time.monotonic()


class SessionManager:
    """Manages agent sessions with automatic TTL eviction."""

    def __init__(self, ttl: int = DEFAULT_SESSION_TTL) -> None:
        self._sessions: dict[str, Session] = {}
        self._ttl = ttl
        self._cleanup_task: asyncio.Task | None = None

    def start_cleanup_loop(self) -> None:
        """Start background task that evicts expired sessions."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically remove sessions that exceed TTL."""
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            expired = [
                sid
                for sid, session in self._sessions.items()
                if now - session.last_active > self._ttl
            ]
            for sid in expired:
                logger.info("Evicting expired session %s", sid)
                del self._sessions[sid]

    def create(self, agent: Agent) -> Session:
        """Create a new session wrapping the given agent instance."""
        session_id = uuid.uuid4().hex[:16]
        session = Session(session_id, agent)
        self._sessions[session_id] = session
        logger.info("Created session %s for %s", session_id, agent.get_agent_name())
        return session

    def get(self, session_id: str) -> Session | None:
        """Retrieve a session by ID, or None if not found / expired."""
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if time.monotonic() - session.last_active > self._ttl:
            del self._sessions[session_id]
            return None
        return session

    def delete(self, session_id: str) -> bool:
        """Delete a session.  Returns True if it existed."""
        return self._sessions.pop(session_id, None) is not None

    def active_count(self) -> int:
        return len(self._sessions)
