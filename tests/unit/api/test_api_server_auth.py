"""Tests for api/server.py auth paths: lifespan startup and WebSocket authentication.

Covers:
- Lifespan startup: no API_KEY + no DISABLE_AUTH (RuntimeError), DISABLE_AUTH path, API_KEY set
- DISABLE_AUTH requires ENV=development explicitly
- DISABLE_AUTH_ALLOWED_IPS CIDR filtering
- Twilio production assertion
- WebSocket authentication: timeout, wrong message type, bad key, correct key, auth disabled
"""

import importlib
import ipaddress
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

    def test_no_api_key_disable_auth_true_without_env_development_raises(self):
        """DISABLE_AUTH=true without ENV=development should raise RuntimeError."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "true",
            "ENV": "",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with pytest.raises(RuntimeError, match="DISABLE_AUTH=true requires ENV=development"):
                with TestClient(server_module.app):
                    pass

    def test_no_api_key_disable_auth_true_with_env_production_raises(self):
        """DISABLE_AUTH=true with ENV=production should raise RuntimeError."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "true",
            "ENV": "production",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with pytest.raises(RuntimeError, match="DISABLE_AUTH=true requires ENV=development"):
                with TestClient(server_module.app):
                    pass

    def test_no_api_key_disable_auth_true_with_env_staging_raises(self):
        """DISABLE_AUTH=true with ENV=staging (not 'development') should raise RuntimeError."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "true",
            "ENV": "staging",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with pytest.raises(RuntimeError, match="DISABLE_AUTH=true requires ENV=development"):
                with TestClient(server_module.app):
                    pass

    def test_no_api_key_disable_auth_true_starts_successfully(self):
        """When API_KEY is not set, DISABLE_AUTH=true, and ENV=development, server should start."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "true",
            "ENV": "development",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            # Should start without error
            with TestClient(server_module.app) as client:
                response = client.get("/health")
                assert response.status_code == 200

    def test_no_api_key_disable_auth_yes_starts_successfully(self):
        """DISABLE_AUTH=yes with ENV=development should also disable auth."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "yes",
            "ENV": "development",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                response = client.get("/health")
                assert response.status_code == 200

    def test_no_api_key_disable_auth_1_starts_successfully(self):
        """DISABLE_AUTH=1 with ENV=development should also disable auth."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "1",
            "ENV": "development",
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

    def test_skip_twilio_validation_in_production_raises(self):
        """SKIP_TWILIO_SIGNATURE_VALIDATION=true with ENV=production should raise RuntimeError."""
        env = {
            "API_KEY": "test-key",
            "SKIP_TWILIO_SIGNATURE_VALIDATION": "true",
            "ENV": "production",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with pytest.raises(
                RuntimeError,
                match="SKIP_TWILIO_SIGNATURE_VALIDATION=true is not allowed when ENV=production",
            ):
                with TestClient(server_module.app):
                    pass

    def test_skip_twilio_validation_in_development_is_allowed(self):
        """SKIP_TWILIO_SIGNATURE_VALIDATION=true with ENV=development should be allowed."""
        env = {
            "API_KEY": "test-key",
            "SKIP_TWILIO_SIGNATURE_VALIDATION": "true",
            "ENV": "development",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                response = client.get("/health")
                assert response.status_code == 200

    def test_skip_twilio_validation_false_in_production_is_allowed(self):
        """SKIP_TWILIO_SIGNATURE_VALIDATION=false with ENV=production is fine."""
        env = {
            "API_KEY": "test-key",
            "SKIP_TWILIO_SIGNATURE_VALIDATION": "false",
            "ENV": "production",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                response = client.get("/health")
                assert response.status_code == 200


# ---------------------------------------------------------------------------
# CIDR helper unit tests
# ---------------------------------------------------------------------------


class TestCidrHelpers:
    """Test _parse_cidr_list and _ip_in_cidr_list helper functions."""

    @pytest.fixture(autouse=True)
    def _restore_server(self):
        yield
        _reload_server()

    def test_parse_cidr_list_loopback_defaults(self):
        """Default CIDRs parse to loopback networks."""
        import api.server as server_module

        nets = server_module._parse_cidr_list("127.0.0.0/8,::1/128")
        assert len(nets) == 2
        assert ipaddress.ip_network("127.0.0.0/8") in nets
        assert ipaddress.ip_network("::1/128") in nets

    def test_parse_cidr_list_skips_invalid(self):
        """Invalid CIDR entries are skipped."""
        import api.server as server_module

        nets = server_module._parse_cidr_list("127.0.0.0/8,not-a-cidr,192.168.1.0/24")
        assert len(nets) == 2

    def test_parse_cidr_list_empty_string(self):
        """Empty string yields empty list."""
        import api.server as server_module

        nets = server_module._parse_cidr_list("")
        assert nets == []

    def test_ip_in_cidr_list_loopback_allowed(self):
        """127.0.0.1 is in 127.0.0.0/8."""
        import api.server as server_module

        nets = server_module._parse_cidr_list("127.0.0.0/8,::1/128")
        assert server_module._ip_in_cidr_list("127.0.0.1", nets) is True

    def test_ip_in_cidr_list_ipv6_loopback_allowed(self):
        """::1 is in ::1/128."""
        import api.server as server_module

        nets = server_module._parse_cidr_list("127.0.0.0/8,::1/128")
        assert server_module._ip_in_cidr_list("::1", nets) is True

    def test_ip_in_cidr_list_external_ip_denied(self):
        """A non-loopback IP is not in the default loopback-only list."""
        import api.server as server_module

        nets = server_module._parse_cidr_list("127.0.0.0/8,::1/128")
        assert server_module._ip_in_cidr_list("203.0.113.1", nets) is False

    def test_ip_in_cidr_list_private_range_custom(self):
        """Custom CIDR can allow private ranges."""
        import api.server as server_module

        nets = server_module._parse_cidr_list("192.168.0.0/16")
        assert server_module._ip_in_cidr_list("192.168.1.100", nets) is True
        assert server_module._ip_in_cidr_list("10.0.0.1", nets) is False

    def test_ip_in_cidr_list_invalid_ip_returns_false(self):
        """An invalid IP string returns False without raising."""
        import api.server as server_module

        nets = server_module._parse_cidr_list("127.0.0.0/8")
        assert server_module._ip_in_cidr_list("not-an-ip", nets) is False


# ---------------------------------------------------------------------------
# DISABLE_AUTH IP allowlist integration tests
# ---------------------------------------------------------------------------


class TestDisableAuthIpAllowlist:
    """Test that DISABLE_AUTH_ALLOWED_IPS is enforced when DISABLE_AUTH is active.

    Note: FastAPI's TestClient sets request.client.host to "testclient" (a
    non-parseable IP string). The CIDR check is skipped for non-IP hosts since
    all real clients in production will have valid IP addresses. The unit-level
    CIDR logic is tested separately in TestCidrHelpers.
    """

    @pytest.fixture(autouse=True)
    def _restore_server(self):
        yield
        _reload_server()

    def test_non_ip_host_skips_cidr_check_and_allows(self):
        """Requests with a non-IP host (e.g. TestClient's 'testclient') skip CIDR check."""
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "true",
            "ENV": "development",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                # TestClient uses "testclient" as host; CIDR check is skipped.
                response = client.get("/health")
                assert response.status_code == 200

    def test_external_ip_denied_by_default(self):
        """Requests from a non-loopback IP are rejected when only loopback is allowed."""
        import asyncio

        server_module = _reload_server()

        async def _run() -> int:
            mock_request = MagicMock()
            mock_request.client = MagicMock()
            mock_request.client.host = "203.0.113.1"  # external, non-loopback

            with patch.dict(
                os.environ,
                {
                    "API_KEY": "",
                    "DISABLE_AUTH": "true",
                    "ENV": "development",
                    "DISABLE_AUTH_ALLOWED_IPS": "127.0.0.0/8,::1/128",
                },
            ):
                from fastapi import HTTPException

                try:
                    await server_module.verify_api_key(mock_request, None)
                    return 200
                except HTTPException as exc:
                    return exc.status_code

        status = asyncio.run(_run())
        assert status == 403

    def test_loopback_ip_allowed_by_default(self):
        """Requests from 127.0.0.1 are allowed with the default CIDR list."""
        import asyncio

        server_module = _reload_server()

        async def _run() -> int:
            mock_request = MagicMock()
            mock_request.client = MagicMock()
            mock_request.client.host = "127.0.0.1"

            with patch.dict(
                os.environ,
                {
                    "API_KEY": "",
                    "DISABLE_AUTH": "true",
                    "ENV": "development",
                    "DISABLE_AUTH_ALLOWED_IPS": "127.0.0.0/8,::1/128",
                },
            ):
                from fastapi import HTTPException

                try:
                    await server_module.verify_api_key(mock_request, None)
                    return 200
                except HTTPException as exc:
                    return exc.status_code

        status = asyncio.run(_run())
        assert status == 200

    def test_custom_cidr_allows_configured_range(self):
        """Custom DISABLE_AUTH_ALLOWED_IPS allows IPs within that range."""
        import asyncio

        server_module = _reload_server()

        async def _run() -> int:
            mock_request = MagicMock()
            mock_request.client = MagicMock()
            mock_request.client.host = "10.0.5.1"  # within 10.0.0.0/8

            with patch.dict(
                os.environ,
                {
                    "API_KEY": "",
                    "DISABLE_AUTH": "true",
                    "ENV": "development",
                    "DISABLE_AUTH_ALLOWED_IPS": "127.0.0.0/8,::1/128,10.0.0.0/8",
                },
            ):
                from fastapi import HTTPException

                try:
                    await server_module.verify_api_key(mock_request, None)
                    return 200
                except HTTPException as exc:
                    return exc.status_code

        status = asyncio.run(_run())
        assert status == 200


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

        When the session doesn't exist, 4003 is returned (unified code prevents
        session enumeration via differential close codes).
        """
        env = {
            "API_KEY": "",
            "DISABLE_AUTH": "true",
            "ENV": "development",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect("/ws/claude-code/nonexistent-session") as ws:
                        # Must still send auth message (with session_token) even when API_KEY is unset
                        ws.send_json({"type": "auth", "session_token": "any-token"})
                        ws.receive_json()
                # 4003 (unified "session not found or invalid token")
                assert exc_info.value.code == 4003

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
        """With correct auth + any session_token, nonexistent session closes with 4003.

        4003 is returned for both "session not found" and "wrong token" to prevent
        enumeration of session IDs.
        """
        env = {"API_KEY": "correct-key", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            server_module = _reload_server()
            with TestClient(server_module.app) as client:
                with pytest.raises(WebSocketDisconnect) as exc_info:
                    with client.websocket_connect("/ws/claude-code/nonexistent-session") as ws:
                        ws.send_json(
                            {"type": "auth", "api_key": "correct-key", "session_token": "tok"}
                        )
                        ws.receive_json()
                # 4003: unified "session not found or invalid token", NOT 4001 (auth failed)
                assert exc_info.value.code == 4003
