"""Tests for OAuth 2.0 Authorization Code Flow with PKCE.

This module tests the OAuth flow implementation including:
- PKCE code generation
- Client registration
- OAuth discovery
- Token exchange
- Token storage and retrieval
"""

import hashlib
import json
import tempfile
import time
from base64 import urlsafe_b64encode
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_framework.oauth.oauth_config import OAuthConfig, discover_oauth_config
from agent_framework.oauth.oauth_flow import OAuthFlowHandler, generate_pkce_pair
from agent_framework.oauth.oauth_tokens import TokenSet, TokenStorage


class TestPKCEGeneration:
    """Tests for PKCE code verifier and challenge generation."""

    def test_generate_pkce_pair_returns_tuple(self) -> None:
        """Test that generate_pkce_pair returns a tuple of two strings."""
        result = generate_pkce_pair()
        assert isinstance(result, tuple)
        assert len(result) == 2
        verifier, challenge = result
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

    def test_generate_pkce_verifier_length(self) -> None:
        """Test that code verifier is at least 43 characters (RFC 7636)."""
        verifier, _ = generate_pkce_pair()
        # Base64 encoding of 32 bytes = 43 characters (without padding)
        assert len(verifier) >= 43

    def test_generate_pkce_verifier_characters(self) -> None:
        """Test that code verifier contains only valid characters."""
        verifier, _ = generate_pkce_pair()
        # RFC 7636: unreserved characters [A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~"
        valid_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        assert all(c in valid_chars for c in verifier)

    def test_generate_pkce_challenge_is_sha256_of_verifier(self) -> None:
        """Test that code challenge is SHA256 hash of verifier."""
        verifier, challenge = generate_pkce_pair()

        # Compute expected challenge
        expected_challenge = (
            urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
            .decode("utf-8")
            .rstrip("=")
        )

        assert challenge == expected_challenge

    def test_generate_pkce_pair_is_unique(self) -> None:
        """Test that each call generates unique values."""
        pair1 = generate_pkce_pair()
        pair2 = generate_pkce_pair()

        assert pair1[0] != pair2[0]  # Different verifiers
        assert pair1[1] != pair2[1]  # Different challenges


class TestOAuthConfig:
    """Tests for OAuthConfig dataclass and helper methods."""

    @pytest.fixture
    def full_oauth_config(self) -> OAuthConfig:
        """Create a fully-configured OAuthConfig."""
        return OAuthConfig(
            resource_url="https://mcp.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            registration_endpoint="https://auth.example.com/register",
            device_authorization_endpoint="https://auth.example.com/device/code",
            scopes_supported=["read", "write", "admin"],
            response_types_supported=["code"],
            grant_types_supported=["authorization_code", "refresh_token"],
            code_challenge_methods_supported=["S256", "plain"],
            token_endpoint_auth_methods_supported=["client_secret_post", "none"],
        )

    @pytest.fixture
    def minimal_oauth_config(self) -> OAuthConfig:
        """Create a minimal OAuthConfig with only required fields."""
        return OAuthConfig(
            resource_url="https://mcp.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
        )

    def test_supports_pkce_with_s256(self, full_oauth_config: OAuthConfig) -> None:
        """Test PKCE support detection with S256."""
        assert full_oauth_config.supports_pkce() is True

    def test_supports_pkce_without_methods(self, minimal_oauth_config: OAuthConfig) -> None:
        """Test PKCE support returns False when not configured."""
        assert minimal_oauth_config.supports_pkce() is False

    def test_supports_pkce_without_s256(self) -> None:
        """Test PKCE support returns False without S256."""
        config = OAuthConfig(
            resource_url="https://mcp.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            code_challenge_methods_supported=["plain"],  # No S256
        )
        assert config.supports_pkce() is False

    def test_supports_public_clients_with_none(self, full_oauth_config: OAuthConfig) -> None:
        """Test public client support detection."""
        assert full_oauth_config.supports_public_clients() is True

    def test_supports_public_clients_without_none(self) -> None:
        """Test public client support returns False without 'none' method."""
        config = OAuthConfig(
            resource_url="https://mcp.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            token_endpoint_auth_methods_supported=["client_secret_post"],
        )
        assert config.supports_public_clients() is False

    def test_supports_public_clients_not_configured(
        self, minimal_oauth_config: OAuthConfig
    ) -> None:
        """Test public client support returns False when not configured."""
        assert minimal_oauth_config.supports_public_clients() is False


