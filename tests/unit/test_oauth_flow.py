"""Tests for PKCE OAuth 2.0 authorization code flow.

Covers PKCE code verifier/challenge generation, authorization URL construction,
token exchange, token refresh, token storage, callback CSRF validation, and
end-to-end flow integration tests against the agent_framework.oauth module.
"""

import hashlib
import time
from base64 import urlsafe_b64encode
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from agent_framework.oauth.oauth_config import OAuthConfig
from agent_framework.oauth.oauth_flow import OAuthFlowHandler, generate_pkce_pair
from agent_framework.oauth.oauth_tokens import TokenSet, TokenStorage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_oauth_config(
    *,
    authorization_endpoint: str = "http://localhost/authorize",
    token_endpoint: str = "http://localhost/token",
    registration_endpoint: str | None = "http://localhost/register",
    code_challenge_methods: list[str] | None = None,
    token_auth_methods: list[str] | None = None,
    scopes: list[str] | None = None,
) -> OAuthConfig:
    """Return a minimal OAuthConfig suitable for unit tests."""
    return OAuthConfig(
        resource_url="http://localhost/resource",
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        registration_endpoint=registration_endpoint,
        code_challenge_methods_supported=code_challenge_methods or ["S256"],
        token_endpoint_auth_methods_supported=token_auth_methods or ["none"],
        scopes_supported=scopes or ["read", "write"],
    )


def make_token_response(
    access_token: str = "access_token_abc",
    token_type: str = "Bearer",
    expires_in: int = 3600,
    refresh_token: str | None = "refresh_token_xyz",
    scope: str | None = "read write",
) -> dict:
    """Return a minimal token endpoint response payload."""
    response: dict = {
        "access_token": access_token,
        "token_type": token_type,
        "expires_in": expires_in,
    }
    if refresh_token is not None:
        response["refresh_token"] = refresh_token
    if scope is not None:
        response["scope"] = scope
    return response


# ---------------------------------------------------------------------------
# PKCE code generation
# ---------------------------------------------------------------------------


class TestPKCECodeGeneration:
    """Tests for generate_pkce_pair() PKCE verifier/challenge generation."""

    def test_returns_two_strings(self) -> None:
        """generate_pkce_pair returns a (verifier, challenge) tuple of strings."""
        result = generate_pkce_pair()
        assert isinstance(result, tuple)
        assert len(result) == 2
        verifier, challenge = result
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)

    def test_verifier_meets_minimum_length(self) -> None:
        """Code verifier must be at least 43 characters per RFC 7636 §4.1."""
        verifier, _ = generate_pkce_pair()
        assert len(verifier) >= 43

    def test_verifier_uses_unreserved_characters(self) -> None:
        """Verifier must use only URL-safe base64 alphabet (no padding '=')."""
        verifier, _ = generate_pkce_pair()
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        assert all(c in allowed for c in verifier), (
            f"Verifier contains disallowed chars: {set(verifier) - allowed}"
        )

    def test_challenge_is_s256_of_verifier(self) -> None:
        """Code challenge must equal BASE64URL(SHA256(verifier)) per RFC 7636 §4.2."""
        verifier, challenge = generate_pkce_pair()
        expected = (
            urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        )
        assert challenge == expected

    def test_each_call_produces_unique_pair(self) -> None:
        """Each call to generate_pkce_pair must return a fresh, distinct pair."""
        pairs = {generate_pkce_pair() for _ in range(20)}
        # All 20 verifiers should be unique
        assert len(pairs) == 20

    def test_verifier_has_no_padding(self) -> None:
        """Verifier must not contain '=' padding characters."""
        for _ in range(10):
            verifier, _ = generate_pkce_pair()
            assert "=" not in verifier

    def test_challenge_has_no_padding(self) -> None:
        """Challenge must not contain '=' padding characters."""
        for _ in range(10):
            _, challenge = generate_pkce_pair()
            assert "=" not in challenge


# ---------------------------------------------------------------------------
# OAuthConfig helper methods
# ---------------------------------------------------------------------------


