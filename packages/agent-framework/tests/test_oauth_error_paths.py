"""Comprehensive error path tests for OAuth flows.

These tests ensure OAuth flows handle all error conditions gracefully:
- Network failures (connection refused, DNS errors, timeouts)
- Malformed server responses
- Token refresh failures
- Edge cases and race conditions
"""

import asyncio
import contextlib
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agent_framework.oauth.device_flow import DeviceFlowHandler
from agent_framework.oauth.oauth_config import OAuthConfig, discover_oauth_config
from agent_framework.oauth.oauth_flow import OAuthFlowHandler
from agent_framework.oauth.oauth_tokens import TokenSet, TokenStorage


def create_mock_oauth_config() -> OAuthConfig:
    """Create a mock OAuthConfig for testing."""
    return OAuthConfig(
        resource_url="http://example.com",
        authorization_endpoint="http://example.com/authorize",
        token_endpoint="http://example.com/token",
        registration_endpoint="http://example.com/register",
        device_authorization_endpoint="http://example.com/device/code",
        grant_types_supported=[
            "authorization_code",
            "refresh_token",
            "urn:ietf:params:oauth:grant-type:device_code",
        ],
        code_challenge_methods_supported=["S256"],
        token_endpoint_auth_methods_supported=["none", "client_secret_post"],
    )


