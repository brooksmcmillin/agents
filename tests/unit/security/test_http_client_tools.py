"""Tests for http_client.py MCP tool functions: redirect validation, allowlist enforcement,
and sensitive field redaction.

Covers the specific security-critical paths:
- _safe_request redirect following within the allowlist
- _safe_request blocking redirects to disallowed hosts
- _check_target_allowed path traversal prevention
- _redact_sensitive masking of token/password fields
- _check_target_allowed fail-secure behavior when env var is absent
- MCP tool functions (http_request, http_session_login, http_upload_file)

Note on allowlist path matching: _check_target_allowed uses posixpath.normpath for
path prefix matching. A prefix of 'http://example.com' (no path) normalizes to '/'
which only exactly matches 'http://example.com/'. To allow all paths under a host
use 'http://example.com/some/path' as prefix. Tests use path-based prefixes to ensure
correct behavior is tested (e.g. 'http://example.com/app').
"""

import base64
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agent_framework.tools.http_client import (
    _check_target_allowed,
    _redact_sensitive,
    _safe_request,
    _session_key,
    _sessions,
    http_request,
    http_session_login,
    http_upload_file,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_response(
    status_code: int,
    url: str,
    headers: dict[str, str] | None = None,
    content: bytes = b"response body",
) -> httpx.Response:
    """Build a real httpx.Response for mocking."""
    return httpx.Response(
        status_code=status_code,
        headers=headers or {},
        content=content,
        request=httpx.Request("GET", url),
    )


_ALLOWLIST_PATCH = "agent_framework.tools.http_client._check_target_allowed"
_SAFE_REQUEST_PATCH = "agent_framework.tools.http_client._safe_request"


def _allow_all_targets(url: str) -> None:
    """No-op _check_target_allowed stub that allows all URLs."""
    pass


# ---------------------------------------------------------------------------
# Redirect validation tests (named per task specification)
# ---------------------------------------------------------------------------


class TestSafeRequestFollowsRedirectsWithinAllowlist:
    """test_safe_request_follows_redirects_within_allowlist

    Verifies that _safe_request follows redirects when each hop is within the allowlist.
    These tests patch _check_target_allowed with a hostname-based stub (matching the
    pattern used in test_http_client_security.py) to isolate redirect mechanics.
    """

    @pytest.mark.asyncio
    async def test_safe_request_follows_redirects_within_allowlist(self) -> None:
        """Redirects that stay within the allowlist are followed successfully."""
        redirect_resp = _make_response(
            302,
            "http://example.com/app/old",
            headers={"location": "http://example.com/app/new"},
        )
        final_resp = _make_response(200, "http://example.com/app/new", content=b"done")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "GET", "http://example.com/app/old")

        assert resp.status_code == 200
        assert len(resp.history) == 1
        assert resp.history[0].status_code == 302

    @pytest.mark.asyncio
    async def test_safe_request_follows_redirect_to_subpath_within_allowlist(self) -> None:
        """Redirects to deeper subpaths on the same allowed host are followed."""
        redirect_resp = _make_response(
            301,
            "http://target.com/app/login",
            headers={"location": "http://target.com/app/dashboard"},
        )
        final_resp = _make_response(200, "http://target.com/app/dashboard", content=b"welcome")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "GET", "http://target.com/app/login")

        assert resp.status_code == 200
        assert resp.history[0].status_code == 301

    @pytest.mark.asyncio
    async def test_safe_request_follows_chained_redirects_within_allowlist(self) -> None:
        """A chain of multiple redirects within the allowlist are all followed."""
        r1 = _make_response(
            301, "http://example.com/a", headers={"location": "http://example.com/b"}
        )
        r2 = _make_response(
            302, "http://example.com/b", headers={"location": "http://example.com/c"}
        )
        r3 = _make_response(200, "http://example.com/c", content=b"final")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[r1, r2, r3])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "GET", "http://example.com/a")

        assert resp.status_code == 200
        assert len(resp.history) == 2

    @pytest.mark.asyncio
    async def test_safe_request_follows_redirects_using_real_allowlist(self) -> None:
        """Redirects within a path-based allowlist pass _check_target_allowed."""
        redirect_resp = _make_response(
            302,
            "http://example.com/api/v1/old",
            headers={"location": "http://example.com/api/v1/new"},
        )
        final_resp = _make_response(200, "http://example.com/api/v1/new", content=b"done")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        # Use a path-based allowlist so both URLs pass the real check
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            resp = await _safe_request(client, "GET", "http://example.com/api/v1/old")

        assert resp.status_code == 200
        assert len(resp.history) == 1