class TestOAuthConfigHelpers:
    """Tests for OAuthConfig capability-detection helpers."""

    def test_supports_pkce_true_when_s256_present(self) -> None:
        cfg = make_oauth_config(code_challenge_methods=["S256"])
        assert cfg.supports_pkce() is True

    def test_supports_pkce_false_when_no_methods(self) -> None:
        cfg = make_oauth_config(code_challenge_methods=None)
        # Override directly since make_oauth_config defaults to S256
        cfg.code_challenge_methods_supported = None
        assert cfg.supports_pkce() is False

    def test_supports_pkce_false_when_s256_absent(self) -> None:
        cfg = make_oauth_config(code_challenge_methods=["plain"])
        assert cfg.supports_pkce() is False

    def test_supports_public_clients_true(self) -> None:
        cfg = make_oauth_config(token_auth_methods=["none", "client_secret_post"])
        assert cfg.supports_public_clients() is True

    def test_supports_public_clients_false_when_none_absent(self) -> None:
        cfg = make_oauth_config(token_auth_methods=["client_secret_post"])
        assert cfg.supports_public_clients() is False

    def test_supports_public_clients_false_when_not_configured(self) -> None:
        cfg = make_oauth_config()
        cfg.token_endpoint_auth_methods_supported = None
        assert cfg.supports_public_clients() is False

    def test_supports_device_flow_via_endpoint(self) -> None:
        cfg = make_oauth_config()
        cfg.device_authorization_endpoint = "http://localhost/device"
        assert cfg.supports_device_flow() is True

    def test_supports_device_flow_via_grant_type(self) -> None:
        cfg = make_oauth_config()
        cfg.device_authorization_endpoint = None
        cfg.grant_types_supported = ["urn:ietf:params:oauth:grant-type:device_code"]
        assert cfg.supports_device_flow() is True

    def test_does_not_support_device_flow_by_default(self) -> None:
        cfg = make_oauth_config()
        cfg.device_authorization_endpoint = None
        cfg.grant_types_supported = ["authorization_code"]
        assert cfg.supports_device_flow() is False


# ---------------------------------------------------------------------------
# TokenSet dataclass
# ---------------------------------------------------------------------------


class TestTokenSet:
    """Tests for TokenSet expiry logic and serialization helpers."""

    def test_is_not_expired_without_expiry_info(self) -> None:
        ts = TokenSet(access_token="tok")
        assert ts.is_expired() is False

    def test_is_not_expired_for_fresh_token(self) -> None:
        ts = TokenSet(access_token="tok", expires_in=3600, issued_at=time.time())
        assert ts.is_expired() is False

    def test_is_expired_for_old_token(self) -> None:
        ts = TokenSet(access_token="tok", expires_in=60, issued_at=time.time() - 120)
        assert ts.is_expired() is True

    def test_is_expired_respects_buffer(self) -> None:
        # Token expires in 30 s but default buffer is 60 s → considered expired
        ts = TokenSet(access_token="tok", expires_in=30, issued_at=time.time())
        assert ts.is_expired(buffer_seconds=60) is True

    def test_from_oauth_response_sets_issued_at(self) -> None:
        before = time.time()
        ts = TokenSet.from_oauth_response(make_token_response())
        after = time.time()
        assert ts.issued_at is not None
        assert before <= ts.issued_at <= after

    def test_from_oauth_response_stores_all_fields(self) -> None:
        payload = make_token_response(
            access_token="at",
            token_type="Bearer",
            expires_in=1800,
            refresh_token="rt",
            scope="read",
        )
        ts = TokenSet.from_oauth_response(
            payload, client_id="cid", client_secret="cs"
        )  # pragma: allowlist secret
        assert ts.access_token == "at"
        assert ts.token_type == "Bearer"
        assert ts.expires_in == 1800
        assert ts.refresh_token == "rt"
        assert ts.scope == "read"
        assert ts.client_id == "cid"
        assert ts.client_secret == "cs"  # pragma: allowlist secret

    def test_round_trip_serialization(self) -> None:
        ts = TokenSet.from_oauth_response(make_token_response(), client_id="cid")
        reconstructed = TokenSet.from_dict(ts.to_dict())
        assert reconstructed.access_token == ts.access_token
        assert reconstructed.refresh_token == ts.refresh_token
        assert reconstructed.issued_at == ts.issued_at

    def test_from_oauth_response_without_optional_fields(self) -> None:
        payload = {"access_token": "at"}
        ts = TokenSet.from_oauth_response(payload)
        assert ts.access_token == "at"
        assert ts.token_type == "Bearer"
        assert ts.expires_in is None
        assert ts.refresh_token is None
        assert ts.scope is None


