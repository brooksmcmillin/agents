"""Additional PKCE flow tests to improve Auth/Security coverage.

This module covers the remaining gaps in OAuth PKCE flow testing:
- TokenStorage encryption error paths
- TokenStorage save/load/delete failure paths
- OAuthHandlerBase refresh_token with no client_id
- OAuthHandlerBase refresh_token with client_secret
- OAuthConfig.supports_device_flow edge cases
- discover_oauth_config URL normalization branches
- discover_oauth_config OpenID fallback failure
- OAuthFlowHandler._run_callback_server (callback server lifecycle)
"""

import asyncio
import hashlib
import json
import os
import shutil
import socket
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

from agent_framework.oauth.oauth_config import OAuthConfig, discover_oauth_config
from agent_framework.oauth.oauth_flow import OAuthFlowHandler
from agent_framework.oauth.oauth_tokens import TokenSet, TokenStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_oauth_config(
    *,
    device_authorization_endpoint: str | None = None,
    grant_types_supported: list[str] | None = None,
) -> OAuthConfig:
    """Create an OAuthConfig for testing with optional device-flow fields."""
    return OAuthConfig(
        resource_url="https://example.com",
        authorization_endpoint="https://example.com/authorize",
        token_endpoint="https://example.com/token",
        registration_endpoint="https://example.com/register",
        device_authorization_endpoint=device_authorization_endpoint,
        grant_types_supported=grant_types_supported,
        code_challenge_methods_supported=["S256"],
        token_endpoint_auth_methods_supported=["none", "client_secret_post"],
    )