class TestSafeRequestBlocksRedirectToDisallowedHost:
    """test_safe_request_blocks_redirect_to_disallowed_host"""

    @pytest.mark.asyncio
    async def test_safe_request_blocks_redirect_to_disallowed_host(self) -> None:
        """A redirect to a host outside the allowlist raises ValueError (SSRF prevention)."""
        redirect_resp = _make_response(
            302,
            "http://allowed.com/api/start",
            headers={"location": "http://evil.internal/admin"},
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://allowed.com/api"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await _safe_request(client, "GET", "http://allowed.com/api/start")

    @pytest.mark.asyncio
    async def test_safe_request_blocks_redirect_to_localhost(self) -> None:
        """A redirect to localhost is blocked."""
        redirect_resp = _make_response(
            301,
            "http://allowed.com/app/page",
            headers={"location": "http://localhost/internal"},
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://allowed.com/app"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await _safe_request(client, "GET", "http://allowed.com/app/page")

    @pytest.mark.asyncio
    async def test_safe_request_blocks_redirect_to_private_ip(self) -> None:
        """A redirect to a private IP range is blocked."""
        redirect_resp = _make_response(
            302,
            "http://allowed.com/app/api",
            headers={"location": "http://192.168.1.100/router"},
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://allowed.com/app"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await _safe_request(client, "GET", "http://allowed.com/app/api")

    @pytest.mark.asyncio
    async def test_safe_request_validates_each_redirect_hop(self) -> None:
        """Each hop is validated; later hops to disallowed hosts are blocked."""
        r1 = _make_response(
            301,
            "http://allowed.com/app/step1",
            headers={"location": "http://allowed.com/app/step2"},
        )
        r2 = _make_response(
            302,
            "http://allowed.com/app/step2",
            headers={"location": "http://evil.com/steal"},
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[r1, r2])

        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://allowed.com/app"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await _safe_request(client, "GET", "http://allowed.com/app/step1")

    @pytest.mark.asyncio
    async def test_safe_request_blocks_scheme_change_on_redirect(self) -> None:
        """A redirect that changes scheme (https -> http) to disallowed host is blocked."""
        redirect_resp = _make_response(
            302,
            "https://allowed.com/app/page",
            headers={"location": "http://other.com/api"},
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "https://allowed.com/app"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await _safe_request(client, "GET", "https://allowed.com/app/page")


# ---------------------------------------------------------------------------
# Path traversal prevention tests
# ---------------------------------------------------------------------------


class TestCheckTargetAllowedBlocksPathTraversal:
    """test_check_target_allowed_blocks_path_traversal"""

    def test_check_target_allowed_blocks_path_traversal(self) -> None:
        """Requests with path traversal sequences are blocked after normalization."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api/../admin")

    def test_check_target_allowed_blocks_double_dot_traversal(self) -> None:
        """Double-dot sequences that escape the allowed path prefix are blocked."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api/v1"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api/v1/../../admin")

    def test_check_target_allowed_blocks_path_prefix_confusion(self) -> None:
        """Path '/api/v1' does NOT match '/api/v1admin' (boundary check prevents this)."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api/v1"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api/v1admin")

    def test_check_target_allowed_allows_legitimate_subpath(self) -> None:
        """A legitimate subpath under the allowed prefix is permitted."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            # Should not raise
            _check_target_allowed("http://example.com/api/users/profile")

    def test_check_target_allowed_blocks_traversal_to_sibling_path(self) -> None:
        """Traversal to a sibling path outside the allowed prefix is blocked."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api/../config")

    def test_check_target_allowed_allows_exact_prefix_path(self) -> None:
        """The exact prefix path itself is allowed."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api/v1"}):
            # Should not raise
            _check_target_allowed("http://example.com/api/v1")

    def test_check_target_allowed_blocks_subdomain_bypass(self) -> None:
        """evil.example.com does not match example.com (no subdomain bypass)."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://evil.example.com/api/resource")


# ---------------------------------------------------------------------------
# Sensitive field redaction tests
# ---------------------------------------------------------------------------


class TestRedactSensitiveMasksTokenFields:
    """test_redact_sensitive_masks_token_fields"""

    def test_redact_sensitive_masks_token_fields(self) -> None:
        """Token fields are redacted from dict results."""
        result = _redact_sensitive({"token": "super-secret-token-value"})
        assert result["token"] == "[REDACTED]"

    def test_redact_sensitive_masks_password(self) -> None:
        """Password fields are always redacted."""
        result = _redact_sensitive({"password": "s3cret123"})
        assert result["password"] == "[REDACTED]"

    def test_redact_sensitive_masks_api_key_variants(self) -> None:
        """api-key, API_KEY, Api-Key all match the sensitive list."""
        for key in ("api-key", "API_KEY", "Api-Key", "apikey"):
            result = _redact_sensitive({key: "key-value"})
            assert result[key] == "[REDACTED]", f"Key {key!r} was not redacted"

    def test_redact_sensitive_masks_access_token(self) -> None:
        """access_token is redacted regardless of case."""
        result = _redact_sensitive({"access_token": "tok123", "ACCESS_TOKEN": "tok456"})
        assert result["access_token"] == "[REDACTED]"
        assert result["ACCESS_TOKEN"] == "[REDACTED]"

    def test_redact_sensitive_masks_refresh_token(self) -> None:
        """refresh_token fields are redacted."""
        result = _redact_sensitive({"refresh_token": "reftok123"})
        assert result["refresh_token"] == "[REDACTED]"

    def test_redact_sensitive_masks_authorization_header(self) -> None:
        """Authorization header values are redacted."""
        result = _redact_sensitive({"Authorization": "Bearer eyJ..."})
        assert result["Authorization"] == "[REDACTED]"

    def test_redact_sensitive_masks_client_secret(self) -> None:
        """client_secret is redacted."""
        result = _redact_sensitive({"client_secret": "oauth-secret"})
        assert result["client_secret"] == "[REDACTED]"

    def test_redact_sensitive_masks_private_key(self) -> None:
        """private_key fields are redacted."""
        result = _redact_sensitive({"private_key": "-----BEGIN RSA PRIVATE KEY-----"})
        assert result["private_key"] == "[REDACTED]"

    def test_redact_sensitive_masks_session_token(self) -> None:
        """session_token is redacted."""
        result = _redact_sensitive({"session_token": "sess-token-value"})
        assert result["session_token"] == "[REDACTED]"

    def test_redact_sensitive_preserves_non_sensitive_fields(self) -> None:
        """Non-sensitive fields are preserved as-is."""
        result = _redact_sensitive({"username": "alice", "role": "admin"})
        assert result["username"] == "alice"
        assert result["role"] == "admin"

    def test_redact_sensitive_mixed_credentials_dict(self) -> None:
        """Mixed dict: sensitive values redacted, safe values preserved."""
        data = {
            "username": "alice",
            "password": "hunter2",
            "token": "tok-abc",
            "role": "user",
        }
        result = _redact_sensitive(data)
        assert result["username"] == "alice"
        assert result["password"] == "[REDACTED]"
        assert result["token"] == "[REDACTED]"
        assert result["role"] == "user"

    def test_redact_sensitive_does_not_leak_token_value(self) -> None:
        """The actual token value is not present anywhere in the output."""
        secret = "top-secret-bearer-token-xyz"
        result = _redact_sensitive({"Authorization": f"Bearer {secret}"})
        for v in result.values():
            assert secret not in v, f"Token value leaked in output: {v!r}"


# ---------------------------------------------------------------------------
# Fail-secure env var absence tests
# ---------------------------------------------------------------------------


class TestCheckTargetAllowedFailsWithoutEnv:
    """test_check_target_allowed_fails_without_env"""

    def test_check_target_allowed_fails_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When REDTEAM_ALLOWED_TARGETS is not set, all requests are denied."""
        monkeypatch.delenv("REDTEAM_ALLOWED_TARGETS", raising=False)
        with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
            _check_target_allowed("http://example.com/api")

    def test_check_target_allowed_fails_with_empty_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When REDTEAM_ALLOWED_TARGETS is empty string, all requests are denied."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "")
        with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
            _check_target_allowed("http://example.com/api")

    def test_check_target_allowed_fails_without_env_for_any_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-secure applies to all URLs, even loopback."""
        monkeypatch.delenv("REDTEAM_ALLOWED_TARGETS", raising=False)
        for url in [
            "http://example.com/api",
            "https://api.example.com/v1/resource",
            "http://localhost/admin",
            "http://192.168.1.1/",
        ]:
            with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
                _check_target_allowed(url)

    def test_check_target_allowed_succeeds_when_env_is_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When env var is set correctly with a path prefix, matching URLs are allowed."""
        # Use a path-based prefix: 'http://example.com/app' allows /app and /app/*
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        # Should not raise
        _check_target_allowed("http://example.com/app/any/path")

    def test_check_target_allowed_error_message_mentions_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Error message when env var is absent mentions REDTEAM_ALLOWED_TARGETS."""
        monkeypatch.delenv("REDTEAM_ALLOWED_TARGETS", raising=False)
        with pytest.raises(ValueError) as exc_info:
            _check_target_allowed("http://example.com/")
        assert "REDTEAM_ALLOWED_TARGETS" in str(exc_info.value)


# ---------------------------------------------------------------------------
# MCP tool function tests (http_request, http_session_login, http_upload_file)
# ---------------------------------------------------------------------------


class TestHttpRequestTool:
    """Tests for the http_request MCP tool function."""

    def setup_method(self) -> None:
        _sessions.clear()

    def _make_mock_response(
        self,
        status: int = 200,
        url: str = "http://example.com/app",
        content: bytes = b"ok",
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        resp = _make_response(status, url, headers, content)
        resp.history = []  # type: ignore[attr-defined]
        return resp

    @pytest.mark.asyncio
    async def test_http_request_returns_expected_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_request returns status, headers, body, elapsed, cookies_set, redirect_history."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        mock_resp = self._make_mock_response(200)

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp):
            result = await http_request("test_agent", "http://example.com/app")

        assert result["status"] == 200
        assert "body" in result
        assert "headers" in result
        assert "elapsed_seconds" in result
        assert "cookies_set" in result
        assert "redirect_history" in result
        assert "final_url" in result

    @pytest.mark.asyncio
    async def test_http_request_blocked_when_url_not_in_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_request raises ValueError for URLs outside the allowlist."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
            await http_request("test_agent", "http://evil.com/api")

    @pytest.mark.asyncio
    async def test_http_request_blocked_when_no_allowlist_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_request raises ValueError when REDTEAM_ALLOWED_TARGETS is not set."""
        monkeypatch.delenv("REDTEAM_ALLOWED_TARGETS", raising=False)
        with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
            await http_request("test_agent", "http://example.com/api")

    @pytest.mark.asyncio
    async def test_http_request_with_json_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """http_request passes json_body correctly to _safe_request."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        mock_resp = self._make_mock_response(201)

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp) as mock_safe:
            await http_request(
                "test_agent",
                "http://example.com/app",
                method="POST",
                json_body={"key": "value"},
            )

        # Verify json kwarg was passed to _safe_request
        call_kwargs = mock_safe.call_args.kwargs
        assert call_kwargs.get("json") == {"key": "value"}

    @pytest.mark.asyncio
    async def test_http_request_with_redirect_history_populated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_request includes redirect history in response when redirects occurred."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")

        # Build a redirect response in history
        redirect_resp = _make_response(
            301,
            "http://example.com/app/old",
            headers={"location": "http://example.com/app/new"},
        )
        final_resp = self._make_mock_response(200)
        final_resp.history = [redirect_resp]  # type: ignore[attr-defined]

        with patch(_SAFE_REQUEST_PATCH, return_value=final_resp):
            result = await http_request("test_agent", "http://example.com/app/old")

        assert len(result["redirect_history"]) == 1
        assert result["redirect_history"][0]["status"] == 301

    @pytest.mark.asyncio
    async def test_http_request_updates_session_cookies(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_request stores cookies in the named session."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        mock_resp = self._make_mock_response(200)

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp):
            await http_request(
                "test_agent",
                "http://example.com/app",
                session="my_session",
            )

        # Session should have been created
        key = _session_key("test_agent", "my_session")
        assert key in _sessions

    @pytest.mark.asyncio
    async def test_http_request_with_form_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """http_request sends form_body as form-encoded data."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        mock_resp = self._make_mock_response(200)

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp) as mock_safe:
            await http_request(
                "test_agent",
                "http://example.com/app",
                method="POST",
                form_body={"field": "value"},
            )

        call_kwargs = mock_safe.call_args.kwargs
        assert call_kwargs.get("data") == {"field": "value"}

    @pytest.mark.asyncio
    async def test_http_request_with_raw_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """http_request sends raw_body as content."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        mock_resp = self._make_mock_response(200)

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp) as mock_safe:
            await http_request(
                "test_agent",
                "http://example.com/app",
                method="POST",
                raw_body="raw content",
            )

        call_kwargs = mock_safe.call_args.kwargs
        assert call_kwargs.get("content") == "raw content"


class TestHttpSessionLoginTool:
    """Tests for the http_session_login MCP tool function."""

    def setup_method(self) -> None:
        _sessions.clear()

    @pytest.mark.asyncio
    async def test_http_session_login_redacts_credentials_in_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_session_login redacts sensitive credential values in the returned dict."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        mock_resp = _make_response(200, "http://example.com/app/login", content=b'{"ok": true}')
        mock_resp.history = []  # type: ignore[attr-defined]

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp):
            result = await http_session_login(
                "test_agent",
                "http://example.com/app/login",
                credentials={"username": "admin", "password": "s3cret"},
            )

        credentials_sent = result["credentials_sent"]
        assert credentials_sent["username"] == "admin"
        assert credentials_sent["password"] == "[REDACTED]"

    @pytest.mark.asyncio
    async def test_http_session_login_redacts_token_in_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_session_login redacts token fields in the credentials_sent response."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        mock_resp = _make_response(200, "http://example.com/app/login", content=b"ok")
        mock_resp.history = []  # type: ignore[attr-defined]

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp):
            result = await http_session_login(
                "test_agent",
                "http://example.com/app/login",
                credentials={"api_key": "secret-key-value", "client_id": "app123"},
            )

        credentials_sent = result["credentials_sent"]
        assert credentials_sent["api_key"] == "[REDACTED]"
        assert credentials_sent["client_id"] == "app123"

    @pytest.mark.asyncio
    async def test_http_session_login_stores_session_info(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_session_login returns session_name and status in response."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        mock_resp = _make_response(200, "http://example.com/app/login", content=b'{"ok": true}')
        mock_resp.history = []  # type: ignore[attr-defined]

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp):
            result = await http_session_login(
                "test_agent",
                "http://example.com/app/login",
                credentials={"username": "admin", "password": "s3cret"},
                session="mylogin",
            )

        assert result["session_name"] == "mylogin"
        assert result["status"] == 200
        assert "body_snippet" in result

    @pytest.mark.asyncio
    async def test_http_session_login_blocked_when_no_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_session_login is blocked when REDTEAM_ALLOWED_TARGETS is not set."""
        monkeypatch.delenv("REDTEAM_ALLOWED_TARGETS", raising=False)
        with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
            await http_session_login(
                "test_agent",
                "http://example.com/login",
                credentials={"username": "user", "password": "pass"},
            )

    @pytest.mark.asyncio
    async def test_http_session_login_with_form_encoding(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_session_login with content_type='form' sends form-encoded credentials."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        mock_resp = _make_response(200, "http://example.com/app/login", content=b"ok")
        mock_resp.history = []  # type: ignore[attr-defined]

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp) as mock_safe:
            await http_session_login(
                "test_agent",
                "http://example.com/app/login",
                credentials={"username": "user", "password": "pass"},
                content_type="form",
            )

        call_kwargs = mock_safe.call_args.kwargs
        assert "data" in call_kwargs
        assert "json" not in call_kwargs

    @pytest.mark.asyncio
    async def test_http_session_login_with_json_encoding_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_session_login defaults to JSON-encoded credentials."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        mock_resp = _make_response(200, "http://example.com/app/login", content=b"ok")
        mock_resp.history = []  # type: ignore[attr-defined]

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp) as mock_safe:
            await http_session_login(
                "test_agent",
                "http://example.com/app/login",
                credentials={"username": "user", "password": "pass"},
            )

        call_kwargs = mock_safe.call_args.kwargs
        assert "json" in call_kwargs
        assert "data" not in call_kwargs


