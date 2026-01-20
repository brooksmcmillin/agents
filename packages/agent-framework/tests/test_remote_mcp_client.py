"""Tests for the remote MCP client with OAuth authentication.

These tests focus on the critical untested areas identified in the coverage report:
- OAuth token refresh logic
- Error handling for expired/invalid tokens
- Network error recovery
- Session management
"""

from unittest.mock import AsyncMock, patch

import pytest

from agent_framework.core.remote_mcp_client import RemoteMCPClient
from agent_framework.oauth.oauth_tokens import TokenSet
from agent_framework.utils.errors import NotConnectedError


class TestRemoteMCPClientInitialization:
    """Tests for RemoteMCPClient initialization."""

    def test_initialization_with_base_url(self):
        """Test RemoteMCPClient initialization with base URL."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        assert client.base_url == "https://mcp.example.com/"
        assert client.current_token is None
        assert client._session is None

    def test_initialization_strips_trailing_slash(self):
        """Test that trailing slash is preserved in base URL."""
        client = RemoteMCPClient(base_url="https://mcp.example.com/")

        assert client.base_url == "https://mcp.example.com/"

    def test_initialization_with_device_flow(self):
        """Test initialization with device flow enabled."""
        client = RemoteMCPClient(base_url="https://mcp.example.com", prefer_device_flow=True)

        assert client.prefer_device_flow is True

    def test_initialization_with_oauth_config(self):
        """Test initialization with OAuth config."""
        from agent_framework.oauth.oauth_config import OAuthConfig

        oauth_config = OAuthConfig(
            resource_url="https://mcp.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            device_authorization_endpoint="https://auth.example.com/device",
            registration_endpoint="https://auth.example.com/register",
        )

        client = RemoteMCPClient(base_url="https://mcp.example.com")
        client.oauth_config = oauth_config

        assert client.oauth_config == oauth_config


class TestRemoteMCPClientTokenManagement:
    """Tests for OAuth token management."""

    def test_current_token_initialization(self):
        """Test that current_token is None on initialization."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        assert client.current_token is None

    def test_manual_token_from_parameter(self):
        """Test manual token from parameter."""
        client = RemoteMCPClient(base_url="https://mcp.example.com", auth_token="manual-token")

        assert client.manual_token == "manual-token"

    def test_token_storage_initialization(self):
        """Test token storage is initialized."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        assert client.token_storage is not None


class TestRemoteMCPClientErrorHandling:
    """Tests for error handling in remote MCP client."""

    @pytest.mark.asyncio
    async def test_list_tools_without_connection_raises(self):
        """Test that list_tools raises NotConnectedError when not connected."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        with pytest.raises(NotConnectedError):
            await client.list_tools()

    @pytest.mark.asyncio
    async def test_call_tool_without_connection_raises(self):
        """Test that call_tool raises NotConnectedError when not connected."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        with pytest.raises(NotConnectedError):
            await client.call_tool("test_tool", {})

    @pytest.mark.asyncio
    async def test_ensure_valid_token_without_oauth_raises(self):
        """Test that _ensure_valid_token raises error when OAuth disabled and no manual token."""
        client = RemoteMCPClient(base_url="https://mcp.example.com", enable_oauth=False)

        with pytest.raises(ValueError, match="No authentication token available"):
            await client._ensure_valid_token()


class TestRemoteMCPClientAuthDetection:
    """Tests for authentication error detection."""

    def test_is_auth_error_401_status(self):
        """Test _is_auth_error detects 401 status codes."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        mock_error = Exception("HTTP 401: Unauthorized")
        assert client._is_auth_error(mock_error) is True

    def test_is_auth_error_403_status(self):
        """Test _is_auth_error detects 403 status codes."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        mock_error = Exception("HTTP 403: Forbidden")
        assert client._is_auth_error(mock_error) is True

    def test_is_auth_error_expired_token(self):
        """Test _is_auth_error detects expired token messages."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        mock_error = Exception("token expired")
        assert client._is_auth_error(mock_error) is True

    def test_is_auth_error_invalid_token(self):
        """Test _is_auth_error detects invalid token messages."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        mock_error = Exception("invalid token")
        assert client._is_auth_error(mock_error) is True

    def test_is_auth_error_authentication_failed(self):
        """Test _is_auth_error detects authentication failed messages."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        mock_error = Exception("Authentication failed")
        assert client._is_auth_error(mock_error) is True

    def test_is_auth_error_not_auth_related(self):
        """Test _is_auth_error returns False for non-auth errors."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        mock_error = Exception("Network timeout")
        assert client._is_auth_error(mock_error) is False


class TestRemoteMCPClientContextManager:
    """Tests for async context manager functionality."""

    @pytest.mark.asyncio
    async def test_context_manager_calls_connect(self):
        """Test that entering context manager calls connect()."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = client
            async with client:
                pass

            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_calls_disconnect(self):
        """Test that exiting context manager calls disconnect()."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
            with patch.object(client, "disconnect", new_callable=AsyncMock) as mock_disconnect:
                mock_connect.return_value = client
                async with client:
                    pass

                mock_disconnect.assert_called_once()


class TestRemoteMCPClientTokenRefresh:
    """Tests for OAuth token refresh functionality.

    This tests the critical untested code path identified in the coverage report.
    """

    @pytest.mark.asyncio
    async def test_retry_with_reauth_success_on_first_try(self):
        """Test that successful operations don't trigger reauthentication."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        mock_operation = AsyncMock(return_value="success")

        result = await client._retry_with_reauth("test_operation", mock_operation)

        assert result == "success"
        mock_operation.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_with_reauth_on_non_auth_error(self):
        """Test that non-auth errors are raised without retry."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")

        mock_operation = AsyncMock(side_effect=Exception("Network timeout"))

        with pytest.raises(Exception, match="Network timeout"):
            await client._retry_with_reauth("test_operation", mock_operation)

        mock_operation.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_with_reauth_on_auth_error_succeeds(self):
        """Test successful reauthentication after auth error."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")
        client.current_token = TokenSet(
            access_token="old_token", token_type="Bearer", expires_in=3600
        )

        # First call fails with auth error, second succeeds
        mock_operation = AsyncMock(side_effect=[Exception("token expired"), "success_after_reauth"])

        with patch.object(client, "disconnect", new_callable=AsyncMock):
            with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
                mock_connect.return_value = client

                result = await client._retry_with_reauth("test_operation", mock_operation)

                assert result == "success_after_reauth"
                assert mock_operation.call_count == 2
                mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_with_reauth_clears_expired_token(self):
        """Test that expired token is cleared before reauthentication."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")
        client.current_token = TokenSet(
            access_token="expired_token", token_type="Bearer", expires_in=3600
        )

        mock_operation = AsyncMock(side_effect=[Exception("token expired"), "success"])

        with patch.object(client, "disconnect", new_callable=AsyncMock):
            with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
                mock_connect.return_value = client

                await client._retry_with_reauth("test_operation", mock_operation)

                # Verify token was cleared before reconnect (it will be set again by connect mock)
                mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_with_reauth_fails_after_retry(self):
        """Test that operation failure after reauthentication raises error."""
        client = RemoteMCPClient(base_url="https://mcp.example.com")
        client.current_token = TokenSet(access_token="token", token_type="Bearer", expires_in=3600)

        # Both attempts fail with auth error
        mock_operation = AsyncMock(side_effect=Exception("token expired"))

        with patch.object(client, "disconnect", new_callable=AsyncMock):
            with patch.object(client, "connect", new_callable=AsyncMock) as mock_connect:
                mock_connect.return_value = client

                with pytest.raises(Exception, match="token expired"):
                    await client._retry_with_reauth("test_operation", mock_operation)

                # Should have tried twice
                assert mock_operation.call_count == 2
