"""Tests for OAuth 2.0 Device Authorization Grant (RFC 8628)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_framework.oauth.device_flow import (
    DEVICE_CODE_GRANT_TYPE,
    DeviceAuthorizationInfo,
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


class TestDeviceAuthorizationInfo:
    """Tests for DeviceAuthorizationInfo dataclass."""

    def test_expires_minutes(self) -> None:
        """Test expires_minutes property (line 40)."""
        info = DeviceAuthorizationInfo(
            user_code="ABCD-EFGH",
            verification_uri="https://auth.example.com/device",
            verification_uri_complete=None,
            expires_in=1800,
            device_code="secret_code",
        )
        assert info.expires_minutes == 30

    def test_expires_minutes_short(self) -> None:
        info = DeviceAuthorizationInfo(
            user_code="ABCD",
            verification_uri="https://auth.example.com/device",
            verification_uri_complete=None,
            expires_in=90,
            device_code="code",
        )
        assert info.expires_minutes == 1


class TestDeviceFlowRequestDeviceCodeErrors:
    """Tests for request_device_code error paths."""

    @pytest.mark.asyncio
    async def test_request_device_code_http_error_with_json(
        self, device_flow_handler: DeviceFlowHandler
    ) -> None:
        """Test request_device_code HTTPStatusError with JSON body (lines 212-219)."""
        device_flow_handler.client_id = "test_client_id"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_scope",
            "error_description": "Scope not supported",
        }
        mock_response.text = '{"error":"invalid_scope"}'
        mock_response.request = MagicMock()

        error = httpx.HTTPStatusError(
            "Bad Request", request=mock_response.request, response=mock_response
        )
        mock_response.raise_for_status.side_effect = error

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(DeviceFlowError) as exc_info:
                await device_flow_handler.request_device_code()

            assert exc_info.value.error == "invalid_scope"
            assert exc_info.value.error_description == "Scope not supported"

    @pytest.mark.asyncio
    async def test_request_device_code_http_error_non_json(
        self, device_flow_handler: DeviceFlowHandler
    ) -> None:
        """Test request_device_code HTTPStatusError without JSON body (line 218-219)."""
        device_flow_handler.client_id = "test_client_id"

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.text = "Internal Server Error"
        mock_response.request = MagicMock()

        error = httpx.HTTPStatusError(
            "Server Error", request=mock_response.request, response=mock_response
        )
        mock_response.raise_for_status.side_effect = error

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Failed to request device code"):
                await device_flow_handler.request_device_code()

    @pytest.mark.asyncio
    async def test_request_device_code_auto_registers(
        self, device_flow_handler: DeviceFlowHandler
    ) -> None:
        """Test request_device_code auto-registers if no client_id (line 193)."""
        assert device_flow_handler.client_id is None

        # Mock register_client
        device_flow_handler.register_client = AsyncMock()
        device_flow_handler.register_client.side_effect = lambda: setattr(
            device_flow_handler, "client_id", "auto_registered"
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "device_code": "dc",
            "user_code": "UC",
            "verification_uri": "https://example.com/device",
            "expires_in": 600,
            "interval": 5,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            await device_flow_handler.request_device_code()
            device_flow_handler.register_client.assert_called_once()


class TestDeviceFlowPollingNetworkErrors:
    """Tests for network error handling during token polling."""

    @pytest.mark.asyncio
    async def test_poll_handles_connect_error(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test polling handles ConnectError and retries (lines 325-329)."""
        device_flow_handler.client_id = "test_client_id"

        connect_error = httpx.ConnectError("Connection refused")
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "access_token": "token_after_retry",
            "token_type": "Bearer",
        }

        mock_post = AsyncMock(side_effect=[connect_error, success_response])

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                token = await device_flow_handler.poll_for_token(
                    device_code="dc", interval=1, expires_in=1800
                )

            assert token.access_token == "token_after_retry"
            assert mock_post.call_count == 2

    @pytest.mark.asyncio
    async def test_poll_handles_timeout_error(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test polling handles TimeoutException and retries (lines 330-331)."""
        device_flow_handler.client_id = "test_client_id"

        timeout_error = httpx.ReadTimeout("Read timed out")
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "access_token": "token_after_timeout",
            "token_type": "Bearer",
        }

        mock_post = AsyncMock(side_effect=[timeout_error, success_response])

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                token = await device_flow_handler.poll_for_token(
                    device_code="dc", interval=1, expires_in=1800
                )

            assert token.access_token == "token_after_timeout"

    @pytest.mark.asyncio
    async def test_poll_handles_generic_http_error(
        self, device_flow_handler: DeviceFlowHandler
    ) -> None:
        """Test polling handles generic HTTPError and retries (lines 332-333)."""
        device_flow_handler.client_id = "test_client_id"

        generic_error = httpx.HTTPError("Something went wrong")
        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "access_token": "recovered",
            "token_type": "Bearer",
        }

        mock_post = AsyncMock(side_effect=[generic_error, success_response])

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                token = await device_flow_handler.poll_for_token(
                    device_code="dc", interval=1, expires_in=1800
                )

            assert token.access_token == "recovered"

    @pytest.mark.asyncio
    async def test_poll_unknown_oauth_error(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test polling raises DeviceFlowError for unknown error codes (line 320)."""
        device_flow_handler.client_id = "test_client_id"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "server_error",
            "error_description": "Internal failure",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(DeviceFlowError) as exc_info:
                await device_flow_handler.poll_for_token(
                    device_code="dc", interval=1, expires_in=1800
                )

            assert exc_info.value.error == "server_error"

    @pytest.mark.asyncio
    async def test_poll_no_client_id_raises(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test poll_for_token raises ValueError without client_id."""
        assert device_flow_handler.client_id is None

        with pytest.raises(ValueError, match="Client not registered"):
            await device_flow_handler.poll_for_token(device_code="dc")


class TestDeviceFlowAuthorize:
    """Tests for the full authorize() flow."""

    @pytest.mark.asyncio
    async def test_authorize_full_flow(self, device_flow_handler: DeviceFlowHandler) -> None:
        """Test complete authorize() flow end-to-end."""
        # Mock register_client
        device_flow_handler.register_client = AsyncMock()
        device_flow_handler.register_client.side_effect = lambda: setattr(
            device_flow_handler, "client_id", "registered_id"
        )

        # Mock request_device_code
        device_flow_handler.request_device_code = AsyncMock(
            return_value={
                "device_code": "dc123",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://auth.example.com/device",
                "verification_uri_complete": "https://auth.example.com/device?code=ABCD-EFGH",
                "expires_in": 600,
                "interval": 5,
            }
        )

        # Mock poll_for_token
        expected_token = TokenSet(
            access_token="final_token", token_type="Bearer", refresh_token="refresh"
        )
        device_flow_handler.poll_for_token = AsyncMock(return_value=expected_token)

        token = await device_flow_handler.authorize()

        assert token.access_token == "final_token"
        device_flow_handler.register_client.assert_called_once()
        device_flow_handler.request_device_code.assert_called_once()
        device_flow_handler.poll_for_token.assert_called_once_with(
            device_code="dc123", interval=5, expires_in=600
        )

    @pytest.mark.asyncio
    async def test_authorize_with_callback(
        self, oauth_config_with_device_flow: OAuthConfig
    ) -> None:
        """Test authorize() invokes the authorization callback."""
        callback = AsyncMock()
        handler = DeviceFlowHandler(
            oauth_config_with_device_flow,
            scopes="read",
            authorization_callback=callback,
        )
        handler.client_id = "pre_registered"

        handler.request_device_code = AsyncMock(
            return_value={
                "device_code": "dc",
                "user_code": "CODE",
                "verification_uri": "https://example.com/device",
                "expires_in": 300,
                "interval": 5,
            }
        )
        handler.poll_for_token = AsyncMock(
            return_value=TokenSet(access_token="tok", token_type="Bearer")
        )

        await handler.authorize()

        callback.assert_called_once()
        call_arg = callback.call_args[0][0]
        assert isinstance(call_arg, DeviceAuthorizationInfo)
        assert call_arg.user_code == "CODE"

    @pytest.mark.asyncio
    async def test_authorize_callback_failure_doesnt_block(
        self, oauth_config_with_device_flow: OAuthConfig
    ) -> None:
        """Test authorize() continues even if callback raises."""
        callback = AsyncMock(side_effect=RuntimeError("callback broke"))
        handler = DeviceFlowHandler(
            oauth_config_with_device_flow,
            authorization_callback=callback,
        )
        handler.client_id = "pre_registered"

        handler.request_device_code = AsyncMock(
            return_value={
                "device_code": "dc",
                "user_code": "CODE",
                "verification_uri": "https://example.com/device",
                "expires_in": 300,
                "interval": 5,
            }
        )
        handler.poll_for_token = AsyncMock(
            return_value=TokenSet(access_token="tok", token_type="Bearer")
        )

        # Should not raise despite callback failure
        token = await handler.authorize()
        assert token.access_token == "tok"

    @pytest.mark.asyncio
    async def test_authorize_skips_registration_if_already_registered(
        self, device_flow_handler: DeviceFlowHandler
    ) -> None:
        """Test authorize() skips registration if client_id is already set."""
        device_flow_handler.client_id = "already_registered"
        device_flow_handler.register_client = AsyncMock()

        device_flow_handler.request_device_code = AsyncMock(
            return_value={
                "device_code": "dc",
                "user_code": "CODE",
                "verification_uri": "https://example.com/device",
                "expires_in": 300,
                "interval": 5,
            }
        )
        device_flow_handler.poll_for_token = AsyncMock(
            return_value=TokenSet(access_token="tok", token_type="Bearer")
        )

        await device_flow_handler.authorize()
        device_flow_handler.register_client.assert_not_called()


class TestDisplayAuthorizationInstructions:
    """Tests for _display_authorization_instructions()."""

    def test_display_with_complete_uri(
        self, device_flow_handler: DeviceFlowHandler, capsys
    ) -> None:
        """Test display with verification_uri_complete."""
        device_flow_handler._display_authorization_instructions(
            user_code="ABCD-EFGH",
            verification_uri="https://auth.example.com/device",
            verification_uri_complete="https://auth.example.com/device?code=ABCD-EFGH",
            expires_in=1800,
        )

        output = capsys.readouterr().out
        assert "ABCD-EFGH" in output
        assert "https://auth.example.com/device?code=ABCD-EFGH" in output
        assert "30 minutes" in output

    def test_display_without_complete_uri(
        self, device_flow_handler: DeviceFlowHandler, capsys
    ) -> None:
        """Test display without verification_uri_complete."""
        device_flow_handler._display_authorization_instructions(
            user_code="WXYZ-1234",
            verification_uri="https://auth.example.com/device",
            verification_uri_complete=None,
            expires_in=600,
        )

        output = capsys.readouterr().out
        assert "WXYZ-1234" in output
        assert "https://auth.example.com/device" in output
        assert "10 minutes" in output


class TestDeviceCodeGrantType:
    """Tests for the device code grant type constant."""

    def test_grant_type_value(self) -> None:
        """Test the grant type URN value."""
        assert DEVICE_CODE_GRANT_TYPE == "urn:ietf:params:oauth:grant-type:device_code"