# ---------------------------------------------------------------------------
# TokenStorage file-based persistence
# ---------------------------------------------------------------------------


class TestTokenStorage:
    """Tests for TokenStorage save/load/delete and encryption behaviour."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> TokenStorage:
        return TokenStorage(storage_dir=tmp_path / "tokens")

    def test_creates_storage_directory(self, tmp_path: Path) -> None:
        dest = tmp_path / "new_tokens"
        assert not dest.exists()
        TokenStorage(storage_dir=dest)
        assert dest.is_dir()

    def test_save_and_load_roundtrip(self, storage: TokenStorage) -> None:
        ts = TokenSet.from_oauth_response(make_token_response())
        storage.save_token("http://example.com", ts)
        loaded = storage.load_token("http://example.com")
        assert loaded is not None
        assert loaded.access_token == ts.access_token

    def test_load_missing_token_returns_none(self, storage: TokenStorage) -> None:
        assert storage.load_token("http://missing.example.com") is None

    def test_load_verifies_server_url(self, storage: TokenStorage) -> None:
        """load_token returns None if the stored URL doesn't match the requested URL."""
        import json
        import os

        ts = TokenSet.from_oauth_response(make_token_response())
        storage.save_token("http://server-a.example.com", ts)
        # Disable encryption so we can manipulate the raw JSON
        storage.cipher = None
        token_file = storage._get_token_file("http://server-a.example.com")
        # Write plaintext JSON with a mismatched server_url at the same path
        tampered = {
            "server_url": "http://different.example.com",
            "token": ts.to_dict(),
        }
        fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(tampered).encode())
        assert storage.load_token("http://server-a.example.com") is None

    def test_delete_existing_token(self, storage: TokenStorage) -> None:
        ts = TokenSet.from_oauth_response(make_token_response())
        storage.save_token("http://example.com", ts)
        storage.delete_token("http://example.com")
        assert storage.load_token("http://example.com") is None

    def test_delete_nonexistent_token_does_not_raise(self, storage: TokenStorage) -> None:
        storage.delete_token("http://never-saved.example.com")  # no exception

    def test_different_servers_have_separate_files(self, storage: TokenStorage) -> None:
        ts_a = TokenSet.from_oauth_response(make_token_response(access_token="token_a"))
        ts_b = TokenSet.from_oauth_response(make_token_response(access_token="token_b"))
        storage.save_token("http://server-a.example.com", ts_a)
        storage.save_token("http://server-b.example.com", ts_b)

        loaded_a = storage.load_token("http://server-a.example.com")
        loaded_b = storage.load_token("http://server-b.example.com")
        assert loaded_a is not None and loaded_a.access_token == "token_a"
        assert loaded_b is not None and loaded_b.access_token == "token_b"

    def test_token_file_uses_url_hash(self, storage: TokenStorage) -> None:
        url = "http://example.com"
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        expected_file = storage.storage_dir / f"{url_hash}.json"
        ts = TokenSet.from_oauth_response(make_token_response())
        storage.save_token(url, ts)
        assert expected_file.exists()

    def test_tokens_not_stored_as_plaintext(self, tmp_path: Path) -> None:
        """Access tokens must not appear verbatim in the on-disk file."""
        storage = TokenStorage(storage_dir=tmp_path / "enc_tokens")
        secret = "SUPER_SECRET_ACCESS_TOKEN_VALUE"
        ts = TokenSet.from_oauth_response(make_token_response(access_token=secret))
        storage.save_token("http://example.com", ts)
        token_file = storage._get_token_file("http://example.com")
        raw_bytes = token_file.read_bytes()
        assert secret.encode() not in raw_bytes

    def test_load_corrupted_file_returns_none(self, storage: TokenStorage) -> None:
        url = "http://corrupt.example.com"
        token_file = storage._get_token_file(url)
        import os

        fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(b"this is not valid json or ciphertext !!!")
        assert storage.load_token(url) is None

    def test_storage_directory_has_700_permissions(self, tmp_path: Path) -> None:
        storage = TokenStorage(storage_dir=tmp_path / "secure_tokens")
        mode = oct(storage.storage_dir.stat().st_mode)[-3:]
        assert mode == "700"

    def test_overwrite_updates_token(self, storage: TokenStorage) -> None:
        url = "http://example.com"
        ts_old = TokenSet.from_oauth_response(make_token_response(access_token="old_token"))
        ts_new = TokenSet.from_oauth_response(make_token_response(access_token="new_token"))
        storage.save_token(url, ts_old)
        storage.save_token(url, ts_new)
        loaded = storage.load_token(url)
        assert loaded is not None
        assert loaded.access_token == "new_token"