def get_free_port() -> int:
    """Find a free TCP port by temporarily binding to port 0."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---------------------------------------------------------------------------
# OAuthConfig.supports_device_flow edge cases
# ---------------------------------------------------------------------------


class TestOAuthConfigSupportsDeviceFlow:
    """Tests for OAuthConfig.supports_device_flow() covering all branches."""

    def test_returns_true_when_endpoint_set(self) -> None:
        """Device flow is supported if device_authorization_endpoint is provided."""
        config = make_oauth_config(device_authorization_endpoint="https://example.com/device/code")
        assert config.supports_device_flow() is True

    def test_returns_true_when_urn_grant_type_present(self) -> None:
        """Device flow is supported when the URN grant type is listed."""
        config = make_oauth_config(
            grant_types_supported=["urn:ietf:params:oauth:grant-type:device_code"]
        )
        assert config.supports_device_flow() is True

    def test_returns_true_when_short_grant_type_present(self) -> None:
        """Device flow is supported when the short 'device_code' grant type is listed."""
        config = make_oauth_config(grant_types_supported=["device_code"])
        assert config.supports_device_flow() is True

    def test_returns_false_when_no_endpoint_and_no_grant_types(self) -> None:
        """Device flow is NOT supported when neither endpoint nor grant types set."""
        config = make_oauth_config()
        assert config.supports_device_flow() is False

    def test_returns_false_when_grant_types_exclude_device(self) -> None:
        """Device flow is NOT supported if grant_types_supported has no device types."""
        config = make_oauth_config(grant_types_supported=["authorization_code", "refresh_token"])
        assert config.supports_device_flow() is False

    def test_returns_false_when_no_endpoint_and_grant_types_none(self) -> None:
        """Device flow is NOT supported when grant_types_supported is None."""
        config = OAuthConfig(
            resource_url="https://example.com",
            authorization_endpoint="https://example.com/authorize",
            token_endpoint="https://example.com/token",
            # device_authorization_endpoint defaults to None
            # grant_types_supported defaults to None
        )
        assert config.supports_device_flow() is False


# ---------------------------------------------------------------------------
# discover_oauth_config URL normalization
# ---------------------------------------------------------------------------


class TestDiscoverOAuthConfigNormalization:
    """Tests for URL normalization in discover_oauth_config."""

    @pytest.fixture
    def resource_metadata(self) -> dict:
        return {
            "resource": "https://example.com",
            "authorization_servers": ["https://auth.example.com"],
        }

    @pytest.fixture
    def auth_metadata(self) -> dict:
        return {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "code_challenge_methods_supported": ["S256"],
        }

    def _make_mock_client(self, resource_metadata: dict, auth_metadata: dict) -> AsyncMock:
        """Build a mock httpx async client."""
        resource_response = MagicMock()
        resource_response.json.return_value = resource_metadata
        resource_response.raise_for_status = MagicMock()

        auth_response = MagicMock()
        auth_response.json.return_value = auth_metadata
        auth_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resource_response, auth_response])
        return mock_client

    @pytest.mark.asyncio
    async def test_normalizes_url_without_mcp_suffix(
        self, resource_metadata: dict, auth_metadata: dict
    ) -> None:
        """URLs without /mcp or /mcp/ suffix are stripped of trailing slash only."""
        with patch("httpx.AsyncClient") as mock_class:
            mock_client = self._make_mock_client(resource_metadata, auth_metadata)
            mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_class.return_value.__aexit__ = AsyncMock(return_value=None)

            config = await discover_oauth_config("https://example.com/")

            # Verify the discovery request used the normalized (stripped) URL
            first_call_url = mock_client.get.call_args_list[0][0][0]
            assert first_call_url == "https://example.com/.well-known/oauth-protected-resource"
            assert config.resource_url == "https://example.com"
            assert config.authorization_endpoint == "https://auth.example.com/authorize"

    @pytest.mark.asyncio
    async def test_normalizes_url_ending_with_mcp_no_trailing_slash(
        self, resource_metadata: dict, auth_metadata: dict
    ) -> None:
        """URLs ending with '/mcp' (no trailing slash) strip that suffix."""
        with patch("httpx.AsyncClient") as mock_class:
            mock_client = self._make_mock_client(resource_metadata, auth_metadata)
            mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_class.return_value.__aexit__ = AsyncMock(return_value=None)

            config = await discover_oauth_config("https://example.com/mcp")

            # Verify the /mcp suffix was stripped before building discovery URL
            first_call_url = mock_client.get.call_args_list[0][0][0]
            assert first_call_url == "https://example.com/.well-known/oauth-protected-resource"
            assert config.resource_url == "https://example.com"

    @pytest.mark.asyncio
    async def test_normalizes_url_ending_with_mcp_and_trailing_slash(
        self, resource_metadata: dict, auth_metadata: dict
    ) -> None:
        """URLs ending with '/mcp/' (trailing slash) strip that suffix."""
        with patch("httpx.AsyncClient") as mock_class:
            mock_client = self._make_mock_client(resource_metadata, auth_metadata)
            mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_class.return_value.__aexit__ = AsyncMock(return_value=None)

            config = await discover_oauth_config("https://example.com/mcp/")

            # Verify the /mcp/ suffix was stripped before building discovery URL
            first_call_url = mock_client.get.call_args_list[0][0][0]
            assert first_call_url == "https://example.com/.well-known/oauth-protected-resource"
            assert config.resource_url == "https://example.com"

    @pytest.mark.asyncio
    async def test_openid_fallback_failure_raises(self) -> None:
        """If both oauth-authorization-server and openid-configuration fail, raise ValueError."""
        resource_response = MagicMock()
        resource_response.json.return_value = {
            "resource": "https://example.com",
            "authorization_servers": ["https://auth.example.com"],
        }
        resource_response.raise_for_status = MagicMock()

        # Both auth server metadata requests fail
        http_error = httpx.HTTPError("Connection refused")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resource_response, http_error, http_error])

        with patch("httpx.AsyncClient") as mock_class:
            mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_class.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Failed to fetch OAuth authorization server"):
                await discover_oauth_config("https://example.com/")


# ---------------------------------------------------------------------------
# OAuthHandlerBase.refresh_token edge cases
# ---------------------------------------------------------------------------


class TestOAuthHandlerBaseRefreshToken:
    """Tests for OAuthHandlerBase.refresh_token edge cases."""

    @pytest.fixture
    def flow_handler(self) -> OAuthFlowHandler:
        config = make_oauth_config()
        handler = OAuthFlowHandler(oauth_config=config)
        return handler

    @pytest.mark.asyncio
    async def test_refresh_raises_when_no_client_id(self, flow_handler: OAuthFlowHandler) -> None:
        """refresh_token raises ValueError when no client_id is available."""
        # client_id is None by default
        assert flow_handler.client_id is None

        with pytest.raises(ValueError, match="Client not registered and no client_id provided"):
            await flow_handler.refresh_token("some_refresh_token")

    @pytest.mark.asyncio
    async def test_refresh_uses_provided_client_id(self, flow_handler: OAuthFlowHandler) -> None:
        """refresh_token accepts explicit client_id parameter."""
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "refreshed_token",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            result = await flow_handler.refresh_token(
                "refresh_token_value",
                client_id="explicit_client_id",
            )

            assert result.access_token == "refreshed_token"
            assert result.client_id == "explicit_client_id"

    @pytest.mark.asyncio
    async def test_refresh_includes_client_secret_in_request(
        self, flow_handler: OAuthFlowHandler
    ) -> None:
        """refresh_token includes client_secret in POST data when provided."""
        flow_handler.client_id = "test_client"

        call_args_captured: list = []

        async def capture_post(*args, **kwargs):
            call_args_captured.append(kwargs)
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "new_token",
                "token_type": "Bearer",
            }
            mock_response.raise_for_status = MagicMock()
            return mock_response

        with patch("httpx.AsyncClient.post", side_effect=capture_post):
            result = await flow_handler.refresh_token(
                "refresh_token_value",
                client_secret="super_secret",  # pragma: allowlist secret
            )

        assert result.access_token == "new_token"
        # client_secret should have been sent in the POST data
        assert call_args_captured
        post_data = call_args_captured[0].get("data", {})
        assert post_data.get("client_secret") == "super_secret"  # pragma: allowlist secret

    @pytest.mark.asyncio
    async def test_refresh_without_client_secret_excludes_it(
        self, flow_handler: OAuthFlowHandler
    ) -> None:
        """refresh_token does NOT include client_secret when not provided."""
        flow_handler.client_id = "test_client"

        call_args_captured: list = []

        async def capture_post(*args, **kwargs):
            call_args_captured.append(kwargs)
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": "new_token",
                "token_type": "Bearer",
            }
            mock_response.raise_for_status = MagicMock()
            return mock_response

        with patch("httpx.AsyncClient.post", side_effect=capture_post):
            await flow_handler.refresh_token("refresh_token_value")

        post_data = call_args_captured[0].get("data", {})
        assert "client_secret" not in post_data

    @pytest.mark.asyncio
    async def test_refresh_http_error_without_oauth_body(
        self, flow_handler: OAuthFlowHandler
    ) -> None:
        """refresh_token raises ValueError when HTTPStatusError has non-JSON body."""
        flow_handler.client_id = "test_client"

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.side_effect = Exception("Not JSON")

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = httpx.HTTPStatusError(
                "500 Internal Server Error",
                request=MagicMock(),
                response=mock_response,
            )

            with pytest.raises(ValueError, match="Failed to refresh token"):
                await flow_handler.refresh_token("refresh_token_value")

    @pytest.mark.asyncio
    async def test_refresh_http_error_with_oauth_error_body(
        self, flow_handler: OAuthFlowHandler
    ) -> None:
        """refresh_token raises ValueError with parsed OAuth error detail."""
        flow_handler.client_id = "test_client"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Refresh token expired",
        }

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.side_effect = httpx.HTTPStatusError(
                "400 Bad Request",
                request=MagicMock(),
                response=mock_response,
            )

            with pytest.raises(ValueError, match="invalid_grant"):
                await flow_handler.refresh_token("expired_refresh_token")


# ---------------------------------------------------------------------------
# TokenStorage encryption and error paths
# ---------------------------------------------------------------------------


class TestTokenStorageEncryptionPaths:
    """Tests for TokenStorage encryption initialization and error handling."""

    def test_require_encryption_raises_when_key_generation_fails(self, tmp_path: Path) -> None:
        """require_encryption=True raises RuntimeError if encryption init fails."""
        with patch(
            "agent_framework.oauth.oauth_tokens.Fernet.generate_key",
            side_effect=OSError("Cannot generate key"),
        ):
            with pytest.raises(RuntimeError, match="Encryption required"):
                TokenStorage(storage_dir=tmp_path, require_encryption=True)

    def test_require_encryption_raises_when_cipher_init_fails(self, tmp_path: Path) -> None:
        """require_encryption=True raises RuntimeError if Fernet() constructor fails."""
        # Write a valid-format key file first so _load_or_generate_key succeeds
        key_file = tmp_path / ".encryption.key"
        key_file.write_text(Fernet.generate_key().decode())
        key_file.chmod(0o600)

        with patch(
            "agent_framework.oauth.oauth_tokens.Fernet",
            side_effect=ValueError("Bad key format"),
        ):
            with pytest.raises(RuntimeError, match="Encryption required"):
                TokenStorage(storage_dir=tmp_path, require_encryption=True)

    def test_encryption_key_file_exists_race_uses_existing(self, tmp_path: Path) -> None:
        """If key file appears between exists() check and O_EXCL open, read it."""
        real_key = Fernet.generate_key().decode()

        original_open = os.open

        call_count = 0

        def patched_open(path, flags, mode=0o600):
            nonlocal call_count
            # On the first O_CREAT|O_EXCL call, simulate a race by writing
            # the key file first then raising FileExistsError
            if flags & os.O_EXCL:
                call_count += 1
                if call_count == 1:
                    Path(path).write_text(real_key)
                    raise FileExistsError("Already exists")
            return original_open(path, flags, mode)

        with patch("os.open", side_effect=patched_open):
            storage = TokenStorage(storage_dir=tmp_path)

        # Encryption should still be initialized using the existing key
        assert storage.cipher is not None

    def test_save_token_failure_propagates(self, tmp_path: Path) -> None:
        """save_token raises when writing the token file fails."""
        storage = TokenStorage(storage_dir=tmp_path)
        token = TokenSet(
            access_token="token123",
            token_type="Bearer",
        )

        with patch("os.open", side_effect=PermissionError("Access denied")):
            with pytest.raises(PermissionError):
                storage.save_token("https://example.com", token)

    def test_save_token_failure_with_fdopen_error(self, tmp_path: Path) -> None:
        """save_token raises when os.fdopen fails after os.open succeeds."""
        storage = TokenStorage(storage_dir=tmp_path)
        token = TokenSet(access_token="token123", token_type="Bearer")

        original_open = os.open

        def patched_open(path, flags, mode=0o600):
            fd = original_open(path, flags, mode)
            return fd

        with patch("os.open", side_effect=patched_open):
            with patch("os.fdopen", side_effect=OSError("fdopen failed")):
                with pytest.raises(OSError):
                    storage.save_token("https://example.com", token)

    def test_load_token_decryption_failure_returns_none(self, tmp_path: Path) -> None:
        """load_token returns None when decryption fails (e.g., key changed)."""
        # Create storage with one key
        storage1 = TokenStorage(storage_dir=tmp_path)
        token = TokenSet(access_token="secret_token", token_type="Bearer")
        storage1.save_token("https://example.com", token)

        # Create new storage with a DIFFERENT key
        new_key_storage = tmp_path / "different_dir"
        new_key_storage.mkdir()
        storage2 = TokenStorage(storage_dir=new_key_storage)

        # Copy the encrypted token file to the new storage directory
        token_files = list(tmp_path.glob("*.json"))
        assert len(token_files) == 1
        shutil.copy(token_files[0], new_key_storage / token_files[0].name)

        # Loading should fail (wrong key) and return None gracefully
        result = storage2.load_token("https://example.com")
        assert result is None

    def test_load_token_url_mismatch_returns_none(self, tmp_path: Path) -> None:
        """load_token returns None when stored server_url doesn't match lookup key."""
        storage = TokenStorage(storage_dir=tmp_path)

        # Create a valid token file for one URL
        token = TokenSet(access_token="token", token_type="Bearer")
        storage.save_token("https://example.com", token)

        # Loading with a DIFFERENT URL should return None (mismatch)
        result = storage.load_token("https://other.example.com")
        assert result is None

    def test_delete_token_failure_propagates(self, tmp_path: Path) -> None:
        """delete_token raises when unlink fails."""
        storage = TokenStorage(storage_dir=tmp_path)
        token = TokenSet(access_token="token", token_type="Bearer")
        storage.save_token("https://example.com", token)

        with patch("pathlib.Path.unlink", side_effect=PermissionError("Cannot delete")):
            with pytest.raises(PermissionError):
                storage.delete_token("https://example.com")

    def test_delete_nonexistent_token_is_noop(self, tmp_path: Path) -> None:
        """delete_token does nothing when the token file doesn't exist."""
        storage = TokenStorage(storage_dir=tmp_path)
        # Should not raise even if token does not exist
        storage.delete_token("https://nonexistent.example.com")

    def test_load_token_json_decode_error_returns_none(self, tmp_path: Path) -> None:
        """load_token returns None when token file contains invalid JSON."""
        storage = TokenStorage(storage_dir=tmp_path)

        url = "https://example.com"
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        token_file = tmp_path / f"{url_hash}.json"

        # Disable cipher so we can write raw bytes that look like plaintext but are invalid JSON
        storage.cipher = None
        token_file.write_bytes(b"not valid json content {{{")

        result = storage.load_token(url)
        assert result is None

    def test_token_storage_without_encryption_saves_plaintext(self, tmp_path: Path) -> None:
        """When encryption key cannot be generated, tokens are stored as plaintext."""
        with patch(
            "agent_framework.oauth.oauth_tokens.Fernet.generate_key",
            side_effect=OSError("Cannot generate key"),
        ):
            storage = TokenStorage(storage_dir=tmp_path, require_encryption=False)

        assert storage.cipher is None

        token = TokenSet(access_token="plain_token", token_type="Bearer")
        storage.save_token("https://example.com", token)

        # Verify the file exists and is readable JSON (not encrypted)
        token_files = list(tmp_path.glob("*.json"))
        assert len(token_files) == 1
        content = token_files[0].read_text()
        data = json.loads(content)
        assert data["token"]["access_token"] == "plain_token"

        # Loading should also work
        loaded = storage.load_token("https://example.com")
        assert loaded is not None
        assert loaded.access_token == "plain_token"


