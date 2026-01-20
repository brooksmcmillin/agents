"""Tests for OAuth 2.0 Device Authorization Grant (RFC 8628)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_framework.oauth.device_flow import (
    DEVICE_CODE_GRANT_TYPE,
    DeviceFlowDeniedError,
    DeviceFlowError,
    DeviceFlowExpiredError,
    DeviceFlowHandler,
)
from agent_framework.oauth.oauth_config import OAuthConfig
from agent_framework.oauth.oauth_tokens import TokenSet


@pytest.fixture
def oauth_config_with_device_flow() -> OAuthConfig:
    """Create an OAuthConfig that supports device flow."""
    return OAuthConfig(
        resource_url="https://mcp.example.com",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        registration_endpoint="https://auth.example.com/register",
        device_authorization_endpoint="https://auth.example.com/device/code",
        scopes_supported=["read", "write"],
        grant_types_supported=[
            "authorization_code",
            "refresh_token",
            "urn:ietf:params:oauth:grant-type:device_code",
        ],
        token_endpoint_auth_methods_supported=["client_secret_post", "none"],
    )


@pytest.fixture
def oauth_config_without_device_flow() -> OAuthConfig:
    """Create an OAuthConfig without device flow support."""
    return OAuthConfig(
        resource_url="https://mcp.example.com",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        scopes_supported=["read", "write"],
        grant_types_supported=["authorization_code", "refresh_token"],
    )


@pytest.fixture
def device_flow_handler(oauth_config_with_device_flow: OAuthConfig) -> DeviceFlowHandler:
    """Create a DeviceFlowHandler for testing."""
    return DeviceFlowHandler(oauth_config_with_device_flow, scopes="read write")


class TestOAuthConfigDeviceFlowSupport:
    """Tests for OAuthConfig.supports_device_flow()."""

    def test_supports_device_flow_with_endpoint(
        self, oauth_config_with_device_flow: OAuthConfig
    ) -> None:
        """Test that device flow is supported when endpoint is present."""
        assert oauth_config_with_device_flow.supports_device_flow() is True

    def test_supports_device_flow_without_endpoint(
        self, oauth_config_without_device_flow: OAuthConfig
    ) -> None:
        """Test that device flow is not supported without endpoint."""
        assert oauth_config_without_device_flow.supports_device_flow() is False

    def test_supports_device_flow_with_grant_type_only(self) -> None:
        """Test device flow support detection via grant_types."""
        config = OAuthConfig(
            resource_url="https://mcp.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            grant_types_supported=["urn:ietf:params:oauth:grant-type:device_code"],
        )
        assert config.supports_device_flow() is True

    def test_supports_device_flow_with_short_grant_type(self) -> None:
        """Test device flow support detection via short grant_type name."""
        config = OAuthConfig(
            resource_url="https://mcp.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            grant_types_supported=["device_code"],
        )
        assert config.supports_device_flow() is True


class TestDeviceFlowHandler:
    """Tests for DeviceFlowHandler."""

    def test_initialization(self, oauth_config_with_device_flow: OAuthConfig) -> None:
        """Test DeviceFlowHandler initialization."""
        handler = DeviceFlowHandler(oauth_config_with_device_flow)
        assert handler.oauth_config == oauth_config_with_device_flow
        assert handler.client_id is None
        assert handler.client_secret is None

    def test_initialization_with_custom_scopes(
        self, oauth_config_with_device_flow: OAuthConfig
    ) -> None:
        """Test DeviceFlowHandler initialization with custom scopes."""
        handler = DeviceFlowHandler(oauth_config_with_device_flow, scopes="custom scope")
        assert handler.scopes == "custom scope"

    def test_initialization_with_default_scopes(
        self, oauth_config_with_device_flow: OAuthConfig
    ) -> None:
        """Test DeviceFlowHandler uses server scopes by default."""
        handler = DeviceFlowHandler(oauth_config_with_device_flow)
        assert handler.scopes == "read write"

    @pytest.mark.asyncio
    async def test_register_client_success(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test successful client registration."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            client_id, client_secret = await device_flow_handler.register_client()

            assert client_id == "test_client_id"
            assert client_secret == "test_client_secret"
            assert device_flow_handler.client_id == "test_client_id"
            assert device_flow_handler.client_secret == "test_client_secret"

    @pytest.mark.asyncio
    async def test_register_client_public(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test client registration for public clients."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "client_id": "public_client_id",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            client_id, client_secret = await device_flow_handler.register_client()

            assert client_id == "public_client_id"
            assert client_secret is None

    @pytest.mark.asyncio
    async def test_register_client_no_endpoint(
        self, oauth_config_without_device_flow: OAuthConfig
    ) -> None:
        """Test client registration fails without registration endpoint."""
        handler = DeviceFlowHandler(oauth_config_without_device_flow)

        with pytest.raises(ValueError, match="does not support dynamic client registration"):
            await handler.register_client()

    @pytest.mark.asyncio
    async def test_request_device_code_success(
        self, device_flow_handler: DeviceFlowHandler
    ) -> None:
        """Test successful device code request."""
        # Pre-set client_id to skip registration
        device_flow_handler.client_id = "test_client_id"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "device_code": "test_device_code",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://auth.example.com/device",
            "verification_uri_complete": "https://auth.example.com/device?code=ABCD-EFGH",
            "expires_in": 1800,
            "interval": 5,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            response = await device_flow_handler.request_device_code()

            assert response["device_code"] == "test_device_code"
            assert response["user_code"] == "ABCD-EFGH"
            assert response["verification_uri"] == "https://auth.example.com/device"
            assert response["expires_in"] == 1800
            assert response["interval"] == 5

    @pytest.mark.asyncio
    async def test_request_device_code_no_endpoint(
        self, oauth_config_without_device_flow: OAuthConfig
    ) -> None:
        """Test device code request fails without device authorization endpoint."""
        handler = DeviceFlowHandler(oauth_config_without_device_flow)
        handler.client_id = "test_client_id"

        with pytest.raises(ValueError, match="does not support device authorization"):
            await handler.request_device_code()

    @pytest.mark.asyncio
    async def test_poll_for_token_success(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test successful token polling."""
        device_flow_handler.client_id = "test_client_id"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test_access_token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "test_refresh_token",
            "scope": "read write",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            token_set = await device_flow_handler.poll_for_token(
                device_code="test_device_code",
                interval=1,
                expires_in=1800,
            )

            assert isinstance(token_set, TokenSet)
            assert token_set.access_token == "test_access_token"
            assert token_set.refresh_token == "test_refresh_token"
            assert token_set.token_type == "Bearer"

    @pytest.mark.asyncio
    async def test_poll_for_token_authorization_pending(
        self, device_flow_handler: DeviceFlowHandler
    ) -> None:
        """Test polling with authorization pending."""
        device_flow_handler.client_id = "test_client_id"

        # First response: authorization_pending
        pending_response = MagicMock()
        pending_response.status_code = 400
        pending_response.json.return_value = {
            "error": "authorization_pending",
            "error_description": "User has not yet authorized",
        }

        # Second response: success
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "access_token": "test_access_token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        mock_post = AsyncMock(side_effect=[pending_response, success_response])

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                token_set = await device_flow_handler.poll_for_token(
                    device_code="test_device_code",
                    interval=1,
                    expires_in=1800,
                )

            assert token_set.access_token == "test_access_token"
            assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_poll_for_token_slow_down(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test polling handles slow_down response."""
        device_flow_handler.client_id = "test_client_id"

        # First response: slow_down
        slow_response = MagicMock()
        slow_response.status_code = 400
        slow_response.json.return_value = {
            "error": "slow_down",
            "error_description": "Polling too frequently",
        }

        # Second response: success
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "access_token": "test_access_token",
            "token_type": "Bearer",
        }

        mock_post = AsyncMock(side_effect=[slow_response, success_response])

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                token_set = await device_flow_handler.poll_for_token(
                    device_code="test_device_code",
                    interval=5,
                    expires_in=1800,
                )

            assert token_set.access_token == "test_access_token"

    @pytest.mark.asyncio
    async def test_poll_for_token_access_denied(
        self, device_flow_handler: DeviceFlowHandler
    ) -> None:
        """Test polling raises error on access_denied."""
        device_flow_handler.client_id = "test_client_id"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "access_denied",
            "error_description": "User denied authorization",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(DeviceFlowDeniedError) as exc_info:
                await device_flow_handler.poll_for_token(
                    device_code="test_device_code",
                    interval=1,
                    expires_in=1800,
                )

            assert exc_info.value.error == "access_denied"

    @pytest.mark.asyncio
    async def test_poll_for_token_expired(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test polling raises error on expired_token."""
        device_flow_handler.client_id = "test_client_id"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "expired_token",
            "error_description": "Device code has expired",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(DeviceFlowExpiredError) as exc_info:
                await device_flow_handler.poll_for_token(
                    device_code="test_device_code",
                    interval=1,
                    expires_in=1800,
                )

            assert exc_info.value.error == "expired_token"

    @pytest.mark.asyncio
    async def test_poll_for_token_client_expiry_check(
        self, device_flow_handler: DeviceFlowHandler
    ) -> None:
        """Test polling respects expiration time."""
        device_flow_handler.client_id = "test_client_id"

        # Response always pending
        pending_response = MagicMock()
        pending_response.status_code = 400
        pending_response.json.return_value = {
            "error": "authorization_pending",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=pending_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            # Use very short expiration to trigger client-side expiry
            # Patch in the device_flow module to avoid affecting httpx internals
            with patch("agent_framework.oauth.device_flow.time") as mock_time:
                # First call: start_time = 1000
                # Second call: elapsed check = 1000 (elapsed = 0, continue)
                # Third call: elapsed check = 2000 (elapsed = 1000 >= 10, expire)
                mock_time.time.side_effect = [1000, 1000, 2000]

                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(DeviceFlowExpiredError):
                        await device_flow_handler.poll_for_token(
                            device_code="test_device_code",
                            interval=1,
                            expires_in=10,  # 10 seconds
                        )

    @pytest.mark.asyncio
    async def test_refresh_token(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test token refresh."""
        device_flow_handler.client_id = "test_client_id"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "new_refresh_token",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            token_set = await device_flow_handler.refresh_token("old_refresh_token")

            assert token_set.access_token == "new_access_token"
            assert token_set.refresh_token == "new_refresh_token"


class TestDeviceFlowErrors:
    """Tests for device flow error classes."""

    def test_device_flow_error(self) -> None:
        """Test DeviceFlowError creation."""
        error = DeviceFlowError("invalid_request", "Missing required parameter")
        assert error.error == "invalid_request"
        assert error.error_description == "Missing required parameter"
        assert str(error) == "invalid_request: Missing required parameter"

    def test_device_flow_error_without_description(self) -> None:
        """Test DeviceFlowError without description."""
        error = DeviceFlowError("server_error")
        assert error.error == "server_error"
        assert error.error_description is None
        assert str(error) == "server_error"

    def test_device_flow_expired_error(self) -> None:
        """Test DeviceFlowExpiredError is a DeviceFlowError."""
        error = DeviceFlowExpiredError("expired_token", "Code expired")
        assert isinstance(error, DeviceFlowError)
        assert error.error == "expired_token"

    def test_device_flow_denied_error(self) -> None:
        """Test DeviceFlowDeniedError is a DeviceFlowError."""
        error = DeviceFlowDeniedError("access_denied", "User denied")
        assert isinstance(error, DeviceFlowError)
        assert error.error == "access_denied"


class TestDeviceCodeGrantType:
    """Tests for the device code grant type constant."""

    def test_grant_type_value(self) -> None:
        """Test the grant type URN value."""
        assert DEVICE_CODE_GRANT_TYPE == "urn:ietf:params:oauth:grant-type:device_code"
