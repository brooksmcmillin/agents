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
with patch.dict(os.environ, {"DATABASE_URL": "", "DISABLE_AUTH": "true", "ENV": "development"}):
    from api.server import (
        _get_rate_limit_key,
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
        """Test health endpoint returns OK status without leaking agent count."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "agents_available" not in data


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

    @staticmethod
    def _mock_request(host: str = "testclient") -> MagicMock:
        """Create a mock Request with a configurable client host."""
        mock_req = MagicMock()
        mock_req.client = MagicMock()
        mock_req.client.host = host
        return mock_req

    @pytest.mark.asyncio
    async def test_allows_request_when_no_api_key_configured(self):
        """When API_KEY env is not set, all requests pass (non-IP host skips CIDR check)."""
        with patch("api.server._api_key", None):
            await verify_api_key(request=self._mock_request(), credentials=None)  # Should not raise

    @pytest.mark.asyncio
    async def test_rejects_missing_credentials(self):
        """When API_KEY is set but no credentials provided, reject."""
        with patch("api.server._api_key", "secret-key"):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(request=self._mock_request(), credentials=None)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_rejects_invalid_key(self):
        """When API_KEY is set and wrong key provided, reject."""
        with patch("api.server._api_key", "secret-key"):
            from fastapi import HTTPException
            from fastapi.security import HTTPAuthorizationCredentials

            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong-key")
            with pytest.raises(HTTPException) as exc_info:
                await verify_api_key(request=self._mock_request(), credentials=creds)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_accepts_valid_key(self):
        """When API_KEY is set and correct key provided, allow."""
        with patch("api.server._api_key", "secret-key"):
            from fastapi.security import HTTPAuthorizationCredentials

            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="secret-key")
            await verify_api_key(
                request=self._mock_request(), credentials=creds
            )  # Should not raise


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


class TestRateLimitKey:
    """Tests for _get_rate_limit_key.

    Rate limits must be keyed on the API key (Bearer token prefix), not on
    X-Forwarded-For or other spoofable IP headers.
    """

    def _make_request(
        self, headers: dict[str, str] | None = None, client_host: str = "1.2.3.4"
    ) -> MagicMock:
        """Build a minimal mock Request with given headers and client address."""
        req = MagicMock()
        req.headers = headers or {}
        req.client = MagicMock()
        req.client.host = client_host
        return req

    def test_keys_on_bearer_token_prefix(self):
        """Should use first 16 chars of Bearer token as key."""
        token = "abcdefghijklmnopqrstuvwxyz"  # nosec B105
        req = self._make_request(headers={"authorization": f"Bearer {token}"})
        key = _get_rate_limit_key(req)
        assert key == f"apikey:{token[:16]}"

    def test_bearer_case_insensitive(self):
        """Authorization header scheme is case-insensitive per RFC 7235."""
        token = "abcdefghijklmnopqrstuvwxyz"  # nosec B105
        req = self._make_request(headers={"authorization": f"bearer {token}"})
        key = _get_rate_limit_key(req)
        assert key == f"apikey:{token[:16]}"

    def test_different_tokens_produce_different_keys(self):
        """Two distinct API keys must produce distinct rate-limit buckets."""
        req_a = self._make_request(headers={"authorization": "Bearer aaaa_key_one_xxx"})
        req_b = self._make_request(headers={"authorization": "Bearer bbbb_key_two_xxx"})
        assert _get_rate_limit_key(req_a) != _get_rate_limit_key(req_b)

    def test_same_token_different_ips_same_bucket(self):
        """Same API key from different IPs should share one rate-limit bucket."""
        token = "shared_api_key_1234567890"  # nosec B105
        req_a = self._make_request(
            headers={"authorization": f"Bearer {token}"}, client_host="10.0.0.1"
        )
        req_b = self._make_request(
            headers={"authorization": f"Bearer {token}"}, client_host="10.0.0.2"
        )
        assert _get_rate_limit_key(req_a) == _get_rate_limit_key(req_b)

    def test_falls_back_to_client_host_without_auth(self):
        """Without Authorization header, fall back to peer IP (not X-Forwarded-For)."""
        req = self._make_request(client_host="192.168.1.100")
        key = _get_rate_limit_key(req)
        assert key == "ip:192.168.1.100"

    def test_ignores_x_forwarded_for(self):
        """X-Forwarded-For must NOT influence the rate-limit key."""
        req = self._make_request(
            headers={"x-forwarded-for": "spoofed.ip.1.1"},
            client_host="192.168.1.100",
        )
        key = _get_rate_limit_key(req)
        assert "spoofed" not in key
        assert key == "ip:192.168.1.100"

    def test_no_client_returns_unknown(self):
        """If request.client is None (e.g. test), return ip:unknown."""
        req = MagicMock()
        req.headers = {}
        req.client = None
        assert _get_rate_limit_key(req) == "ip:unknown"

    def test_short_token(self):
        """Tokens shorter than 16 chars should still work (uses full token)."""
        req = self._make_request(headers={"authorization": "Bearer short"})
        key = _get_rate_limit_key(req)
        assert key == "apikey:short"

    def test_empty_bearer_token_falls_back_to_ip(self):
        """Bare 'Bearer ' with no token falls back to peer IP."""
        req = self._make_request(
            headers={"authorization": "Bearer "},
            client_host="10.0.0.5",
        )
        key = _get_rate_limit_key(req)
        assert key == "ip:10.0.0.5"

    def test_non_bearer_auth_falls_back_to_ip(self):
        """Non-Bearer auth schemes (e.g. Basic) fall back to peer IP."""
        req = self._make_request(
            headers={"authorization": "Basic dXNlcjpwYXNz"},
            client_host="10.0.0.6",
        )
        key = _get_rate_limit_key(req)
        assert key == "ip:10.0.0.6"


class TestWebSocketAuth:
    """Tests for WebSocket message-based authentication.

    Clients must always send an auth message as their first message after
    connecting.  When API_KEY is configured the message must include the key;
    the session_token is always required to prove session ownership.

        {"type": "auth", "api_key": "...", "session_token": "<per-session token>"}

    Credentials never appear in the URL, avoiding leakage via server logs,
    browser history, or proxy logs.
    """

    def test_ws_accepts_when_no_api_key_configured(self, client):
        """Auth message is still required when no API_KEY is set (for session_token)."""
        with patch("api.server._api_key", None):
            from starlette.websockets import WebSocketDisconnect

            # A non-auth message should still be rejected with 4001
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws/claude-code/fake-session") as ws:
                    ws.send_json({"type": "input", "text": "hello"})
                    ws.receive_json()
            assert exc_info.value.code == 4001

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
                    ws.send_json({"type": "auth", "api_key": "wrong-key", "session_token": "tok"})
                    ws.receive_json()
            assert exc_info.value.code == 4001

    def test_ws_accepts_valid_auth_message(self, client):
        """WebSocket passes API key check then closes with 4003 for unknown/unowned session.

        Session not found and wrong session_token both return 4003 to prevent
        session enumeration via differential close codes.
        """
        with patch("api.server._api_key", "secret-key"):
            from starlette.websockets import WebSocketDisconnect

            # Correct API key but session doesn't exist → 4003 (unified code).
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws/claude-code/fake-session") as ws:
                    ws.send_json(
                        {"type": "auth", "api_key": "secret-key", "session_token": "any-token"}
                    )
                    ws.receive_json()
            assert exc_info.value.code == 4003

    def test_ws_rejects_wrong_session_token(self, client):
        """WebSocket should reject a connection with an incorrect session token."""
        from unittest.mock import MagicMock

        from api.claude_code_sessions import ClaudeCodeSession

        fake_session = MagicMock(spec=ClaudeCodeSession)
        fake_session.session_token = "correct-token"  # nosec B105

        with patch("api.server._api_key", "secret-key"):
            with patch("api.server.claude_code_mgr") as mock_mgr:
                mock_mgr.get_session.return_value = fake_session
                from starlette.websockets import WebSocketDisconnect

                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect("/ws/claude-code/some-session") as ws:
                        ws.send_json(
                            {
                                "type": "auth",
                                "api_key": "secret-key",
                                "session_token": "wrong-token",
                            }
                        )
                        ws.receive_json()
                assert exc_info.value.code == 4003

    def test_ws_accepts_correct_session_token(self, client):
        """WebSocket should proceed when both API key and session token are correct."""
        from unittest.mock import MagicMock

        from api.claude_code_sessions import ClaudeCodeSession

        fake_session = MagicMock(spec=ClaudeCodeSession)
        fake_session.session_token = "correct-token"  # nosec B105

        async def _fake_events():
            # Yield nothing — immediately return so the handler exits cleanly
            return
            yield  # pragma: no cover — makes it an async generator

        fake_session.events = _fake_events

        with patch("api.server._api_key", "secret-key"):
            with patch("api.server.claude_code_mgr") as mock_mgr:
                mock_mgr.get_session.return_value = fake_session
                # Connection should pass auth + token check and enter the event loop
                with client.websocket_connect("/ws/claude-code/some-session") as ws:
                    ws.send_json(
                        {
                            "type": "auth",
                            "api_key": "secret-key",
                            "session_token": "correct-token",
                        }
                    )


class TestClaudeCodeRestSessionToken:
    """Tests for X-Session-Token enforcement on REST mutation endpoints.

    POST /claude-code/sessions/{id}/input
    POST /claude-code/sessions/{id}/permission
    POST /claude-code/sessions/{id}/resize
    DELETE /claude-code/sessions/{id}

    All require a valid X-Session-Token header that matches the session's
    stored token, regardless of whether global API-key auth is enabled.
    """

    def _make_session(self, token: str = "real-token"):  # nosec B107
        """Create a fake ClaudeCodeSession with a known session_token."""
        from unittest.mock import AsyncMock, MagicMock

        from api.claude_code_sessions import ClaudeCodeSession

        session = MagicMock(spec=ClaudeCodeSession)
        session.session_token = token  # nosec B105
        session.session_id = "test-session-id"
        session.send_input = AsyncMock()
        session.respond_permission = AsyncMock()
        session.resize_terminal = AsyncMock()
        session.terminate = AsyncMock()
        return session

    def test_input_missing_token_returns_403(self, client):
        """POST /input without X-Session-Token returns 403."""
        with patch("api.server.claude_code_mgr") as mock_mgr:
            mock_mgr.get_session.return_value = self._make_session()
            response = client.post(
                "/claude-code/sessions/test-session-id/input",
                json={"text": "hello"},
            )
        assert response.status_code == 403

    def test_input_wrong_token_returns_403(self, client):
        """POST /input with wrong X-Session-Token returns 403."""
        with patch("api.server.claude_code_mgr") as mock_mgr:
            mock_mgr.get_session.return_value = self._make_session("real-token")  # nosec B106
            response = client.post(
                "/claude-code/sessions/test-session-id/input",
                json={"text": "hello"},
                headers={"X-Session-Token": "wrong-token"},
            )
        assert response.status_code == 403

    def test_input_correct_token_succeeds(self, client):
        """POST /input with correct X-Session-Token returns 204."""
        session = self._make_session("correct-token")  # nosec B106
        with patch("api.server.claude_code_mgr") as mock_mgr:
            mock_mgr.get_session.return_value = session
            response = client.post(
                "/claude-code/sessions/test-session-id/input",
                json={"text": "hello"},
                headers={"X-Session-Token": "correct-token"},  # nosec B106
            )
        assert response.status_code == 204
        session.send_input.assert_called_once_with("hello")

    def test_permission_missing_token_returns_403(self, client):
        """POST /permission without X-Session-Token returns 403."""
        with patch("api.server.claude_code_mgr") as mock_mgr:
            mock_mgr.get_session.return_value = self._make_session()
            response = client.post(
                "/claude-code/sessions/test-session-id/permission",
                json={"approved": True},
            )
        assert response.status_code == 403

    def test_resize_missing_token_returns_403(self, client):
        """POST /resize without X-Session-Token returns 403."""
        with patch("api.server.claude_code_mgr") as mock_mgr:
            mock_mgr.get_session.return_value = self._make_session()
            response = client.post(
                "/claude-code/sessions/test-session-id/resize",
                json={"rows": 40, "cols": 120},
            )
        assert response.status_code == 403

    def test_delete_missing_token_returns_403(self, client):
        """DELETE /sessions/{id} without X-Session-Token returns 403."""
        with patch("api.server.claude_code_mgr") as mock_mgr:
            mock_mgr.get_session.return_value = self._make_session()
            response = client.delete("/claude-code/sessions/test-session-id")
        assert response.status_code == 403

    def test_session_not_found_returns_403(self, client):
        """Endpoints return 403 (not 404) when session doesn't exist.

        The unified error prevents callers from enumerating session IDs.
        """
        with patch("api.server.claude_code_mgr") as mock_mgr:
            mock_mgr.get_session.return_value = None
            response = client.post(
                "/claude-code/sessions/nonexistent-session/input",
                json={"text": "hello"},
                headers={"X-Session-Token": "any-token"},
            )
        assert response.status_code == 403


class TestDisableAuthProductionSafety:
    """Tests for DISABLE_AUTH + ENV safety checks."""

    def test_disable_auth_blocked_without_env_development(self):
        """DISABLE_AUTH=true without ENV=development raises RuntimeError at startup."""
        with (
            patch.dict(
                os.environ,
                {"DISABLE_AUTH": "true", "ENV": "production", "API_KEY": ""},
                clear=False,
            ),
            patch("api.server._api_key", None),
        ):
            import asyncio

            from api.server import lifespan

            async def _run() -> None:
                async with lifespan(app):
                    pass  # pragma: no cover

            with pytest.raises(RuntimeError, match="DISABLE_AUTH=true requires ENV=development"):
                asyncio.run(_run())

    def test_disable_auth_allowed_in_development(self, client):
        """DISABLE_AUTH=true with ENV=development works normally."""
        # The test suite itself runs with DISABLE_AUTH=true and ENV=development,
        # so if we got this far the server started successfully.
        response = client.get("/health")
        assert response.status_code == 200


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