# ---------------------------------------------------------------------------
# OAuthFlowHandler._run_callback_server
# ---------------------------------------------------------------------------


class TestOAuthFlowHandlerCallbackServer:
    """Tests for OAuthFlowHandler._run_callback_server using ephemeral ports."""

    @pytest.fixture
    def flow_handler(self) -> OAuthFlowHandler:
        config = make_oauth_config()
        port = get_free_port()
        handler = OAuthFlowHandler(oauth_config=config, redirect_port=port)
        handler.client_id = "test_client"
        return handler

    @pytest.mark.asyncio
    async def test_run_callback_server_returns_code(self, flow_handler: OAuthFlowHandler) -> None:
        """_run_callback_server returns the auth code after callback is hit."""
        expected_state = "test_state_12345"

        async def simulate_callback(port: int, state: str) -> None:
            """Wait briefly then hit the callback endpoint."""
            await asyncio.sleep(0.1)
            async with httpx.AsyncClient() as client:
                await client.get(
                    f"http://localhost:{port}/callback",
                    params={"code": "auth_code_from_provider", "state": state},
                )

        # Run the callback server and the simulated browser in parallel
        server_task = asyncio.create_task(
            flow_handler._run_callback_server(expected_state=expected_state)
        )
        await simulate_callback(flow_handler.redirect_port, expected_state)
        code, error = await server_task

        assert code == "auth_code_from_provider"
        assert error is None

    @pytest.mark.asyncio
    async def test_run_callback_server_returns_error_on_denial(
        self, flow_handler: OAuthFlowHandler
    ) -> None:
        """_run_callback_server returns (None, error) when user denies access."""
        expected_state = "test_state_67890"

        async def simulate_denial(port: int, state: str) -> None:
            await asyncio.sleep(0.1)
            async with httpx.AsyncClient() as client:
                await client.get(
                    f"http://localhost:{port}/callback",
                    params={
                        "error": "access_denied",
                        "error_description": "User denied access",
                        "state": state,
                    },
                )

        server_task = asyncio.create_task(
            flow_handler._run_callback_server(expected_state=expected_state)
        )
        await simulate_denial(flow_handler.redirect_port, expected_state)
        code, error = await server_task

        assert code is None
        assert error == "access_denied"

    @pytest.mark.asyncio
    async def test_run_callback_server_returns_error_on_state_mismatch(
        self, flow_handler: OAuthFlowHandler
    ) -> None:
        """_run_callback_server sets error immediately on CSRF state mismatch.

        Once auth_result["error"] is set, the polling loop exits and runner.cleanup()
        is called. Only one request is needed — the server stops after the mismatch.
        """
        expected_state = "correct_state"

        async def simulate_wrong_state(port: int) -> None:
            await asyncio.sleep(0.1)
            async with httpx.AsyncClient() as client:
                # Send with wrong state — this sets auth_result["error"] and unblocks the server
                await client.get(
                    f"http://localhost:{port}/callback",
                    params={"code": "code", "state": "wrong_state"},
                )

        server_task = asyncio.create_task(
            flow_handler._run_callback_server(expected_state=expected_state)
        )
        await simulate_wrong_state(flow_handler.redirect_port)
        code, error = await server_task

        # Should have detected CSRF and returned error immediately
        assert error == "state_mismatch"
        assert code is None