# ---------------------------------------------------------------------------
# OAuthFlowHandler – client registration
# ---------------------------------------------------------------------------


class TestOAuthFlowHandlerRegistration:
    """Tests for OAuthFlowHandler.register_client()."""

    @pytest.fixture
    def handler(self) -> OAuthFlowHandler:
        return OAuthFlowHandler(oauth_config=make_oauth_config())

    @pytest.mark.asyncio
    async def test_register_confidential_client(self, handler: OAuthFlowHandler) -> None:
        """Registration with client_secret returns (client_id, client_secret)."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "client_id": "registered_cid",
            "client_secret": "registered_cs",  # pragma: allowlist secret
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            cid, cs = await handler.register_client()

        assert cid == "registered_cid"
        assert cs == "registered_cs"  # pragma: allowlist secret
        assert handler.client_id == "registered_cid"
        assert handler.client_secret == "registered_cs"  # pragma: allowlist secret

    @pytest.mark.asyncio
    async def test_register_public_client(self) -> None:
        """Public client registration returns no client_secret."""
        cfg = make_oauth_config(token_auth_methods=["none"])
        handler = OAuthFlowHandler(oauth_config=cfg)

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"client_id": "pub_cid"}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            cid, cs = await handler.register_client()

        assert cid == "pub_cid"
        assert cs is None

    @pytest.mark.asyncio
    async def test_register_raises_if_no_endpoint(self) -> None:
        """ValueError raised when server has no registration endpoint."""
        cfg = make_oauth_config(registration_endpoint=None)
        handler = OAuthFlowHandler(oauth_config=cfg)
        with pytest.raises(ValueError, match="does not support dynamic client registration"):
            await handler.register_client()

    @pytest.mark.asyncio
    async def test_register_raises_on_http_error(self, handler: OAuthFlowHandler) -> None:
        """ValueError raised when registration HTTP request fails."""
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(ValueError, match="Failed to register OAuth client"):
                await handler.register_client()


# ---------------------------------------------------------------------------
# OAuthFlowHandler – token exchange (_exchange_code)
# ---------------------------------------------------------------------------


class TestOAuthFlowHandlerTokenExchange:
    """Tests for OAuthFlowHandler._exchange_code()."""

    @pytest.fixture
    def handler(self) -> OAuthFlowHandler:
        h = OAuthFlowHandler(oauth_config=make_oauth_config())
        h.client_id = "test_client"
        return h

    @pytest.mark.asyncio
    async def test_successful_exchange_includes_pkce_verifier(
        self, handler: OAuthFlowHandler
    ) -> None:
        """Token exchange sends the code_verifier in the POST body."""
        captured: list[dict] = []

        async def fake_post(url: str, *, data: dict, headers: dict) -> MagicMock:
            captured.append(data)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = make_token_response()
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.AsyncClient.post", side_effect=fake_post):
            result = await handler._exchange_code(code="auth_code_123", code_verifier="my_verifier")

        assert result.access_token == "access_token_abc"
        assert len(captured) == 1
        assert captured[0]["code_verifier"] == "my_verifier"
        assert captured[0]["grant_type"] == "authorization_code"

    @pytest.mark.asyncio
    async def test_exchange_omits_client_secret_for_public_client(
        self, handler: OAuthFlowHandler
    ) -> None:
        """No client_secret field in token request for public clients."""
        handler.client_secret = None
        captured: list[dict] = []

        async def fake_post(url: str, *, data: dict, headers: dict) -> MagicMock:
            captured.append(data)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = make_token_response()
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.AsyncClient.post", side_effect=fake_post):
            await handler._exchange_code(code="code", code_verifier="verifier")

        assert "client_secret" not in captured[0]

    @pytest.mark.asyncio
    async def test_exchange_includes_client_secret_for_confidential_client(
        self, handler: OAuthFlowHandler
    ) -> None:
        """client_secret is included in token request for confidential clients."""
        handler.client_secret = "secret123"  # pragma: allowlist secret
        captured: list[dict] = []

        async def fake_post(url: str, *, data: dict, headers: dict) -> MagicMock:
            captured.append(data)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = make_token_response()
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.AsyncClient.post", side_effect=fake_post):
            await handler._exchange_code(code="code", code_verifier="verifier")

        assert captured[0]["client_secret"] == "secret123"  # pragma: allowlist secret

    @pytest.mark.asyncio
    async def test_exchange_raises_on_http_status_error_with_oauth_body(
        self, handler: OAuthFlowHandler
    ) -> None:
        """ValueError raised when server returns 4xx with OAuth error body."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Authorization code is invalid",
        }
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_resp
        )

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            with pytest.raises(ValueError, match="invalid_grant"):
                await handler._exchange_code(code="bad_code", code_verifier="verifier")

    @pytest.mark.asyncio
    async def test_exchange_raises_on_network_error(self, handler: OAuthFlowHandler) -> None:
        """ValueError raised when a network error occurs during token exchange."""
        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.NetworkError("connection lost"),
        ):
            with pytest.raises(ValueError, match="Failed to exchange code"):
                await handler._exchange_code(code="code", code_verifier="verifier")

    @pytest.mark.asyncio
    async def test_exchange_returns_token_with_client_credentials(
        self, handler: OAuthFlowHandler
    ) -> None:
        """Returned TokenSet stores client_id for future refresh operations."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = make_token_response()
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            result = await handler._exchange_code(code="code", code_verifier="verifier")

        assert result.client_id == "test_client"


# ---------------------------------------------------------------------------
# OAuthFlowHandler – token refresh (inherited from OAuthHandlerBase)
# ---------------------------------------------------------------------------


class TestOAuthFlowHandlerTokenRefresh:
    """Tests for OAuthFlowHandler.refresh_token() (inherited from base class)."""

    @pytest.fixture
    def handler(self) -> OAuthFlowHandler:
        h = OAuthFlowHandler(oauth_config=make_oauth_config())
        h.client_id = "test_client"
        return h

    @pytest.mark.asyncio
    async def test_successful_refresh_returns_new_token_set(
        self, handler: OAuthFlowHandler
    ) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = make_token_response(access_token="new_access_token")
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            result = await handler.refresh_token("old_refresh_token")

        assert result.access_token == "new_access_token"

    @pytest.mark.asyncio
    async def test_refresh_raises_without_client_id(self) -> None:
        """refresh_token raises ValueError when client is not yet registered."""
        h = OAuthFlowHandler(oauth_config=make_oauth_config())
        # client_id is None by default
        with pytest.raises(ValueError, match="Client not registered"):
            await h.refresh_token("some_refresh_token")

    @pytest.mark.asyncio
    async def test_refresh_raises_on_invalid_grant(self, handler: OAuthFlowHandler) -> None:
        """ValueError raised when server rejects refresh token (invalid_grant)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "invalid_grant"}
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_resp
        )

        with patch("httpx.AsyncClient.post", return_value=mock_resp):
            with pytest.raises(ValueError, match="invalid_grant"):
                await handler.refresh_token("expired_refresh_token")

    @pytest.mark.asyncio
    async def test_refresh_sends_client_secret_when_confidential(
        self, handler: OAuthFlowHandler
    ) -> None:
        handler.client_secret = "s3cr3t"  # pragma: allowlist secret
        captured: list[dict] = []

        async def fake_post(url: str, *, data: dict, headers: dict) -> MagicMock:
            captured.append(data)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = make_token_response()
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.AsyncClient.post", side_effect=fake_post):
            await handler.refresh_token("rt")

        assert captured[0].get("client_secret") == "s3cr3t"  # pragma: allowlist secret

    @pytest.mark.asyncio
    async def test_refresh_uses_provided_client_id_override(
        self, handler: OAuthFlowHandler
    ) -> None:
        """refresh_token accepts an explicit client_id override."""
        captured: list[dict] = []

        async def fake_post(url: str, *, data: dict, headers: dict) -> MagicMock:
            captured.append(data)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = make_token_response()
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.AsyncClient.post", side_effect=fake_post):
            await handler.refresh_token("rt", client_id="override_cid")

        assert captured[0]["client_id"] == "override_cid"