class TestHttpUploadFileTool:
    """Tests for the http_upload_file MCP tool function."""

    def setup_method(self) -> None:
        _sessions.clear()

    @pytest.mark.asyncio
    async def test_http_upload_file_blocked_when_no_allowlist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_upload_file is blocked when REDTEAM_ALLOWED_TARGETS is not set."""
        monkeypatch.delenv("REDTEAM_ALLOWED_TARGETS", raising=False)
        content_b64 = base64.b64encode(b"file content").decode()
        with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
            await http_upload_file(
                "test_agent",
                "http://example.com/upload",
                file_content_base64=content_b64,
                filename="test.txt",
            )

    @pytest.mark.asyncio
    async def test_http_upload_file_blocked_for_disallowed_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_upload_file raises ValueError for URLs outside the allowlist."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        content_b64 = base64.b64encode(b"file content").decode()
        with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
            await http_upload_file(
                "test_agent",
                "http://evil.com/upload",
                file_content_base64=content_b64,
                filename="test.txt",
            )

    @pytest.mark.asyncio
    async def test_http_upload_file_rejects_invalid_base64(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_upload_file raises ValueError for invalid base64 content."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        with pytest.raises(ValueError, match="Invalid base64 content"):
            await http_upload_file(
                "test_agent",
                "http://example.com/app/upload",
                file_content_base64="not-valid-base64!!!",
                filename="test.txt",
            )

    @pytest.mark.asyncio
    async def test_http_upload_file_rejects_empty_filename(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_upload_file raises ValueError when filename is empty."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        content_b64 = base64.b64encode(b"data").decode()
        with pytest.raises(ValueError, match="Filename cannot be empty"):
            await http_upload_file(
                "test_agent",
                "http://example.com/app/upload",
                file_content_base64=content_b64,
                filename="",
            )

    @pytest.mark.asyncio
    async def test_http_upload_file_rejects_too_long_filename(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_upload_file raises ValueError when filename exceeds 255 chars."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        content_b64 = base64.b64encode(b"data").decode()
        with pytest.raises(ValueError, match="Filename too long"):
            await http_upload_file(
                "test_agent",
                "http://example.com/app/upload",
                file_content_base64=content_b64,
                filename="a" * 256,
            )

    @pytest.mark.asyncio
    async def test_http_upload_file_succeeds_for_allowed_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_upload_file succeeds and returns expected fields for an allowed URL."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        content_b64 = base64.b64encode(b"file content").decode()
        mock_resp = _make_response(
            200,
            "http://example.com/app/upload",
            content=b'{"uploaded": true}',
        )
        mock_resp.history = []  # type: ignore[attr-defined]

        with patch(_SAFE_REQUEST_PATCH, return_value=mock_resp):
            result = await http_upload_file(
                "test_agent",
                "http://example.com/app/upload",
                file_content_base64=content_b64,
                filename="test.txt",
            )

        assert result["status"] == 200
        assert "body" in result
        assert "elapsed_seconds" in result

    @pytest.mark.asyncio
    async def test_http_upload_file_rejects_oversized_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_upload_file raises ValueError for files exceeding 10 MB."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        # Create content slightly over 10 MB
        oversized_content = b"x" * (10 * 1024 * 1024 + 1)
        content_b64 = base64.b64encode(oversized_content).decode()
        with pytest.raises(ValueError, match="File too large"):
            await http_upload_file(
                "test_agent",
                "http://example.com/app/upload",
                file_content_base64=content_b64,
                filename="big.bin",
            )

    @pytest.mark.asyncio
    async def test_http_upload_file_strips_null_bytes_from_filename(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """http_upload_file strips null bytes from filename before validation."""
        monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://example.com/app")
        content_b64 = base64.b64encode(b"data").decode()
        # A filename that is only null bytes should become empty and fail the empty check
        with pytest.raises(ValueError, match="Filename cannot be empty"):
            await http_upload_file(
                "test_agent",
                "http://example.com/app/upload",
                file_content_base64=content_b64,
                filename="\x00",
            )


# ---------------------------------------------------------------------------
# Additional security edge case tests
# ---------------------------------------------------------------------------


class TestCheckTargetAllowedUrlEncodedTraversal:
    """URL-encoded path traversal edge cases.

    Note: _check_target_allowed uses posixpath.normpath which is NOT percent-aware.
    These tests document the current behavior — including the known gap where
    %2e%2e (URL-encoded dots) is not decoded before normpath is applied.
    This is documented here to make the behavior explicit and to flag it for
    future hardening.
    """

    def test_check_target_allowed_blocks_literal_dot_dot_traversal(self) -> None:
        """Literal ../.. traversal is blocked after posixpath.normpath normalizes it."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api/../admin")

    def test_check_target_allowed_url_encoded_traversal_documents_current_behavior(
        self,
    ) -> None:
        """Documents that %2e%2e is NOT decoded before normpath — check passes for encoded dots.

        This test exists to make explicit the known behavior gap: posixpath.normpath
        does not decode percent-encoded characters, so '/api/%2e%2e/admin' normalizes
        to '/api/%2e%2e/admin' (not '/admin'). The allowlist check therefore allows
        the request if the path starts with '/api/'.

        This is a documentation test for a known security consideration. The production
        code should be hardened by URL-decoding paths before normpath if encoded traversal
        is a concern.
        """
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            # The encoded %2e%2e is NOT treated as '..', so the path starts with /api/
            # and the check passes. This documents the current behavior, not an ideal.
            _check_target_allowed("http://example.com/api/%2e%2e/admin")  # currently allowed