# ---------------------------------------------------------------------------
# OAuthFlowHandler.authorize integration path
# ---------------------------------------------------------------------------


class TestOAuthFlowHandlerAuthorize:
    """Tests for OAuthFlowHandler.authorize end-to-end flow."""

    @pytest.mark.asyncio
    async def test_authorize_exchanges_code_for_token(self) -> None:
        """authorize() calls _run_callback_server and _exchange_code."""
        config = make_oauth_config()
        port = get_free_port()
        handler = OAuthFlowHandler(oauth_config=config, redirect_port=port)
        handler.client_id = "existing_client"  # Skip registration

        mock_token = TokenSet(
            access_token="access_from_exchange",
            token_type="Bearer",
            expires_in=3600,
        )

        with patch.object(
            handler,
            "_run_callback_server",
            return_value=("auth_code_123", None),
        ):
            with patch.object(
                handler,
                "_exchange_code",
                return_value=mock_token,
            ) as mock_exchange:
                with patch("webbrowser.open"):
                    result = await handler.authorize()

        assert result.access_token == "access_from_exchange"
        mock_exchange.assert_called_once()
        call_args = mock_exchange.call_args
        # _exchange_code is called as: await self._exchange_code(auth_code, code_verifier)
        # with positional args
        assert call_args[0][0] == "auth_code_123"

    @pytest.mark.asyncio
    async def test_authorize_raises_when_callback_error(self) -> None:
        """authorize() raises ValueError when callback returns an error."""
        config = make_oauth_config()
        port = get_free_port()
        handler = OAuthFlowHandler(oauth_config=config, redirect_port=port)
        handler.client_id = "existing_client"

        with patch.object(
            handler,
            "_run_callback_server",
            return_value=(None, "access_denied"),
        ):
            with patch("webbrowser.open"):
                with pytest.raises(ValueError, match="Authorization failed"):
                    await handler.authorize()

    @pytest.mark.asyncio
    async def test_authorize_raises_when_no_code_and_no_error(self) -> None:
        """authorize() raises ValueError when no code and no error received."""
        config = make_oauth_config()
        port = get_free_port()
        handler = OAuthFlowHandler(oauth_config=config, redirect_port=port)
        handler.client_id = "existing_client"

        with patch.object(
            handler,
            "_run_callback_server",
            return_value=(None, None),
        ):
            with patch("webbrowser.open"):
                with pytest.raises(ValueError, match="no code received"):
                    await handler.authorize()