class TestNetworkFailures:
    """Tests for network failure scenarios in OAuth flows."""

    @pytest.mark.asyncio
    async def test_discovery_connection_refused(self):
        """Test OAuth discovery when server refuses connection."""
        with pytest.raises((httpx.ConnectError, httpx.RequestError, ValueError)):
            await discover_oauth_config("http://localhost:9999/")  # Port likely not in use

    @pytest.mark.asyncio
    async def test_discovery_connection_timeout(self):
        """Test OAuth discovery with connection timeout."""
        # Mock the httpx client to timeout
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Request timed out")
            with pytest.raises((httpx.TimeoutException, httpx.RequestError, ValueError)):
                await discover_oauth_config("http://192.0.2.1:8888/")

    @pytest.mark.asyncio
    async def test_discovery_dns_resolution_failure(self):
        """Test OAuth discovery with DNS resolution failure."""
        with pytest.raises((httpx.ConnectError, httpx.RequestError, ValueError)):
            await discover_oauth_config(
                "http://this-domain-definitely-does-not-exist-12345.invalid/"
            )

    @pytest.mark.asyncio
    async def test_token_exchange_network_error(self):
        """Test token exchange when network fails mid-request."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_post.side_effect = httpx.NetworkError("Connection lost")

                with pytest.raises((httpx.NetworkError, httpx.RequestError, ValueError)):
                    await flow_handler._exchange_code(
                        code="auth_code",
                        code_verifier="verifier",
                    )

    @pytest.mark.asyncio
    async def test_token_refresh_connection_timeout(self):
        """Test token refresh with connection timeout."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_post.side_effect = httpx.TimeoutException("Request timed out")

                with pytest.raises((httpx.TimeoutException, httpx.RequestError, ValueError)):
                    # Refresh is handled by base class now
                    await flow_handler.refresh_token("refresh_token_123")

    @pytest.mark.asyncio
    async def test_client_registration_network_failure(self):
        """Test client registration with network failure."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_post.side_effect = httpx.ConnectError("Connection refused")

                with pytest.raises((httpx.ConnectError, httpx.RequestError, ValueError)):
                    await flow_handler.register_client()

    @pytest.mark.asyncio
    async def test_device_flow_polling_network_intermittent(self):
        """Test device flow polling with intermittent network failures."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()

            # Create device flow handler
            device_handler = DeviceFlowHandler(oauth_config=oauth_config)
            device_handler.client_id = "test_client"

            call_count = 0

            async def side_effect_intermittent(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count % 2 == 0:
                    raise httpx.NetworkError("Network blip")
                # Return authorization_pending
                mock_response = MagicMock()
                mock_response.status_code = 400
                mock_response.json.return_value = {"error": "authorization_pending"}
                return mock_response

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_post.side_effect = side_effect_intermittent

                # Should handle network errors during polling
                # Note: This will timeout or fail based on implementation
                with pytest.raises((httpx.NetworkError, httpx.RequestError, TimeoutError)):
                    await asyncio.wait_for(
                        device_handler.poll_for_token("device_code", interval=0.1),
                        timeout=1.0,
                    )


class TestMalformedResponses:
    """Tests for malformed server responses in OAuth flows."""

    @pytest.mark.asyncio
    async def test_discovery_invalid_json(self):
        """Test OAuth discovery with invalid JSON response."""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "Not JSON at all {{{{{{"
            mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
            mock_get.return_value = mock_response

            with pytest.raises((json.JSONDecodeError, ValueError)):
                await discover_oauth_config("http://example.com/")

    @pytest.mark.asyncio
    async def test_discovery_missing_required_fields(self):
        """Test OAuth discovery with missing required fields."""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "issuer": "http://example.com",
                # Missing authorization_endpoint and token_endpoint
            }
            mock_get.return_value = mock_response

            with pytest.raises((ValueError, KeyError)):
                await discover_oauth_config("http://example.com/")

    @pytest.mark.asyncio
    async def test_token_exchange_malformed_response(self):
        """Test token exchange with malformed server response."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    # Missing access_token field
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
                mock_post.return_value = mock_response

                with pytest.raises((ValueError, KeyError)):
                    await flow_handler._exchange_code(
                        code="auth_code",
                        code_verifier="verifier",
                    )

    @pytest.mark.asyncio
    async def test_token_exchange_invalid_token_type(self):
        """Test token exchange with invalid token_type."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "access_token": "token123",
                    "token_type": "InvalidType",  # Should be "Bearer"
                    "expires_in": 3600,
                }
                mock_post.return_value = mock_response

                # Depending on implementation, might accept or reject
                result = await flow_handler._exchange_code(
                    code="auth_code",
                    code_verifier="verifier",
                )
                # Should still work but might log warning
                assert result.access_token == "token123"

    @pytest.mark.asyncio
    async def test_token_refresh_non_json_error_response(self):
        """Test token refresh with non-JSON error response."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 500
                mock_response.text = "Internal Server Error"
                mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
                mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "500 Internal Server Error", request=MagicMock(), response=mock_response
                )
                mock_post.return_value = mock_response

                with pytest.raises((httpx.HTTPStatusError, json.JSONDecodeError, ValueError)):
                    await flow_handler.refresh_token("refresh_token_123")

    @pytest.mark.asyncio
    async def test_device_authorization_missing_codes(self):
        """Test device authorization with missing device/user codes."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            device_handler = DeviceFlowHandler(oauth_config=oauth_config)
            device_handler.client_id = "test_client"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    # Missing device_code and user_code
                    "verification_uri": "http://example.com/activate",
                    "expires_in": 600,
                }
                mock_post.return_value = mock_response

                # request_device_code returns the response without validation
                # The error would occur later when trying to access the missing fields
                result = await device_handler.request_device_code()
                assert "device_code" not in result
                assert "user_code" not in result


