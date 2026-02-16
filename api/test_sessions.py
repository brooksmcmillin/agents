"""Tests for the Session and SessionManager classes.

Run with:
    pytest api/test_sessions.py -v
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from api.sessions import DEFAULT_SESSION_TTL, Session, SessionManager


class TestSession:
    """Tests for the Session class."""

    def test_creation_sets_timestamps(self):
        """Session creation sets created_at and last_active."""
        agent = MagicMock()
        session = Session("test-id", agent)

        assert session.id == "test-id"
        assert session.agent is agent
        assert session.created_at > 0
        assert session.last_active == session.created_at

    def test_touch_updates_last_active(self):
        """touch() updates the last_active timestamp."""
        agent = MagicMock()
        session = Session("test-id", agent)
        original = session.last_active

        # Small sleep to ensure monotonic clock advances
        time.sleep(0.01)
        session.touch()

        assert session.last_active > original


class TestSessionManager:
    """Tests for the SessionManager class."""

    def test_create_returns_session(self):
        """create() returns a Session with a unique ID."""
        mgr = SessionManager()
        agent = MagicMock()
        agent.get_agent_name.return_value = "test-agent"

        session = mgr.create(agent)

        assert isinstance(session, Session)
        assert len(session.id) == 16
        assert session.agent is agent

    def test_create_generates_unique_ids(self):
        """Each create() call generates a unique session ID."""
        mgr = SessionManager()
        agent = MagicMock()
        agent.get_agent_name.return_value = "test-agent"

        ids = {mgr.create(agent).id for _ in range(20)}
        assert len(ids) == 20

    def test_get_returns_session(self):
        """get() returns a session that was created."""
        mgr = SessionManager()
        agent = MagicMock()
        agent.get_agent_name.return_value = "test-agent"

        session = mgr.create(agent)
        retrieved = mgr.get(session.id)

        assert retrieved is session

    def test_get_returns_none_for_unknown(self):
        """get() returns None for an unknown session ID."""
        mgr = SessionManager()
        assert mgr.get("nonexistent") is None

    def test_delete_removes_session(self):
        """delete() removes the session and returns True."""
        mgr = SessionManager()
        agent = MagicMock()
        agent.get_agent_name.return_value = "test-agent"

        session = mgr.create(agent)
        assert mgr.delete(session.id) is True
        assert mgr.get(session.id) is None

    def test_delete_returns_false_for_unknown(self):
        """delete() returns False for an unknown session ID."""
        mgr = SessionManager()
        assert mgr.delete("nonexistent") is False

    def test_ttl_expiration_on_get(self):
        """get() returns None for a session that has exceeded TTL."""
        mgr = SessionManager(ttl=1)
        agent = MagicMock()
        agent.get_agent_name.return_value = "test-agent"

        session = mgr.create(agent)

        # Patch monotonic to simulate time passing beyond TTL
        with patch("api.sessions.time.monotonic", return_value=session.last_active + 2):
            assert mgr.get(session.id) is None

    def test_expired_session_removed_from_store(self):
        """After get() finds an expired session, it's removed."""
        mgr = SessionManager(ttl=1)
        agent = MagicMock()
        agent.get_agent_name.return_value = "test-agent"

        session = mgr.create(agent)

        with patch("api.sessions.time.monotonic", return_value=session.last_active + 2):
            mgr.get(session.id)  # Triggers removal

        # Even with time restored, session is gone
        assert mgr.active_count() == 0

    def test_active_count(self):
        """active_count() returns the number of stored sessions."""
        mgr = SessionManager()
        agent = MagicMock()
        agent.get_agent_name.return_value = "test-agent"

        assert mgr.active_count() == 0

        mgr.create(agent)
        assert mgr.active_count() == 1

        mgr.create(agent)
        assert mgr.active_count() == 2

    def test_default_ttl(self):
        """SessionManager uses DEFAULT_SESSION_TTL by default."""
        mgr = SessionManager()
        assert mgr._ttl == DEFAULT_SESSION_TTL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