class TestSafeRequestAdditionalCoverage:
    """Additional _safe_request tests for edge cases raised in code review."""

    @pytest.mark.asyncio
    async def test_safe_request_too_many_redirects_raises(self) -> None:
        """Exceeding _MAX_REDIRECTS raises httpx.TooManyRedirects."""
        from agent_framework.tools.http_client import _MAX_REDIRECTS

        loop_resp = _make_response(
            302,
            "http://example.com/app/loop",
            headers={"location": "http://example.com/app/loop"},
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=loop_resp)

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            with pytest.raises(httpx.TooManyRedirects, match=f"Exceeded {_MAX_REDIRECTS}"):
                await _safe_request(client, "GET", "http://example.com/app/loop")

        # Verify the client was called exactly _MAX_REDIRECTS times
        assert client.request.call_count == _MAX_REDIRECTS

    @pytest.mark.asyncio
    async def test_safe_request_follow_redirects_false_returns_redirect_directly(self) -> None:
        """When follow_redirects=False, a redirect response is returned without following."""
        redirect_resp = _make_response(
            302,
            "http://example.com/app/old",
            headers={"location": "http://example.com/app/new"},
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        resp = await _safe_request(
            client, "GET", "http://example.com/app/old", follow_redirects=False
        )

        assert resp.status_code == 302
        # Only one request made — the redirect is NOT followed
        client.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_safe_request_post_303_converts_to_get_and_strips_body(self) -> None:
        """POST → 303 → converts method to GET and strips the request body.

        This is security-relevant: a POST with credentials that receives a 303 redirect
        should not re-submit the body to the redirect target.
        """
        redirect_resp = _make_response(
            303,
            "http://example.com/app/submit",
            headers={"location": "http://example.com/app/result"},
        )
        final_resp = _make_response(200, "http://example.com/app/result", content=b"ok")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(
                client,
                "POST",
                "http://example.com/app/submit",
                json={"username": "admin", "password": "s3cret"},
            )

        assert resp.status_code == 200
        second_call = client.request.call_args_list[1]
        # Method must be GET after 303
        assert second_call.args[0] == "GET"
        # Body kwargs must be stripped
        second_kwargs = second_call.kwargs
        assert "json" not in second_kwargs
        assert "content" not in second_kwargs
        assert "data" not in second_kwargs