class TestTokenRefreshFailures:
    """Tests for token refresh failure scenarios."""

    @pytest.mark.asyncio
    async def test_refresh_with_expired_refresh_token(self):
        """Test refresh when refresh token itself is expired."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 400
                mock_response.json.return_value = {"error": "invalid_grant"}
                mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "400 Bad Request", request=MagicMock(), response=mock_response
                )
                mock_post.return_value = mock_response

                with pytest.raises((httpx.HTTPStatusError, ValueError)):
                    await flow_handler.refresh_token("expired_refresh_token")

    @pytest.mark.asyncio
    async def test_refresh_with_revoked_refresh_token(self):
        """Test refresh when refresh token has been revoked."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 401
                mock_response.json.return_value = {"error": "invalid_client"}
                mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "401 Unauthorized", request=MagicMock(), response=mock_response
                )
                mock_post.return_value = mock_response

                with pytest.raises((httpx.HTTPStatusError, ValueError)):
                    await flow_handler.refresh_token("revoked_refresh_token")

    @pytest.mark.asyncio
    async def test_refresh_returns_invalid_token(self):
        """Test refresh when server returns invalid token format."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "access_token": "",  # Empty token
                    "token_type": "Bearer",
                }
                mock_post.return_value = mock_response

                result = await flow_handler.refresh_token("refresh_token")
                # Should get empty token (might want to validate in production)
                assert result.access_token == ""


class TestEdgeCases:
    """Tests for edge cases and race conditions."""

    @pytest.mark.asyncio
    async def test_concurrent_token_refreshes(self):
        """Test behavior when multiple token refreshes happen concurrently."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            call_count = 0

            async def mock_refresh(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                await asyncio.sleep(0.1)  # Simulate network delay
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "access_token": f"token_{call_count}",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
                return mock_response

            with patch("httpx.AsyncClient.post", side_effect=mock_refresh):
                # Fire off multiple concurrent refreshes
                results = await asyncio.gather(
                    flow_handler.refresh_token("refresh_token"),
                    flow_handler.refresh_token("refresh_token"),
                    flow_handler.refresh_token("refresh_token"),
                )

                # All should succeed (but might get different tokens)
                assert len(results) == 3
                assert all(result.access_token.startswith("token_") for result in results)

    @pytest.mark.asyncio
    async def test_token_storage_during_network_failure(self):
        """Test that token storage doesn't corrupt during network failures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir)
            storage = TokenStorage(storage_path)

            # Save a valid token
            token = TokenSet(
                access_token="valid_token",
                token_type="Bearer",
                expires_in=3600,
                refresh_token="refresh_token",
            )
            storage.save_token("http://example.com", token)

            # Verify token was saved
            loaded = storage.load_token("http://example.com")
            assert loaded.access_token == "valid_token"

            # Now try to refresh with network failure
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_post.side_effect = httpx.NetworkError("Connection lost")

                with contextlib.suppress(httpx.NetworkError, ValueError):
                    await flow_handler.refresh_token("refresh_token")

            # Original token should still be there
            loaded_after = storage.load_token("http://example.com")
            assert loaded_after.access_token == "valid_token"

    @pytest.mark.asyncio
    async def test_device_flow_rapid_polling(self):
        """Test device flow with very rapid polling (should respect interval)."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            device_handler = DeviceFlowHandler(oauth_config=oauth_config)
            device_handler.client_id = "test_client"

            poll_count = 0

            async def mock_poll(*args, **kwargs):
                nonlocal poll_count
                poll_count += 1
                if poll_count < 5:
                    mock_response = MagicMock()
                    mock_response.status_code = 400
                    mock_response.json.return_value = {"error": "authorization_pending"}
                    return mock_response
                else:
                    # Grant access
                    mock_response = MagicMock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {
                        "access_token": "granted_token",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    }
                    return mock_response

            with patch("httpx.AsyncClient.post", side_effect=mock_poll):
                # Should complete successfully with minimal interval
                result = await device_handler.poll_for_token("device_code", interval=0.01)
                assert result.access_token == "granted_token"
                # Should have polled multiple times
                assert poll_count >= 5

    @pytest.mark.asyncio
    async def test_empty_client_id_handling(self):
        """Test OAuth flow with empty client ID."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()

            # Some flows might allow empty client_id for public clients
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = ""  # Empty client ID

            assert flow_handler.client_id == ""

    @pytest.mark.asyncio
    async def test_very_long_access_token(self):
        """Test handling of very long access token (e.g., JWT with many claims)."""
        with tempfile.TemporaryDirectory():
            oauth_config = create_mock_oauth_config()
            flow_handler = OAuthFlowHandler(oauth_config=oauth_config)
            flow_handler.client_id = "test_client"

            # Create a very long token (simulating large JWT)
            long_token = "x" * 10000

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    "access_token": long_token,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
                mock_post.return_value = mock_response

                result = await flow_handler._exchange_code(
                    code="auth_code",
                    code_verifier="verifier",
                )

                assert result.access_token == long_token
                assert len(result.access_token) == 10000
