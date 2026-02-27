"""Tests for api/server.py auth paths: lifespan startup and WebSocket authentication.

Covers:
- Lifespan startup: no API_KEY + no DISABLE_AUTH (RuntimeError), DISABLE_AUTH path, API_KEY set
- WebSocket authentication: timeout, wrong message type, bad key, correct key, auth disabled
"""

import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_server():
    """Reload api.server to pick up environment variable changes."""
    import api.server as server_module

    importlib.reload(server_module)
    return server_module


# ---------------------------------------------------------------------------
# Lifespan startup tests
# ---------------------------------------------------------------------------


class TestLifespanStartup:
    """Test the lifespan context manager startup logic."""

    @pytest.fixture(autouse=True)
    def _restore_server(self):
        yield
        _reload_server()

    def test_no_api_key_no_disable_auth_raises_runtime_error(self):
        """When API_KEY is not set and DISABLE_AUTH is not true, lifespan should raise RuntimeError."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            # TestClient triggers the lifespan; RuntimeError should propagate
            with pytest.raises(RuntimeError, match="API_KEY environment variable is required"):
                with TestClient(server_module.app):
                    pass

    def test_no_api_key_disable_auth_true_starts_successfully(self):
        """When API_KEY is not set but DISABLE_AUTH=true, server should start with a warning."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "true",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            # Should start without error
            with TestClient(server_module.app) as client:
                response = client.get("/health")
                assert response.status_code == 200

    def test_no_api_key_disable_auth_yes_starts_successfully(self):
        """DISABLE_AUTH=yes should also disable auth."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "yes",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                response = client.get("/health")
                assert response.status_code == 200

    def test_no_api_key_disable_auth_1_starts_successfully(self):
        """DISABLE_AUTH=1 should also disable auth."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "1",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                response = client.get("/health")
                assert response.status_code == 200

    def test_api_key_set_starts_successfully(self):
        """When API_KEY is set, server should start and require auth on protected endpoints."""
        env = {
            "API_KEY": "test-secret-key",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            mock_agent = MagicMock()
            mock_agent.process_message = AsyncMock(return_value="Hello!")
            mock_agent.total_input_tokens = 10
            mock_agent.total_output_tokens = 5

            with patch.object(server_module, "_create_agent", return_value=mock_agent):
                with TestClient(server_module.app) as client:
                    # Unauthenticated request to a protected endpoint should be rejected
                    response = client.post(
                        "/agents/chatbot/message",
                        json={"message": "test"},
                    )
                    assert response.status_code == 401
                    # Authenticated request should succeed
                    response = client.post(
                        "/agents/chatbot/message",
                        json={"message": "test"},
                        headers={"Authorization": "Bearer test-secret-key"},
                    )
                    assert response.status_code == 200

    def test_no_api_key_disable_auth_false_raises_runtime_error(self):
        """DISABLE_AUTH=false should not bypass the API_KEY requirement."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "false",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with pytest.raises(RuntimeError, match="API_KEY environment variable is required"):
                with TestClient(server_module.app):
                    pass


# ---------------------------------------------------------------------------
# WebSocket authentication unit tests (testing _authenticate_websocket directly)
# ---------------------------------------------------------------------------


class TestAuthenticateWebsocketDirect:
    """Test _authenticate_websocket function directly with mock WebSocket objects.

    _authenticate_websocket now always reads a message from the WebSocket so that
    the session_token (for session-ownership verification) can be extracted even
    when global API-key auth is disabled.  It returns the parsed auth dict on
    success, or None on failure.
    """

    @pytest.fixture(autouse=True)
    def _restore_server(self):
        yield
        _reload_server()

    async def test_auth_disabled_reads_message_and_returns_dict(self):
        """When _api_key is None/empty, should still read the auth message and return it."""
        env = {"API_KEY": ""}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            mock_ws = MagicMock()
            mock_ws.receive_json = AsyncMock(return_value={"type": "auth", "session_token": "tok"})
            result = await server_module._authenticate_websocket(mock_ws)
            # Returns the auth payload dict (truthy) when auth is disabled and message is valid
            assert result == {"type": "auth", "session_token": "tok"}
            mock_ws.receive_json.assert_called_once()

    async def test_timeout_returns_none(self):
        """When client doesn't send auth within timeout, should return None."""
        env = {"API_KEY": "secret123"}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            mock_ws = MagicMock()
            mock_ws.receive_json = AsyncMock(side_effect=TimeoutError)
            result = await server_module._authenticate_websocket(mock_ws)
            assert result is None

    async def test_exception_during_receive_returns_none(self):
        """Any exception during receive should return None."""
        env = {"API_KEY": "secret123"}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            mock_ws = MagicMock()
            mock_ws.receive_json = AsyncMock(side_effect=WebSocketDisconnect)
            result = await server_module._authenticate_websocket(mock_ws)
            assert result is None

    async def test_non_dict_message_returns_none(self):
        """If client sends a non-dict message, should return None."""
        env = {"API_KEY": "secret123"}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            mock_ws = MagicMock()
            mock_ws.receive_json = AsyncMock(return_value="not a dict")
            result = await server_module._authenticate_websocket(mock_ws)
            assert result is None

    async def test_wrong_type_field_returns_none(self):
        """If message type is not 'auth', should return None."""
        env = {"API_KEY": "secret123"}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            mock_ws = MagicMock()
            mock_ws.receive_json = AsyncMock(
                return_value={"type": "message", "api_key": "secret123"}
            )
            result = await server_module._authenticate_websocket(mock_ws)
            assert result is None

    async def test_missing_type_field_returns_none(self):
        """If message has no 'type' field, should return None."""
        env = {"API_KEY": "secret123"}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            mock_ws = MagicMock()
            mock_ws.receive_json = AsyncMock(return_value={"api_key": "secret123"})
            result = await server_module._authenticate_websocket(mock_ws)
            assert result is None

    async def test_wrong_api_key_returns_none(self):
        """If api_key doesn't match, should return None."""
        env = {"API_KEY": "secret123"}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            mock_ws = MagicMock()
            mock_ws.receive_json = AsyncMock(return_value={"type": "auth", "api_key": "wrongkey"})
            result = await server_module._authenticate_websocket(mock_ws)
            assert result is None

    async def test_missing_api_key_field_returns_none(self):
        """If auth message has no api_key field when API_KEY is set, should return None."""
        env = {"API_KEY": "secret123"}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            mock_ws = MagicMock()
            mock_ws.receive_json = AsyncMock(return_value={"type": "auth"})
            result = await server_module._authenticate_websocket(mock_ws)
            assert result is None

    async def test_correct_api_key_returns_dict(self):
        """If api_key matches, should return the auth payload dict."""
        env = {"API_KEY": "secret123"}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            mock_ws = MagicMock()
            payload = {"type": "auth", "api_key": "secret123", "session_token": "tok"}
            mock_ws.receive_json = AsyncMock(return_value=payload)
            result = await server_module._authenticate_websocket(mock_ws)
            assert result == payload


# ---------------------------------------------------------------------------
# WebSocket endpoint integration tests
# ---------------------------------------------------------------------------


class TestWebSocketAuth:
    """Test WebSocket authentication through the /ws/claude-code/{session_id} endpoint."""

    @pytest.fixture(autouse=True)
    def _restore_server(self):
        yield
        _reload_server()

    def test_websocket_no_auth_required_session_not_found(self):
        """With auth disabled, WebSocket still needs auth message (for session_token).

        When the session doesn't exist, 4004 is returned after auth message is processed.
        """
        env = {"API_KEY": "", "DISABLE_AUTH": "true", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect("/ws/claude-code/nonexistent-session") as ws:
                        # Must still send auth message (with session_token) even when API_KEY is unset
                        ws.send_json({"type": "auth", "session_token": "any-token"})
                        ws.receive_json()
                # Should close with 4004 (session not found) since auth message was valid
                assert exc_info.value.code == 4004

    def test_websocket_bad_auth_closes_4001(self):
        """With API_KEY set, sending wrong key should close with 4001."""
        env = {"API_KEY": "correct-key", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect("/ws/claude-code/some-session") as ws:
                        ws.send_json(
                            {"type": "auth", "api_key": "wrong-key", "session_token": "tok"}
                        )
                        # Server should close the connection; try to receive to trigger it
                        ws.receive_json()
                assert exc_info.value.code == 4001

    def test_websocket_wrong_message_type_closes_4001(self):
        """Sending a message with wrong type should close with 4001."""
        env = {"API_KEY": "correct-key", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect("/ws/claude-code/some-session") as ws:
                        ws.send_json({"type": "hello", "api_key": "correct-key"})
                        ws.receive_json()
                assert exc_info.value.code == 4001

    def test_websocket_correct_auth_proceeds_to_session_check(self):
        """With correct auth + session_token, should proceed to session lookup (4004 for missing)."""
        env = {"API_KEY": "correct-key", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect("/ws/claude-code/nonexistent-session") as ws:
                        ws.send_json(
                            {"type": "auth", "api_key": "correct-key", "session_token": "tok"}
                        )
                        # After auth succeeds, server checks session => 4004
                        ws.receive_json()
                # Should get 4004 (session not found), NOT 4001 (auth failed)
                assert exc_info.value.code == 4004
