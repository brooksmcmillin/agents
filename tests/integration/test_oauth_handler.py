"""Tests for the OAuthHandler class.

Tests cover OAuth flows, token refresh, authorization URL generation, and error handling.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from config.mcp_server.auth.oauth_handler import OAuthHandler
from config.mcp_server.auth.token_store import TokenData, TokenStore


class TestOAuthHandler:
    """Tests for the OAuthHandler class."""

    @pytest.fixture
    def token_store(self, tmp_path: Path) -> TokenStore:
        """Create a temporary token store."""
        return TokenStore(storage_path=tmp_path / "tokens")

    @pytest.fixture
    def oauth_handler(self, token_store: TokenStore) -> OAuthHandler:
        """Create an OAuthHandler with test credentials."""
        return OAuthHandler(
            token_store=token_store,
            client_id="test_client_id",
            client_secret="test_client_secret",  # pragma: allowlist secret
        )

    # --- Authorization URL Tests ---

    def test_get_authorization_url_twitter(self, oauth_handler: OAuthHandler):
        """Test generating Twitter authorization URL."""
        url = oauth_handler.get_authorization_url(
            platform="twitter",
            redirect_uri="http://localhost:8080/callback",
        )

        assert "twitter.com" in url
        assert "client_id=test_client_id" in url
        assert "redirect_uri=http" in url
        assert "response_type=code" in url
        assert "scope=" in url

    def test_get_authorization_url_linkedin(self, oauth_handler: OAuthHandler):
        """Test generating LinkedIn authorization URL."""
        url = oauth_handler.get_authorization_url(
            platform="linkedin",
            redirect_uri="http://localhost:8080/callback",
        )

        assert "linkedin.com" in url
        assert "client_id=test_client_id" in url

    def test_authorization_url_includes_state(self, oauth_handler: OAuthHandler):
        """Test that CSRF state parameter is included in authorization URL."""
        url = oauth_handler.get_authorization_url(
            platform="twitter",
            redirect_uri="http://localhost:8080/callback",
            state="random_csrf_token_12345",
        )

        assert "state=random_csrf_token_12345" in url

    def test_authorization_url_without_state(self, oauth_handler: OAuthHandler):
        """Test authorization URL without state parameter."""
        url = oauth_handler.get_authorization_url(
            platform="twitter",
            redirect_uri="http://localhost:8080/callback",
        )

        # URL should not contain state parameter
        assert "state=" not in url

    def test_unsupported_platform_raises_error(self, oauth_handler: OAuthHandler):
        """Test that unsupported platform raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported platform"):
            oauth_handler.get_authorization_url(
                platform="unsupported_platform",
                redirect_uri="http://localhost/callback",
            )

    def test_authorization_url_includes_scopes(self, oauth_handler: OAuthHandler):
        """Test that authorization URL includes platform-specific scopes."""
        url = oauth_handler.get_authorization_url(
            platform="twitter",
            redirect_uri="http://localhost/callback",
        )

        # Twitter scopes should be present
        assert "tweet.read" in url or "scope=" in url

    # --- Token Exchange Tests ---

    @pytest.mark.asyncio
    async def test_exchange_code_unsupported_platform(
        self, oauth_handler: OAuthHandler
    ):
        """Test that exchange_code_for_token returns None for unsupported platform."""
        result = await oauth_handler.exchange_code_for_token(
            platform="unsupported",
            code="auth_code",
            redirect_uri="http://localhost/callback",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_exchange_code_success(self, oauth_handler: OAuthHandler):
        """Test successful code exchange for token."""
        mock_token_response = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "tweet.read users.read",
        }

        with patch(
            "config.mcp_server.auth.oauth_handler.AsyncOAuth2Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.fetch_token = AsyncMock(return_value=mock_token_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            result = await oauth_handler.exchange_code_for_token(
                platform="twitter",
                code="authorization_code",
                redirect_uri="http://localhost/callback",
                user_id="test_user",
            )

            assert result is not None
            assert result.access_token == "new_access_token"
            assert result.refresh_token == "new_refresh_token"
            assert result.expires_at is not None

    @pytest.mark.asyncio
    async def test_exchange_code_failure(self, oauth_handler: OAuthHandler):
        """Test that exchange_code_for_token returns None on failure."""
        with patch(
            "config.mcp_server.auth.oauth_handler.AsyncOAuth2Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.fetch_token = AsyncMock(
                side_effect=Exception("OAuth server error")
            )
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            result = await oauth_handler.exchange_code_for_token(
                platform="twitter",
                code="invalid_code",
                redirect_uri="http://localhost/callback",
            )

            assert result is None

    # --- Token Refresh Tests ---

    @pytest.mark.asyncio
    async def test_refresh_token_no_existing_token(self, oauth_handler: OAuthHandler):
        """Test refresh returns None when no token exists."""
        result = await oauth_handler.refresh_token("twitter", "nonexistent_user")
        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_token_no_refresh_token(
        self, oauth_handler: OAuthHandler, token_store: TokenStore
    ):
        """Test refresh returns None when token has no refresh_token."""
        # Save token without refresh_token
        token = TokenData(access_token="access_only")
        token_store.save_token("twitter", token, "user1")

        result = await oauth_handler.refresh_token("twitter", "user1")
        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_token_unsupported_platform(
        self, oauth_handler: OAuthHandler, token_store: TokenStore
    ):
        """Test refresh returns None for unsupported platform."""
        result = await oauth_handler.refresh_token("unsupported_platform")
        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_preserves_refresh_token(
        self, oauth_handler: OAuthHandler, token_store: TokenStore
    ):
        """Test that refresh token is preserved if not returned by provider."""
        # Save initial token with refresh token
        initial_token = TokenData(
            access_token="old_access",
            refresh_token="my_precious_refresh_token",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        token_store.save_token("twitter", initial_token)

        # Mock the OAuth client to return token WITHOUT refresh_token
        mock_response = {
            "access_token": "new_access_token",
            "expires_in": 3600,
            # Note: no refresh_token in response
        }

        with patch(
            "config.mcp_server.auth.oauth_handler.AsyncOAuth2Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.fetch_token = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            refreshed = await oauth_handler.refresh_token("twitter")

            # Should preserve original refresh token
            assert refreshed is not None
            assert refreshed.refresh_token == "my_precious_refresh_token"
            assert refreshed.access_token == "new_access_token"

    @pytest.mark.asyncio
    async def test_refresh_updates_refresh_token_if_provided(
        self, oauth_handler: OAuthHandler, token_store: TokenStore
    ):
        """Test that new refresh token replaces old one if provided."""
        initial_token = TokenData(
            access_token="old_access",
            refresh_token="old_refresh",
        )
        token_store.save_token("twitter", initial_token)

        mock_response = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",  # New refresh token provided
            "expires_in": 3600,
        }

        with patch(
            "config.mcp_server.auth.oauth_handler.AsyncOAuth2Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.fetch_token = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            refreshed = await oauth_handler.refresh_token("twitter")

            assert refreshed is not None
            assert refreshed.refresh_token == "new_refresh"

    @pytest.mark.asyncio
    async def test_refresh_failure_returns_none(
        self, oauth_handler: OAuthHandler, token_store: TokenStore
    ):
        """Test that refresh returns None on OAuth failure."""
        initial_token = TokenData(
            access_token="old_access",
            refresh_token="refresh",
        )
        token_store.save_token("twitter", initial_token)

        with patch(
            "config.mcp_server.auth.oauth_handler.AsyncOAuth2Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.fetch_token = AsyncMock(side_effect=Exception("Refresh failed"))
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            result = await oauth_handler.refresh_token("twitter")
            assert result is None

    # --- Get Valid Token Tests ---

    @pytest.mark.asyncio
    async def test_get_valid_token_no_token(self, oauth_handler: OAuthHandler):
        """Test get_valid_token returns None when no token exists."""
        result = await oauth_handler.get_valid_token("twitter", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_valid_token_returns_non_expired(
        self, oauth_handler: OAuthHandler, token_store: TokenStore
    ):
        """Test get_valid_token returns token if not expired."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        token = TokenData(
            access_token="valid_token",
            expires_at=future,
        )
        token_store.save_token("twitter", token)

        result = await oauth_handler.get_valid_token("twitter")

        assert result is not None
        assert result.access_token == "valid_token"

    @pytest.mark.asyncio
    async def test_get_valid_token_auto_refreshes_expired(
        self, oauth_handler: OAuthHandler, token_store: TokenStore
    ):
        """Test get_valid_token auto-refreshes expired tokens."""
        # Save expired token
        expired = TokenData(
            access_token="expired_access",
            refresh_token="my_refresh",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        token_store.save_token("twitter", expired)

        mock_response = {
            "access_token": "refreshed_access",
            "expires_in": 3600,
        }

        with patch(
            "config.mcp_server.auth.oauth_handler.AsyncOAuth2Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.fetch_token = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            result = await oauth_handler.get_valid_token("twitter")

            assert result is not None
            assert result.access_token == "refreshed_access"

    @pytest.mark.asyncio
    async def test_get_valid_token_returns_none_if_refresh_fails(
        self, oauth_handler: OAuthHandler, token_store: TokenStore
    ):
        """Test get_valid_token returns None if refresh fails."""
        expired = TokenData(
            access_token="expired",
            refresh_token="refresh",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        token_store.save_token("twitter", expired)

        with patch(
            "config.mcp_server.auth.oauth_handler.AsyncOAuth2Client"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.fetch_token = AsyncMock(side_effect=Exception("Refresh failed"))
            mock_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_client

            result = await oauth_handler.get_valid_token("twitter")
            assert result is None

    # --- Token Response Parsing Tests ---

    def test_parse_token_response_basic(self, oauth_handler: OAuthHandler):
        """Test parsing basic token response."""
        response = {
            "access_token": "access123",
            "token_type": "Bearer",
        }

        token = oauth_handler._parse_token_response(response)

        assert token.access_token == "access123"
        assert token.token_type == "Bearer"
        assert token.refresh_token is None
        assert token.expires_at is None

    def test_parse_token_response_with_expiration(self, oauth_handler: OAuthHandler):
        """Test parsing token response with expires_in."""
        response = {
            "access_token": "access123",
            "expires_in": 3600,  # 1 hour
        }

        before = datetime.now(timezone.utc)
        token = oauth_handler._parse_token_response(response)
        after = datetime.now(timezone.utc)

        assert token.expires_at is not None
        # Should be approximately 1 hour from now
        expected_min = before + timedelta(seconds=3600)
        expected_max = after + timedelta(seconds=3600)
        assert expected_min <= token.expires_at <= expected_max

    def test_parse_token_response_with_refresh(self, oauth_handler: OAuthHandler):
        """Test parsing token response with refresh token."""
        response = {
            "access_token": "access123",
            "refresh_token": "refresh456",
        }

        token = oauth_handler._parse_token_response(response)
        assert token.refresh_token == "refresh456"

    def test_parse_token_response_with_scope(self, oauth_handler: OAuthHandler):
        """Test parsing token response with scope."""
        response = {
            "access_token": "access123",
            "scope": "read write delete",
        }

        token = oauth_handler._parse_token_response(response)
        assert token.scope == "read write delete"

    # --- Revoke Token Tests ---

    @pytest.mark.asyncio
    async def test_revoke_token_deletes_from_store(
        self, oauth_handler: OAuthHandler, token_store: TokenStore
    ):
        """Test that revoke_token deletes token from storage."""
        token = TokenData(access_token="to_revoke")
        token_store.save_token("twitter", token, "user1")

        result = await oauth_handler.revoke_token("twitter", "user1")

        assert result is True
        assert token_store.get_token("twitter", "user1") is None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_token(self, oauth_handler: OAuthHandler):
        """Test revoking a token that doesn't exist returns True."""
        result = await oauth_handler.revoke_token("twitter", "nonexistent")
        assert result is True


class TestOAuthHandlerEdgeCases:
    """Edge case tests for OAuthHandler."""

    @pytest.fixture
    def token_store(self, tmp_path: Path) -> TokenStore:
        return TokenStore(storage_path=tmp_path / "tokens")

    def test_handler_without_credentials(self, token_store: TokenStore):
        """Test creating handler without client credentials."""
        handler = OAuthHandler(token_store=token_store)

        assert handler.client_id is None
        assert handler.client_secret is None

        # Should still be able to generate URLs (with None client_id)
        url = handler.get_authorization_url(
            platform="twitter",
            redirect_uri="http://localhost/callback",
        )
        assert "client_id=None" in url

    def test_platform_configs_exist(self, token_store: TokenStore):
        """Test that platform configs are properly defined."""
        handler = OAuthHandler(token_store=token_store)

        assert "twitter" in handler.PLATFORM_CONFIGS
        assert "linkedin" in handler.PLATFORM_CONFIGS

        for platform, config in handler.PLATFORM_CONFIGS.items():
            assert "authorize_url" in config
            assert "token_url" in config
            assert "scopes" in config
            assert isinstance(config["scopes"], list)
