"""Tests for shared authentication utilities.

Tests cover token retrieval, validation, refresh flows, and error handling
for the centralized token management used by all agents.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shared.auth_utils import get_valid_token_for_mcp


@pytest.fixture
def mock_token_storage():
    """Create a mock TokenStorage."""
    return MagicMock()


@pytest.fixture
def valid_token():
    """Create a valid (non-expired) token."""
    token = MagicMock()
    token.access_token = "valid_access_token_123"
    token.refresh_token = "refresh_token_456"
    token.client_id = "client_id_789"
    token.client_secret = "client_secret_abc"  # pragma: allowlist secret
    token.is_expired.return_value = False
    token.expires_at = datetime.now(UTC) + timedelta(hours=1)
    return token


@pytest.fixture
def expired_token():
    """Create an expired token with refresh token."""
    token = MagicMock()
    token.access_token = "expired_access_token_123"
    token.refresh_token = "refresh_token_456"
    token.client_id = "client_id_789"
    token.client_secret = "client_secret_abc"  # pragma: allowlist secret
    token.is_expired.return_value = True
    token.expires_at = datetime.now(UTC) - timedelta(hours=1)
    return token


@pytest.fixture
def expired_token_no_refresh():
    """Create an expired token without refresh token."""
    token = MagicMock()
    token.access_token = "expired_access_token_123"
    token.refresh_token = None
    token.client_id = "client_id_789"
    token.client_secret = "client_secret_abc"  # pragma: allowlist secret
    token.is_expired.return_value = True
    return token


@pytest.fixture
def expired_token_no_client_id():
    """Create an expired token without client_id."""
    token = MagicMock()
    token.access_token = "expired_access_token_123"
    token.refresh_token = "refresh_token_456"
    token.client_id = None
    token.client_secret = "client_secret_abc"  # pragma: allowlist secret
    token.is_expired.return_value = True
    return token


@pytest.fixture
def refreshed_token():
    """Create a refreshed token."""
    token = MagicMock()
    token.access_token = "new_access_token_999"
    token.refresh_token = "new_refresh_token_888"
    token.is_expired.return_value = False
    return token


class TestGetValidTokenForMCP:
    """Tests for get_valid_token_for_mcp function."""

    @pytest.mark.asyncio
    @patch("shared.auth_utils.TokenStorage")
    async def test_no_token_found(self, mock_storage_class):
        """Test when no token is saved for the MCP URL."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = None
        mock_storage_class.return_value = mock_storage

        result = await get_valid_token_for_mcp("https://mcp.example.com")

        assert result is None
        mock_storage.load_token.assert_called_once_with("https://mcp.example.com/")

    @pytest.mark.asyncio
    @patch("shared.auth_utils.TokenStorage")
    async def test_url_normalization_adds_trailing_slash(self, mock_storage_class):
        """Test that URL without trailing slash gets normalized."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = None
        mock_storage_class.return_value = mock_storage

        await get_valid_token_for_mcp("https://mcp.example.com")

        # Should add trailing slash
        mock_storage.load_token.assert_called_once_with("https://mcp.example.com/")

    @pytest.mark.asyncio
    @patch("shared.auth_utils.TokenStorage")
    async def test_url_normalization_keeps_trailing_slash(self, mock_storage_class):
        """Test that URL with trailing slash is not modified."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = None
        mock_storage_class.return_value = mock_storage

        await get_valid_token_for_mcp("https://mcp.example.com/")

        # Should keep trailing slash
        mock_storage.load_token.assert_called_once_with("https://mcp.example.com/")

    @pytest.mark.asyncio
    @patch("shared.auth_utils.TokenStorage")
    async def test_valid_token_returned_immediately(
        self, mock_storage_class, valid_token
    ):
        """Test that valid (non-expired) token is returned without refresh."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = valid_token
        mock_storage_class.return_value = mock_storage

        result = await get_valid_token_for_mcp("https://mcp.example.com")

        assert result == "valid_access_token_123"
        valid_token.is_expired.assert_called_once()
        # Should not attempt to save or refresh
        mock_storage.save_token.assert_not_called()

    @pytest.mark.asyncio
    @patch("shared.auth_utils.TokenStorage")
    async def test_expired_token_no_refresh_token(
        self, mock_storage_class, expired_token_no_refresh
    ):
        """Test expired token without refresh token returns None."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = expired_token_no_refresh
        mock_storage_class.return_value = mock_storage

        result = await get_valid_token_for_mcp("https://mcp.example.com")

        assert result is None
        expired_token_no_refresh.is_expired.assert_called_once()

    @pytest.mark.asyncio
    @patch("shared.auth_utils.TokenStorage")
    async def test_expired_token_no_client_id(
        self, mock_storage_class, expired_token_no_client_id
    ):
        """Test expired token without client_id returns None."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = expired_token_no_client_id
        mock_storage_class.return_value = mock_storage

        result = await get_valid_token_for_mcp("https://mcp.example.com")

        assert result is None
        expired_token_no_client_id.is_expired.assert_called_once()

    @pytest.mark.asyncio
    @patch("shared.auth_utils.OAuthFlowHandler")
    @patch("shared.auth_utils.discover_oauth_config")
    @patch("shared.auth_utils.TokenStorage")
    async def test_successful_token_refresh(
        self,
        mock_storage_class,
        mock_discover,
        mock_oauth_handler_class,
        expired_token,
        refreshed_token,
    ):
        """Test successful token refresh flow."""
        # Setup mocks
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = expired_token
        mock_storage_class.return_value = mock_storage

        mock_oauth_config = MagicMock()
        mock_discover.return_value = mock_oauth_config

        mock_oauth_handler = MagicMock()
        mock_oauth_handler.refresh_token = AsyncMock(return_value=refreshed_token)
        mock_oauth_handler_class.return_value = mock_oauth_handler

        # Execute
        result = await get_valid_token_for_mcp("https://mcp.example.com")

        # Verify
        assert result == "new_access_token_999"

        # Check OAuth config discovery
        mock_discover.assert_called_once_with("https://mcp.example.com/")

        # Check OAuth handler creation
        mock_oauth_handler_class.assert_called_once_with(mock_oauth_config)

        # Check token refresh call
        mock_oauth_handler.refresh_token.assert_called_once_with(
            "refresh_token_456",
            client_id="client_id_789",
            client_secret="client_secret_abc",  # pragma: allowlist secret
        )

        # Check token was saved
        mock_storage.save_token.assert_called_once_with(
            "https://mcp.example.com/", refreshed_token
        )

    @pytest.mark.asyncio
    @patch("shared.auth_utils.OAuthFlowHandler")
    @patch("shared.auth_utils.discover_oauth_config")
    @patch("shared.auth_utils.TokenStorage")
    async def test_token_refresh_http_error(
        self, mock_storage_class, mock_discover, mock_oauth_handler_class, expired_token
    ):
        """Test token refresh failure with HTTPError returns None."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = expired_token
        mock_storage_class.return_value = mock_storage

        mock_oauth_config = MagicMock()
        mock_discover.return_value = mock_oauth_config

        mock_oauth_handler = MagicMock()
        mock_oauth_handler.refresh_token = AsyncMock(
            side_effect=httpx.HTTPError("Server error")
        )
        mock_oauth_handler_class.return_value = mock_oauth_handler

        result = await get_valid_token_for_mcp("https://mcp.example.com")

        assert result is None
        mock_storage.save_token.assert_not_called()

    @pytest.mark.asyncio
    @patch("shared.auth_utils.OAuthFlowHandler")
    @patch("shared.auth_utils.discover_oauth_config")
    @patch("shared.auth_utils.TokenStorage")
    async def test_token_refresh_value_error(
        self, mock_storage_class, mock_discover, mock_oauth_handler_class, expired_token
    ):
        """Test token refresh failure with ValueError returns None."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = expired_token
        mock_storage_class.return_value = mock_storage

        mock_oauth_config = MagicMock()
        mock_discover.return_value = mock_oauth_config

        mock_oauth_handler = MagicMock()
        mock_oauth_handler.refresh_token = AsyncMock(
            side_effect=ValueError("Invalid token format")
        )
        mock_oauth_handler_class.return_value = mock_oauth_handler

        result = await get_valid_token_for_mcp("https://mcp.example.com")

        assert result is None
        mock_storage.save_token.assert_not_called()

    @pytest.mark.asyncio
    @patch("shared.auth_utils.OAuthFlowHandler")
    @patch("shared.auth_utils.discover_oauth_config")
    @patch("shared.auth_utils.TokenStorage")
    async def test_token_refresh_key_error(
        self, mock_storage_class, mock_discover, mock_oauth_handler_class, expired_token
    ):
        """Test token refresh failure with KeyError returns None."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = expired_token
        mock_storage_class.return_value = mock_storage

        mock_oauth_config = MagicMock()
        mock_discover.return_value = mock_oauth_config

        mock_oauth_handler = MagicMock()
        mock_oauth_handler.refresh_token = AsyncMock(
            side_effect=KeyError("access_token")
        )
        mock_oauth_handler_class.return_value = mock_oauth_handler

        result = await get_valid_token_for_mcp("https://mcp.example.com")

        assert result is None
        mock_storage.save_token.assert_not_called()

    @pytest.mark.asyncio
    @patch("shared.auth_utils.OAuthFlowHandler")
    @patch("shared.auth_utils.discover_oauth_config")
    @patch("shared.auth_utils.TokenStorage")
    async def test_token_refresh_unexpected_error_raises(
        self, mock_storage_class, mock_discover, mock_oauth_handler_class, expired_token
    ):
        """Test that unexpected errors during refresh are re-raised."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = expired_token
        mock_storage_class.return_value = mock_storage

        mock_oauth_config = MagicMock()
        mock_discover.return_value = mock_oauth_config

        mock_oauth_handler = MagicMock()
        mock_oauth_handler.refresh_token = AsyncMock(
            side_effect=RuntimeError("Unexpected error")
        )
        mock_oauth_handler_class.return_value = mock_oauth_handler

        with pytest.raises(RuntimeError, match="Unexpected error"):
            await get_valid_token_for_mcp("https://mcp.example.com")

        mock_storage.save_token.assert_not_called()

    @pytest.mark.asyncio
    @patch("shared.auth_utils.discover_oauth_config")
    @patch("shared.auth_utils.TokenStorage")
    async def test_oauth_discovery_failure(
        self, mock_storage_class, mock_discover, expired_token
    ):
        """Test token refresh when OAuth discovery fails."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = expired_token
        mock_storage_class.return_value = mock_storage

        mock_discover.side_effect = httpx.HTTPError("Discovery failed")

        result = await get_valid_token_for_mcp("https://mcp.example.com")

        assert result is None
        mock_storage.save_token.assert_not_called()

    @pytest.mark.asyncio
    @patch("shared.auth_utils.TokenStorage")
    async def test_logging_no_token_found(self, mock_storage_class, caplog):
        """Test that appropriate warning is logged when no token found."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = None
        mock_storage_class.return_value = mock_storage

        await get_valid_token_for_mcp("https://mcp.example.com")

        assert "No saved token found" in caplog.text
        assert "https://mcp.example.com/" in caplog.text

    @pytest.mark.asyncio
    @patch("shared.auth_utils.TokenStorage")
    async def test_logging_valid_token(self, mock_storage_class, valid_token, caplog):
        """Test that info is logged when using valid token."""
        import logging

        caplog.set_level(logging.INFO)

        mock_storage = MagicMock()
        mock_storage.load_token.return_value = valid_token
        mock_storage_class.return_value = mock_storage

        await get_valid_token_for_mcp("https://mcp.example.com")

        assert "Using valid token from storage" in caplog.text

    @pytest.mark.asyncio
    @patch("shared.auth_utils.OAuthFlowHandler")
    @patch("shared.auth_utils.discover_oauth_config")
    @patch("shared.auth_utils.TokenStorage")
    async def test_logging_token_refresh_success(
        self,
        mock_storage_class,
        mock_discover,
        mock_oauth_handler_class,
        expired_token,
        refreshed_token,
        caplog,
    ):
        """Test that success is logged after token refresh."""
        import logging

        caplog.set_level(logging.INFO)

        mock_storage = MagicMock()
        mock_storage.load_token.return_value = expired_token
        mock_storage_class.return_value = mock_storage

        mock_oauth_config = MagicMock()
        mock_discover.return_value = mock_oauth_config

        mock_oauth_handler = MagicMock()
        mock_oauth_handler.refresh_token = AsyncMock(return_value=refreshed_token)
        mock_oauth_handler_class.return_value = mock_oauth_handler

        await get_valid_token_for_mcp("https://mcp.example.com")

        assert "Token expired, attempting refresh" in caplog.text
        assert "Token refreshed successfully" in caplog.text

    @pytest.mark.asyncio
    @patch("shared.auth_utils.OAuthFlowHandler")
    @patch("shared.auth_utils.discover_oauth_config")
    @patch("shared.auth_utils.TokenStorage")
    async def test_logging_token_refresh_failure(
        self,
        mock_storage_class,
        mock_discover,
        mock_oauth_handler_class,
        expired_token,
        caplog,
    ):
        """Test that error is logged on token refresh failure."""
        mock_storage = MagicMock()
        mock_storage.load_token.return_value = expired_token
        mock_storage_class.return_value = mock_storage

        mock_oauth_config = MagicMock()
        mock_discover.return_value = mock_oauth_config

        mock_oauth_handler = MagicMock()
        mock_oauth_handler.refresh_token = AsyncMock(
            side_effect=httpx.HTTPError("Network error")
        )
        mock_oauth_handler_class.return_value = mock_oauth_handler

        await get_valid_token_for_mcp("https://mcp.example.com")

        assert "Failed to refresh token" in caplog.text