class TestDiscoverOAuthConfig:
    """Tests for OAuth discovery from .well-known endpoints."""

    @pytest.fixture
    def resource_metadata(self) -> dict:
        """Sample protected resource metadata."""
        return {
            "resource": "https://mcp.example.com",
            "authorization_servers": ["https://auth.example.com"],
        }

    @pytest.fixture
    def auth_server_metadata(self) -> dict:
        """Sample authorization server metadata."""
        return {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "registration_endpoint": "https://auth.example.com/register",
            "scopes_supported": ["read", "write"],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
        }

    @pytest.mark.asyncio
    async def test_discover_oauth_config_success(
        self, resource_metadata: dict, auth_server_metadata: dict
    ) -> None:
        """Test successful OAuth discovery."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            # Mock both discovery endpoints
            resource_response = MagicMock()
            resource_response.json.return_value = resource_metadata
            resource_response.raise_for_status = MagicMock()

            auth_response = MagicMock()
            auth_response.json.return_value = auth_server_metadata
            auth_response.raise_for_status = MagicMock()

            mock_client.get = AsyncMock(side_effect=[resource_response, auth_response])

            config = await discover_oauth_config("https://mcp.example.com/mcp/")

            assert config.resource_url == "https://mcp.example.com"
            assert config.authorization_endpoint == "https://auth.example.com/authorize"
            assert config.token_endpoint == "https://auth.example.com/token"
            assert config.registration_endpoint == "https://auth.example.com/register"
            assert config.supports_pkce() is True
            assert config.supports_public_clients() is True

    @pytest.mark.asyncio
    async def test_discover_oauth_config_normalizes_url_with_mcp_path(
        self, resource_metadata: dict, auth_server_metadata: dict
    ) -> None:
        """Test that discovery normalizes URLs with /mcp/ path."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            resource_response = MagicMock()
            resource_response.json.return_value = resource_metadata
            resource_response.raise_for_status = MagicMock()

            auth_response = MagicMock()
            auth_response.json.return_value = auth_server_metadata
            auth_response.raise_for_status = MagicMock()

            mock_client.get = AsyncMock(side_effect=[resource_response, auth_response])

            # URL with /mcp/ suffix should be stripped for discovery
            await discover_oauth_config("https://mcp.example.com/mcp/")

            # First call should be to the root .well-known endpoint
            calls = mock_client.get.call_args_list
            assert "/.well-known/oauth-protected-resource" in calls[0][0][0]
            assert "/mcp/" not in calls[0][0][0]

    @pytest.mark.asyncio
    async def test_discover_oauth_config_missing_resource(self) -> None:
        """Test discovery fails when resource metadata is missing 'resource' field."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            resource_response = MagicMock()
            resource_response.json.return_value = {
                "authorization_servers": ["https://auth.example.com"]
                # Missing "resource" field
            }
            resource_response.raise_for_status = MagicMock()

            mock_client.get = AsyncMock(return_value=resource_response)

            with pytest.raises(ValueError, match="missing 'resource' field"):
                await discover_oauth_config("https://mcp.example.com")

    @pytest.mark.asyncio
    async def test_discover_oauth_config_missing_auth_servers(self) -> None:
        """Test discovery fails when authorization_servers is missing."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            resource_response = MagicMock()
            resource_response.json.return_value = {
                "resource": "https://mcp.example.com"
                # Missing "authorization_servers" field
            }
            resource_response.raise_for_status = MagicMock()

            mock_client.get = AsyncMock(return_value=resource_response)

            with pytest.raises(ValueError, match="missing 'authorization_servers' field"):
                await discover_oauth_config("https://mcp.example.com")

    @pytest.mark.asyncio
    async def test_discover_oauth_config_http_error_on_resource(self) -> None:
        """Test discovery handles HTTP error when fetching resource metadata."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_client.get = AsyncMock(side_effect=httpx.HTTPError("Connection failed"))

            with pytest.raises(ValueError, match="Failed to fetch OAuth protected resource"):
                await discover_oauth_config("https://mcp.example.com")

    @pytest.mark.asyncio
    async def test_discover_oauth_config_fallback_to_openid(
        self, resource_metadata: dict, auth_server_metadata: dict
    ) -> None:
        """Test discovery falls back to OpenID Connect endpoint."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            resource_response = MagicMock()
            resource_response.json.return_value = resource_metadata
            resource_response.raise_for_status = MagicMock()

            # First auth server request fails, second (OpenID) succeeds
            auth_error_response = MagicMock()
            auth_error_response.raise_for_status.side_effect = httpx.HTTPError("Not found")

            auth_success_response = MagicMock()
            auth_success_response.json.return_value = auth_server_metadata
            auth_success_response.raise_for_status = MagicMock()

            mock_client.get = AsyncMock(
                side_effect=[resource_response, auth_error_response, auth_success_response]
            )

            config = await discover_oauth_config("https://mcp.example.com")

            # Should have tried 3 URLs
            assert mock_client.get.call_count == 3
            # Last call should be to OpenID endpoint
            last_call = mock_client.get.call_args_list[2]
            assert "openid-configuration" in last_call[0][0]

            assert config.authorization_endpoint == "https://auth.example.com/authorize"

    @pytest.mark.asyncio
    async def test_discover_oauth_config_missing_required_endpoints(
        self, resource_metadata: dict
    ) -> None:
        """Test discovery fails when required endpoints are missing."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            resource_response = MagicMock()
            resource_response.json.return_value = resource_metadata
            resource_response.raise_for_status = MagicMock()

            # Auth server metadata missing required endpoints
            auth_response = MagicMock()
            auth_response.json.return_value = {
                "scopes_supported": ["read"]
                # Missing authorization_endpoint and token_endpoint
            }
            auth_response.raise_for_status = MagicMock()

            mock_client.get = AsyncMock(side_effect=[resource_response, auth_response])

            with pytest.raises(ValueError, match="missing required endpoints"):
                await discover_oauth_config("https://mcp.example.com")


class TestOAuthFlowHandler:
    """Tests for OAuthFlowHandler."""

    @pytest.fixture
    def oauth_config(self) -> OAuthConfig:
        """Create an OAuthConfig for testing."""
        return OAuthConfig(
            resource_url="https://mcp.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            registration_endpoint="https://auth.example.com/register",
            scopes_supported=["read", "write"],
            token_endpoint_auth_methods_supported=["client_secret_post", "none"],
        )

    @pytest.fixture
    def flow_handler(self, oauth_config: OAuthConfig) -> OAuthFlowHandler:
        """Create an OAuthFlowHandler for testing."""
        return OAuthFlowHandler(oauth_config, redirect_port=8889, scopes="read write")

    def test_initialization(self, oauth_config: OAuthConfig) -> None:
        """Test OAuthFlowHandler initialization."""
        handler = OAuthFlowHandler(oauth_config, redirect_port=9999)

        assert handler.oauth_config == oauth_config
        assert handler.redirect_port == 9999
        assert handler.redirect_uri == "http://localhost:9999/callback"
        assert handler.client_id is None
        assert handler.client_secret is None

    def test_initialization_with_custom_scopes(self, oauth_config: OAuthConfig) -> None:
        """Test OAuthFlowHandler with custom scopes."""
        handler = OAuthFlowHandler(oauth_config, scopes="custom scope")
        assert handler.scopes == "custom scope"

    def test_initialization_uses_server_scopes_by_default(self, oauth_config: OAuthConfig) -> None:
        """Test OAuthFlowHandler uses server's default scopes."""
        handler = OAuthFlowHandler(oauth_config)
        assert handler.scopes == "read write"

    @pytest.mark.asyncio
    async def test_register_client_success(self, flow_handler: OAuthFlowHandler) -> None:
        """Test successful client registration."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",  # pragma: allowlist secret
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)

            client_id, client_secret = await flow_handler.register_client()

            assert client_id == "test_client_id"
            assert client_secret == "test_client_secret"  # pragma: allowlist secret
            assert flow_handler.client_id == "test_client_id"
            assert flow_handler.client_secret == "test_client_secret"  # pragma: allowlist secret

            # Verify registration request
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "https://auth.example.com/register"
            registration_data = call_args[1]["json"]
            assert "http://localhost:8889/callback" in registration_data["redirect_uris"]
            assert "authorization_code" in registration_data["grant_types"]

    @pytest.mark.asyncio
    async def test_register_client_public(self, flow_handler: OAuthFlowHandler) -> None:
        """Test client registration for public clients (no secret)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_id": "public_client_id",
            # No client_secret for public clients
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)

            client_id, client_secret = await flow_handler.register_client()

            assert client_id == "public_client_id"
            assert client_secret is None

    @pytest.mark.asyncio
    async def test_register_client_no_endpoint(self) -> None:
        """Test client registration fails without registration endpoint."""
        config = OAuthConfig(
            resource_url="https://mcp.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            # No registration_endpoint
        )
        handler = OAuthFlowHandler(config)

        with pytest.raises(ValueError, match="does not support dynamic client registration"):
            await handler.register_client()

    @pytest.mark.asyncio
    async def test_register_client_http_error(self, flow_handler: OAuthFlowHandler) -> None:
        """Test client registration handles HTTP errors."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.HTTPError("Connection refused"))

            with pytest.raises(ValueError, match="Failed to register OAuth client"):
                await flow_handler.register_client()

    @pytest.mark.asyncio
    async def test_exchange_code_success(self, flow_handler: OAuthFlowHandler) -> None:
        """Test successful authorization code exchange."""
        flow_handler.client_id = "test_client_id"
        flow_handler.client_secret = "test_client_secret"  # pragma: allowlist secret

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test_access_token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "test_refresh_token",
            "scope": "read write",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)

            token_set = await flow_handler._exchange_code("auth_code_123", "verifier_456")

            assert isinstance(token_set, TokenSet)
            assert token_set.access_token == "test_access_token"
            assert token_set.refresh_token == "test_refresh_token"
            assert token_set.token_type == "Bearer"
            assert token_set.expires_in == 3600

            # Verify token request
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "https://auth.example.com/token"
            token_data = call_args[1]["data"]
            assert token_data["grant_type"] == "authorization_code"
            assert token_data["code"] == "auth_code_123"
            assert token_data["code_verifier"] == "verifier_456"
            assert token_data["client_id"] == "test_client_id"
            assert token_data["client_secret"] == "test_client_secret"  # pragma: allowlist secret

    @pytest.mark.asyncio
    async def test_exchange_code_public_client(self, flow_handler: OAuthFlowHandler) -> None:
        """Test code exchange for public client (no secret)."""
        flow_handler.client_id = "public_client_id"
        flow_handler.client_secret = None  # Public client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test_access_token",
            "token_type": "Bearer",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)

            await flow_handler._exchange_code("auth_code", "verifier")

            # Verify no client_secret in request
            call_args = mock_client.post.call_args
            token_data = call_args[1]["data"]
            assert "client_secret" not in token_data

    @pytest.mark.asyncio
    async def test_exchange_code_http_error(self, flow_handler: OAuthFlowHandler) -> None:
        """Test code exchange handles HTTP errors."""
        flow_handler.client_id = "test_client_id"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.HTTPError("Token endpoint error"))

            with pytest.raises(ValueError, match="Failed to exchange code for token"):
                await flow_handler._exchange_code("auth_code", "verifier")


class TestTokenSet:
    """Tests for TokenSet dataclass."""

    def test_token_set_creation(self) -> None:
        """Test basic TokenSet creation."""
        token = TokenSet(
            access_token="access123",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="refresh456",
            scope="read write",
            issued_at=time.time(),
        )

        assert token.access_token == "access123"
        assert token.token_type == "Bearer"
        assert token.expires_in == 3600
        assert token.refresh_token == "refresh456"
        assert token.scope == "read write"

    def test_token_set_defaults(self) -> None:
        """Test TokenSet default values."""
        token = TokenSet(access_token="access123")

        assert token.token_type == "Bearer"
        assert token.expires_in is None
        assert token.refresh_token is None
        assert token.scope is None
        assert token.issued_at is None

    def test_is_expired_without_expiration_info(self) -> None:
        """Test is_expired returns False when no expiration info."""
        token = TokenSet(access_token="access123")
        assert token.is_expired() is False

    def test_is_expired_not_expired(self) -> None:
        """Test is_expired returns False for valid token."""
        token = TokenSet(
            access_token="access123",
            expires_in=3600,
            issued_at=time.time(),
        )
        assert token.is_expired() is False

    def test_is_expired_expired(self) -> None:
        """Test is_expired returns True for expired token."""
        token = TokenSet(
            access_token="access123",
            expires_in=3600,
            issued_at=time.time() - 4000,  # Issued 4000 seconds ago
        )
        assert token.is_expired() is True

    def test_is_expired_within_buffer(self) -> None:
        """Test is_expired considers buffer time."""
        # Token expires in 30 seconds, but buffer is 60
        token = TokenSet(
            access_token="access123",
            expires_in=30,
            issued_at=time.time(),
        )
        assert token.is_expired(buffer_seconds=60) is True
        assert token.is_expired(buffer_seconds=10) is False

    def test_from_oauth_response(self) -> None:
        """Test creating TokenSet from OAuth response."""
        response_data = {
            "access_token": "access123",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "refresh456",
            "scope": "read write",
        }

        token = TokenSet.from_oauth_response(response_data)

        assert token.access_token == "access123"
        assert token.token_type == "Bearer"
        assert token.expires_in == 3600
        assert token.refresh_token == "refresh456"
        assert token.scope == "read write"
        assert token.issued_at is not None
        assert time.time() - token.issued_at < 1  # Issued just now

    def test_to_dict_and_from_dict(self) -> None:
        """Test round-trip serialization."""
        original = TokenSet(
            access_token="access123",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="refresh456",
            scope="read write",
            issued_at=time.time(),
        )

        data = original.to_dict()
        restored = TokenSet.from_dict(data)

        assert restored.access_token == original.access_token
        assert restored.token_type == original.token_type
        assert restored.expires_in == original.expires_in
        assert restored.refresh_token == original.refresh_token
        assert restored.scope == original.scope
        assert restored.issued_at == original.issued_at


class TestTokenStorage:
    """Tests for TokenStorage file-based persistence."""

    @pytest.fixture
    def temp_storage_dir(self) -> Path:
        """Create a temporary directory for token storage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def token_storage(self, temp_storage_dir: Path) -> TokenStorage:
        """Create a TokenStorage with temporary directory."""
        return TokenStorage(storage_dir=temp_storage_dir)

    @pytest.fixture
    def sample_token(self) -> TokenSet:
        """Create a sample token for testing."""
        return TokenSet(
            access_token="test_access_token",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="test_refresh_token",
            scope="read write",
            issued_at=time.time(),
        )

    def test_storage_creates_directory(self, temp_storage_dir: Path) -> None:
        """Test storage creates directory if it doesn't exist."""
        storage_path = temp_storage_dir / "nested" / "tokens"
        TokenStorage(storage_dir=storage_path)  # Creates directory as side effect

        assert storage_path.exists()
        assert storage_path.is_dir()

    def test_save_and_load_token(self, token_storage: TokenStorage, sample_token: TokenSet) -> None:
        """Test saving and loading a token."""
        server_url = "https://mcp.example.com"

        token_storage.save_token(server_url, sample_token)
        loaded = token_storage.load_token(server_url)

        assert loaded is not None
        assert loaded.access_token == sample_token.access_token
        assert loaded.refresh_token == sample_token.refresh_token
        assert loaded.token_type == sample_token.token_type
        assert loaded.expires_in == sample_token.expires_in

    def test_load_nonexistent_token(self, token_storage: TokenStorage) -> None:
        """Test loading a token that doesn't exist."""
        loaded = token_storage.load_token("https://nonexistent.example.com")
        assert loaded is None

    def test_delete_token(self, token_storage: TokenStorage, sample_token: TokenSet) -> None:
        """Test deleting a token."""
        server_url = "https://mcp.example.com"

        token_storage.save_token(server_url, sample_token)
        assert token_storage.load_token(server_url) is not None

        token_storage.delete_token(server_url)
        assert token_storage.load_token(server_url) is None

    def test_delete_nonexistent_token(self, token_storage: TokenStorage) -> None:
        """Test deleting a token that doesn't exist (should not raise)."""
        # Should not raise an exception
        token_storage.delete_token("https://nonexistent.example.com")

    def test_different_servers_separate_tokens(self, token_storage: TokenStorage) -> None:
        """Test that different servers have separate token storage."""
        token1 = TokenSet(access_token="token1")
        token2 = TokenSet(access_token="token2")

        token_storage.save_token("https://server1.example.com", token1)
        token_storage.save_token("https://server2.example.com", token2)

        loaded1 = token_storage.load_token("https://server1.example.com")
        loaded2 = token_storage.load_token("https://server2.example.com")

        assert loaded1 is not None
        assert loaded2 is not None
        assert loaded1.access_token == "token1"
        assert loaded2.access_token == "token2"

    def test_token_file_uses_url_hash(
        self, token_storage: TokenStorage, sample_token: TokenSet, temp_storage_dir: Path
    ) -> None:
        """Test that token files are named by URL hash."""
        server_url = "https://mcp.example.com"
        token_storage.save_token(server_url, sample_token)

        # Should have created exactly one file
        files = list(temp_storage_dir.glob("*.json"))
        assert len(files) == 1

        # File should contain the token data
        with open(files[0]) as f:
            data = json.load(f)
            assert data["server_url"] == server_url
            assert data["token"]["access_token"] == sample_token.access_token

    def test_load_token_url_mismatch(
        self, token_storage: TokenStorage, sample_token: TokenSet, temp_storage_dir: Path
    ) -> None:
        """Test that loading fails if stored URL doesn't match."""
        server_url = "https://mcp.example.com"
        token_storage.save_token(server_url, sample_token)

        # Manually corrupt the stored URL
        files = list(temp_storage_dir.glob("*.json"))
        with open(files[0]) as f:
            data = json.load(f)
        data["server_url"] = "https://different.example.com"
        with open(files[0], "w") as f:
            json.dump(data, f)

        # Should return None due to URL mismatch
        loaded = token_storage.load_token(server_url)
        assert loaded is None

    def test_load_corrupted_token_file(
        self, token_storage: TokenStorage, temp_storage_dir: Path
    ) -> None:
        """Test handling of corrupted token files."""
        server_url = "https://mcp.example.com"

        # Create a corrupted token file
        token_file = token_storage._get_token_file(server_url)
        with open(token_file, "w") as f:
            f.write("not valid json")

        # Should return None and not raise
        loaded = token_storage.load_token(server_url)
        assert loaded is None