# ---------------------------------------------------------------------------
# TokenSet edge cases
# ---------------------------------------------------------------------------


class TestTokenSetEdgeCases:
    """Additional TokenSet edge case tests."""

    def test_is_expired_with_zero_expires_in(self) -> None:
        """Token with expires_in=0 and issued_at set is immediately expired."""
        token = TokenSet(
            access_token="token",
            expires_in=0,
            issued_at=time.time() - 1,
        )
        assert token.is_expired() is True

    def test_is_expired_with_large_expires_in(self) -> None:
        """Token with very large expires_in is not expired."""
        token = TokenSet(
            access_token="token",
            expires_in=999_999_999,
            issued_at=time.time(),
        )
        assert token.is_expired() is False

    def test_from_oauth_response_stores_client_credentials(self) -> None:
        """from_oauth_response preserves client_id and client_secret."""
        token = TokenSet.from_oauth_response(
            {"access_token": "tok", "token_type": "Bearer"},
            client_id="my_client",
            client_secret="my_secret",  # pragma: allowlist secret
        )
        assert token.client_id == "my_client"
        assert token.client_secret == "my_secret"  # pragma: allowlist secret

    def test_from_oauth_response_without_client_credentials(self) -> None:
        """from_oauth_response works with no client credentials."""
        token = TokenSet.from_oauth_response({"access_token": "tok", "token_type": "Bearer"})
        assert token.client_id is None
        assert token.client_secret is None

    def test_round_trip_serialization_with_all_fields(self) -> None:
        """TokenSet can be serialized and deserialized with all fields set."""
        original = TokenSet(
            access_token="access123",
            token_type="Bearer",
            expires_in=3600,
            refresh_token="refresh456",
            scope="read write",
            issued_at=time.time(),
            client_id="client_id",
            client_secret="client_secret",  # pragma: allowlist secret
        )

        data = original.to_dict()
        restored = TokenSet.from_dict(data)

        assert restored.access_token == original.access_token
        assert restored.refresh_token == original.refresh_token
        assert restored.scope == original.scope
        assert restored.client_id == original.client_id
        assert restored.client_secret == original.client_secret  # pragma: allowlist secret
        assert restored.expires_in == original.expires_in