# ---------------------------------------------------------------------------
# OAuthFlowHandler – authorization URL construction
# ---------------------------------------------------------------------------


class TestOAuthFlowHandlerAuthURL:
    """Tests for authorization URL construction inside authorize()."""

    def test_redirect_uri_uses_configured_port(self) -> None:
        handler = OAuthFlowHandler(oauth_config=make_oauth_config(), redirect_port=9999)
        assert handler.redirect_uri == "http://localhost:9999/callback"

    def test_default_redirect_port_is_8889(self) -> None:
        handler = OAuthFlowHandler(oauth_config=make_oauth_config())
        assert handler.redirect_port == 8889
        assert "8889" in handler.redirect_uri

    def test_scopes_default_to_server_scopes(self) -> None:
        cfg = make_oauth_config(scopes=["custom_scope"])
        handler = OAuthFlowHandler(oauth_config=cfg)
        assert "custom_scope" in handler.scopes

    def test_custom_scopes_override_server_scopes(self) -> None:
        cfg = make_oauth_config(scopes=["server_scope"])
        handler = OAuthFlowHandler(oauth_config=cfg, scopes="override_scope")
        assert handler.scopes == "override_scope"


# ---------------------------------------------------------------------------
# End-to-end PKCE authorize() flow
# ---------------------------------------------------------------------------


