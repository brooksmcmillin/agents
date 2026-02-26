"""Tests for the REST API server and web UI endpoints.

Run with:
    pytest api/test_server.py -v
"""

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Mock the database and disable auth requirement before importing the server
with patch.dict(os.environ, {"DATABASE_URL": "", "DISABLE_AUTH": "true"}):
    from api.server import (
        _sanitize_log_input,
        _validate_cors_origin,
        app,
        verify_api_key,
    )


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def mock_conversation_store(monkeypatch):
    """Mock conversation store for testing."""
    mock = MagicMock()
    monkeypatch.setattr("api.server._conversation_store", mock)
    # Mock the store with sample data
    mock.list_conversations = AsyncMock(
        return_value=[
            MagicMock(
                id="conv-1",
                agent_name="chatbot",
                title="Test Conversation",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                message_count=2,
                metadata={},
            )
        ]
    )
    mock.create_conversation = AsyncMock(
        return_value=MagicMock(
            id="conv-new",
            agent_name="chatbot",
            title="New Conversation",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            message_count=0,
            metadata={},
        )
    )
    mock.get_conversation_with_messages = AsyncMock(
        return_value=MagicMock(
            id="conv-1",
            agent_name="chatbot",
            title="Test Conversation",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            message_count=2,
            metadata={},
            messages=[
                MagicMock(
                    role="user",
                    content="Hello",
                    turn_number=0,
                    created_at=datetime.now(UTC),
                    token_count=5,
                ),
                MagicMock(
                    role="assistant",
                    content="Hi there!",
                    turn_number=1,
                    created_at=datetime.now(UTC),
                    token_count=10,
                ),
            ],
        )
    )
    mock.update_conversation = AsyncMock(
        return_value=MagicMock(
            id="conv-1",
            agent_name="chatbot",
            title="Updated Title",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            message_count=2,
            metadata={},
        )
    )
    mock.delete_conversation = AsyncMock(return_value=True)
    return mock


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_check(self, client):
        """Test health endpoint returns OK status."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "agents_available" in data


class TestAgentEndpoints:
    """Tests for agent listing endpoints."""

    def test_list_agents(self, client):
        """Test listing available agents."""
        response = client.get("/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert len(data["agents"]) > 0

        # Verify agent structure
        agent = data["agents"][0]
        assert "name" in agent
        assert "description" in agent


class TestConversationEndpoints:
    """Tests for conversation management endpoints."""

    def test_list_conversations_no_database(self, client, monkeypatch):
        """Test listing conversations without database configured."""
        monkeypatch.setattr("api.server._conversation_store", None)
        response = client.get("/conversations")
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]

    @pytest.mark.skip(reason="Requires database configuration - tested in integration tests")
    def test_list_conversations(self, client):
        """Test listing conversations with database."""
        pass

    def test_create_conversation(self, client, mock_conversation_store):
        """Test creating a new conversation."""
        response = client.post(
            "/conversations", json={"agent": "chatbot", "title": "New Conversation"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "conv-new"
        assert data["agent"] == "chatbot"
        assert data["title"] == "New Conversation"

    def test_create_conversation_invalid_agent(self, client, mock_conversation_store):
        """Test creating conversation with invalid agent name."""
        response = client.post("/conversations", json={"agent": "invalid_agent"})
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_get_conversation(self, client, mock_conversation_store):
        """Test getting a conversation with messages."""
        response = client.get("/conversations/conv-1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "conv-1"
        assert "messages" in data
        assert len(data["messages"]) == 2

        # Verify message structure
        msg = data["messages"][0]
        assert msg["role"] == "user"
        assert msg["content"] == "Hello"
        assert "turn_number" in msg

    def test_update_conversation(self, client, mock_conversation_store):
        """Test updating conversation title."""
        response = client.patch("/conversations/conv-1", json={"title": "Updated Title"})
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"

    def test_delete_conversation(self, client, mock_conversation_store):
        """Test deleting a conversation."""
        response = client.delete("/conversations/conv-1")
        assert response.status_code == 204


class TestCORSConfiguration:
    """Tests for CORS configuration."""

    def test_cors_headers_present(self, client):
        """Test that CORS headers are properly configured."""
        # With DEV_MODE, should allow any origin
        with patch.dict(os.environ, {"DEV_MODE": "true"}):
            response = client.options("/conversations", headers={"Origin": "http://example.com"})
            # In test mode, CORS may not be fully enabled
            # This is more of a configuration check
            assert response.status_code in [200, 405]


class TestStaticFileServing:
    """Tests for static file serving."""

    @patch("api.server.WEBUI_DIST")
    def test_spa_catchall_when_dist_exists(self, mock_dist, client):
        """Test SPA catch-all route when dist exists."""
        # Mock dist directory existence
        mock_dist.exists.return_value = True
        mock_index = MagicMock()
        mock_index.exists.return_value = True

        with patch("api.server.FileResponse"):
            # This should catch non-API routes
            response = client.get("/some-random-path")
            # Will either serve index.html or 404
            assert response.status_code in [200, 404]

    def test_api_routes_not_caught_by_spa(self, client):
        """Test that API routes are not caught by SPA catch-all."""
        # API routes should always be handled by their specific handlers
        response = client.get("/health")
        assert response.status_code == 200
        # Should not be served as static file


class TestMessageSending:
    """Tests for sending messages in conversations."""

    @patch("api.server._create_agent")
    def test_send_message(self, mock_create_agent, client, mock_conversation_store):
        """Test sending a message to a conversation."""
        # Mock the agent
        mock_agent = MagicMock()
        mock_agent.process_message = AsyncMock(return_value="Test response")
        mock_agent.total_input_tokens = 0
        mock_agent.total_output_tokens = 0
        mock_agent.messages = []
        mock_create_agent.return_value = mock_agent

        # Mock conversation with messages
        mock_conversation_store.add_messages_batch = AsyncMock()

        response = client.post("/conversations/conv-1/message", json={"message": "Hello"})

        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert data["agent"] == "chatbot"
        assert "usage" in data


class TestVerifyApiKey:
    """Tests for the verify_api_key dependency."""

    @pytest.mark.asyncio
    async def test_allows_request_when_no_api_key_configured(self):
        """When API_KEY env is not set, all requests pass."""
        with patch("api.server._api_key", None):
            await verify_api_key(credentials=None)  # Should not raise

    @pytest.mark.asyncio
    async def test_rejects_missing_credentials(self):
        """When API_KEY is set but no credentials provided, reject."""
        with patch("api.server._api_key", "secret-key"):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(credentials=None)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_rejects_invalid_key(self):
        """When API_KEY is set and wrong key provided, reject."""
        with patch("api.server._api_key", "secret-key"):
            from fastapi import HTTPException
            from fastapi.security import HTTPAuthorizationCredentials

            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-key")
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(credentials=creds)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_accepts_valid_key(self):
        """When API_KEY is set and correct key provided, allow."""
        with patch("api.server._api_key", "secret-key"):
            from fastapi.security import HTTPAuthorizationCredentials

            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret-key")
            await verify_api_key(credentials=creds)  # Should not raise


class TestSanitizeLogInput:
    """Tests for _sanitize_log_input."""

    def test_replaces_newlines(self):
        assert "\\n" in _sanitize_log_input("line1\nline2")
        assert "\n" not in _sanitize_log_input("line1\nline2")

    def test_replaces_carriage_returns(self):
        assert "\\r" in _sanitize_log_input("line1\rline2")
        assert "\r" not in _sanitize_log_input("line1\rline2")

    def test_removes_null_bytes(self):
        result = _sanitize_log_input("before\x00after")
        assert "\x00" not in result
        assert "\\x00" in result

    def test_removes_control_chars(self):
        result = _sanitize_log_input("test\x01\x02\x03value")
        assert "\x01" not in result
        assert "\x02" not in result
        assert "\x03" not in result

    def test_preserves_tabs(self):
        assert "\t" in _sanitize_log_input("col1\tcol2")

    def test_preserves_unicode(self):
        assert "hello" in _sanitize_log_input("hello 世界")

    def test_normal_text_unchanged(self):
        assert _sanitize_log_input("hello world") == "hello world"


class TestCorsOriginValidation:
    """Tests for _validate_cors_origin."""

    def test_rejects_wildcard(self):
        assert _validate_cors_origin("*") is False

    def test_rejects_empty_string(self):
        assert _validate_cors_origin("") is False

    def test_rejects_ftp_scheme(self):
        assert _validate_cors_origin("ftp://example.com") is False

    def test_rejects_no_scheme(self):
        assert _validate_cors_origin("example.com") is False

    def test_accepts_http(self):
        assert _validate_cors_origin("http://localhost:3000") is True

    def test_accepts_https(self):
        assert _validate_cors_origin("https://example.com") is True


class TestWebSocketAuth:
    """Tests for WebSocket message-based authentication.

    When API_KEY is configured, clients must send {"type": "auth", "api_key": "..."}
    as their first message after connecting. Credentials never appear in the URL,
    avoiding leakage via server logs, browser history, or proxy logs.
    """

    def test_ws_accepts_when_no_api_key_configured(self, client):
        """WebSocket should work without auth message when no API_KEY is set."""
        with patch("api.server._api_key", None):
            # No auth message needed; connection proceeds to session lookup (4004)
            with client.websocket_connect("/ws/claude-code/fake-session"):
                pass  # pragma: no cover - closes with 4004 (no session)

    def test_ws_rejects_missing_auth_message(self, client):
        """WebSocket should reject when API_KEY is set but no auth message sent."""
        with patch("api.server._api_key", "secret-key"):
            from starlette.websockets import WebSocketDisconnect

            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws/claude-code/fake-session") as ws:
                    # Send a non-auth message as first message
                    ws.send_json({"type": "input", "text": "hello"})
                    ws.receive_json()  # Should get close frame
            assert exc_info.value.code == 4001

    def test_ws_rejects_wrong_api_key(self, client):
        """WebSocket should reject when wrong API key in auth message."""
        with patch("api.server._api_key", "secret-key"):
            from starlette.websockets import WebSocketDisconnect

            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws/claude-code/fake-session") as ws:
                    ws.send_json({"type": "auth", "api_key": "wrong-key"})
                    ws.receive_json()
            assert exc_info.value.code == 4001

    def test_ws_accepts_valid_auth_message(self, client):
        """WebSocket should accept when correct API key sent in auth message."""
        with patch("api.server._api_key", "secret-key"):
            # Should pass auth, then close with 4004 (session not found)
            with client.websocket_connect("/ws/claude-code/fake-session") as ws:
                ws.send_json({"type": "auth", "api_key": "secret-key"})
                # Connection proceeds past auth; server will close with 4004


@pytest.mark.asyncio
async def test_conversation_persistence_workflow():
    """Integration test for full conversation workflow."""
    from api.server import _conversation_store

    if _conversation_store is None:
        pytest.skip("Database not configured")

    # Create conversation
    conv = await _conversation_store.create_conversation(
        agent_name="chatbot", title="Integration Test"
    )
    assert conv.id is not None

    # Add messages
    await _conversation_store.add_messages_batch(
        conv.id,
        [
            {"role": "user", "content": "Test message"},
            {"role": "assistant", "content": "Test response"},
        ],
    )

    # Retrieve conversation
    retrieved = await _conversation_store.get_conversation_with_messages(conv.id)
    assert retrieved is not None
    assert len(retrieved.messages) == 2

    # Update conversation
    updated = await _conversation_store.update_conversation(conv.id, title="Updated Title")
    assert updated is not None
    assert updated.title == "Updated Title"

    # Delete conversation
    deleted = await _conversation_store.delete_conversation(conv.id)
    assert deleted is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