class TestOAuthFlowHandlerAuthorize:
    """Integration-level tests for the full authorize() flow."""

    @pytest.fixture
    def cfg(self) -> OAuthConfig:
        return make_oauth_config()

    @pytest.mark.asyncio
    async def test_authorize_registers_client_when_none_set(self, cfg: OAuthConfig) -> None:
        """authorize() registers a client when client_id is not pre-set."""
        handler = OAuthFlowHandler(oauth_config=cfg)

        reg_resp = MagicMock()
        reg_resp.status_code = 201
        reg_resp.json.return_value = {"client_id": "auto_client"}
        reg_resp.raise_for_status = MagicMock()

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = make_token_response()
        token_resp.raise_for_status = MagicMock()

        with (
            patch("httpx.AsyncClient.post", side_effect=[reg_resp, token_resp]),
            patch("webbrowser.open"),
            patch.object(
                handler,
                "_run_callback_server",
                new=AsyncMock(return_value=("the_code", None)),
            ),
        ):
            result = await handler.authorize()

        assert handler.client_id == "auto_client"
        assert result.access_token == "access_token_abc"

    @pytest.mark.asyncio
    async def test_authorize_skips_registration_when_client_id_preset(
        self, cfg: OAuthConfig
    ) -> None:
        """authorize() skips registration when client_id is already set."""
        handler = OAuthFlowHandler(oauth_config=cfg)
        handler.client_id = "preset_client"

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = make_token_response()
        token_resp.raise_for_status = MagicMock()

        with (
            patch("httpx.AsyncClient.post", return_value=token_resp) as mock_post,
            patch("webbrowser.open"),
            patch.object(
                handler,
                "_run_callback_server",
                new=AsyncMock(return_value=("the_code", None)),
            ),
        ):
            result = await handler.authorize()

        # POST called exactly once (token exchange, no registration)
        mock_post.assert_called_once()
        assert result.access_token == "access_token_abc"

    @pytest.mark.asyncio
    async def test_authorize_raises_when_no_code_received(self, cfg: OAuthConfig) -> None:
        """authorize() raises ValueError when callback provides no code."""
        handler = OAuthFlowHandler(oauth_config=cfg)
        handler.client_id = "client"

        with (
            patch("webbrowser.open"),
            patch.object(
                handler,
                "_run_callback_server",
                new=AsyncMock(return_value=(None, None)),
            ),
        ):
            with pytest.raises(ValueError, match="no code received"):
                await handler.authorize()

    @pytest.mark.asyncio
    async def test_authorize_raises_on_callback_error(self, cfg: OAuthConfig) -> None:
        """authorize() raises ValueError when OAuth error is returned by callback."""
        handler = OAuthFlowHandler(oauth_config=cfg)
        handler.client_id = "client"

        with (
            patch("webbrowser.open"),
            patch.object(
                handler,
                "_run_callback_server",
                new=AsyncMock(return_value=(None, "access_denied")),
            ),
        ):
            with pytest.raises(ValueError, match="access_denied"):
                await handler.authorize()

    @pytest.mark.asyncio
    async def test_authorize_authorization_url_contains_pkce_params(self, cfg: OAuthConfig) -> None:
        """The authorization URL sent to the browser must include PKCE parameters."""
        handler = OAuthFlowHandler(oauth_config=cfg)
        handler.client_id = "client"

        opened_urls: list[str] = []

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = make_token_response()
        token_resp.raise_for_status = MagicMock()

        with (
            patch("httpx.AsyncClient.post", return_value=token_resp),
            patch("webbrowser.open", side_effect=lambda url: opened_urls.append(url)),
            patch.object(
                handler,
                "_run_callback_server",
                new=AsyncMock(return_value=("the_code", None)),
            ),
        ):
            await handler.authorize()

        assert opened_urls, "webbrowser.open was not called"
        auth_url = opened_urls[0]
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url
        assert "state=" in auth_url
        assert "response_type=code" in auth_url

    @pytest.mark.asyncio
    async def test_authorize_csrf_state_matches_callback_state(self, cfg: OAuthConfig) -> None:
        """The state sent in the auth URL must equal the state expected by the server."""
        handler = OAuthFlowHandler(oauth_config=cfg)
        handler.client_id = "client"

        opened_urls: list[str] = []
        expected_states: list[str] = []

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = make_token_response()
        token_resp.raise_for_status = MagicMock()

        async def capture_state(expected_state: str) -> tuple[str | None, str | None]:
            expected_states.append(expected_state)
            return "code_xyz", None

        with (
            patch("httpx.AsyncClient.post", return_value=token_resp),
            patch("webbrowser.open", side_effect=lambda url: opened_urls.append(url)),
            patch.object(handler, "_run_callback_server", side_effect=capture_state),
        ):
            await handler.authorize()

        assert opened_urls and expected_states
        auth_url = opened_urls[0]
        # Extract state from URL
        from urllib.parse import parse_qs, urlparse

        qs = parse_qs(urlparse(auth_url).query)
        url_state = qs["state"][0]
        callback_state = expected_states[0]
        assert url_state == callback_state
