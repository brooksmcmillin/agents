"""Tests for HTTP client security: credential redaction, session isolation, target allowlist."""

import os
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agent_framework.tools.http_client import (
    _MAX_REDIRECTS,
    _check_target_allowed,
    _get_session,
    _redact_sensitive,
    _safe_request,
    _session_key,
    _sessions,
    http_clear_session,
)


class TestCredentialRedaction:
    """Ensure sensitive fields are redacted regardless of casing/format."""

    def test_redacts_password(self) -> None:
        result = _redact_sensitive({"password": "s3cret"})
        assert result["password"] == "[REDACTED]"

    def test_redacts_api_key_case_insensitive(self) -> None:
        result = _redact_sensitive({"API_KEY": "abc123"})
        assert result["API_KEY"] == "[REDACTED]"

    def test_redacts_hyphenated_headers(self) -> None:
        """api-key, x-auth-token, etc. should be normalised and redacted."""
        result = _redact_sensitive({"Api-Key": "xyz", "X-Auth-Token": "tok"})
        assert result["Api-Key"] == "[REDACTED]"
        assert result["X-Auth-Token"] == "[REDACTED]"

    def test_redacts_authorization(self) -> None:
        result = _redact_sensitive({"Authorization": "Bearer abc"})
        assert result["Authorization"] == "[REDACTED]"

    def test_redacts_cookie_and_set_cookie(self) -> None:
        result = _redact_sensitive({"Cookie": "sid=abc", "Set-Cookie": "sid=def"})
        assert result["Cookie"] == "[REDACTED]"
        assert result["Set-Cookie"] == "[REDACTED]"

    def test_preserves_non_sensitive_fields(self) -> None:
        result = _redact_sensitive({"Content-Type": "application/json", "Accept": "text/html"})
        assert result["Content-Type"] == "application/json"
        assert result["Accept"] == "text/html"

    def test_mixed_sensitive_and_safe(self) -> None:
        data = {"username": "admin", "password": "s3cret", "remember": "true"}
        result = _redact_sensitive(data)
        assert result["username"] == "admin"
        assert result["password"] == "[REDACTED]"
        assert result["remember"] == "true"

    def test_empty_dict(self) -> None:
        assert _redact_sensitive({}) == {}

    def test_all_sensitive_fields(self) -> None:
        """Ensure every field in _SENSITIVE_FIELDS is actually redacted."""
        from agent_framework.tools.http_client import _SENSITIVE_FIELDS

        for field in _SENSITIVE_FIELDS:
            result = _redact_sensitive({field: "value"})
            assert result[field] == "[REDACTED]", f"Field {field!r} was not redacted"


class TestTargetAllowlist:
    """Ensure requests outside the allowlist are rejected."""

    def test_rejects_when_env_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("REDTEAM_ALLOWED_TARGETS", None)
            with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
                _check_target_allowed("http://example.com")

    def test_allows_exact_match(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com"}):
            _check_target_allowed("http://example.com/")  # should not raise

    def test_allows_subpath(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            _check_target_allowed("http://example.com/api/users")

    def test_rejects_different_host(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://evil.com/api")

    def test_rejects_subdomain_bypass(self) -> None:
        """Subdomain evil.example.com should not match example.com."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://evil.example.com/api")

    def test_rejects_scheme_mismatch(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "https://example.com"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api")

    def test_rejects_port_mismatch(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com:8080"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com:9090/api")

    def test_rejects_path_prefix_confusion(self) -> None:
        """'/api/v1' should NOT match '/api/v1admin' (boundary check)."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api/v1"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api/v1admin")

    def test_rejects_path_traversal(self) -> None:
        """/api/../admin should normalize and fail."""
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/api"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                _check_target_allowed("http://example.com/api/../admin")

    def test_rejects_invalid_url(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com"}):
            with pytest.raises(ValueError, match="Invalid URL"):
                _check_target_allowed("not-a-url")

    def test_multiple_allowed_targets(self) -> None:
        targets = "http://a.com/app, https://b.com/api"
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": targets}):
            _check_target_allowed("http://a.com/app/page")
            _check_target_allowed("https://b.com/api/v1")
            with pytest.raises(ValueError):
                _check_target_allowed("http://c.com")


class TestSessionIsolation:
    """Ensure sessions are scoped per agent and expire properly."""

    def setup_method(self) -> None:
        _sessions.clear()

    def test_sessions_scoped_by_agent_name(self) -> None:
        sess_a = _get_session("agent_a", "default")
        sess_b = _get_session("agent_b", "default")
        sess_a["cookies"]["sid"] = "aaa"
        assert "sid" not in sess_b.get("cookies", {})

    def test_session_key_format(self) -> None:
        assert _session_key("agent_a", "mysession") == "agent_a:mysession"

    def test_separate_named_sessions(self) -> None:
        sess1 = _get_session("agent_a", "session1")
        sess2 = _get_session("agent_a", "session2")
        sess1["cookies"]["a"] = "1"
        assert "a" not in sess2.get("cookies", {})

    @pytest.mark.asyncio
    async def test_clear_session(self) -> None:
        _get_session("agent_a", "default")
        result = await http_clear_session("agent_a", "default")
        assert result["cleared"] is True

    @pytest.mark.asyncio
    async def test_clear_nonexistent_session(self) -> None:
        result = await http_clear_session("agent_a", "nonexistent")
        assert result["cleared"] is False

    def test_session_expiry(self) -> None:
        from agent_framework.tools.http_client import _SESSION_TTL_SECONDS, _expire_sessions

        sess = _get_session("agent_a", "default")
        sess["last_used"] = time.monotonic() - _SESSION_TTL_SECONDS - 1
        _expire_sessions()
        key = _session_key("agent_a", "default")
        assert key not in _sessions

    def test_fresh_session_not_expired(self) -> None:
        from agent_framework.tools.http_client import _expire_sessions

        _get_session("agent_a", "default")
        _expire_sessions()
        key = _session_key("agent_a", "default")
        assert key in _sessions


# ---------------------------------------------------------------------------
# Helpers for redirect chain tests
# ---------------------------------------------------------------------------


def _make_response(
    status_code: int,
    url: str,
    headers: dict[str, str] | None = None,
    content: bytes = b"",
) -> httpx.Response:
    """Build a real httpx.Response for use in mocked client.request()."""
    resp = httpx.Response(
        status_code=status_code,
        headers=headers or {},
        content=content,
        request=httpx.Request("GET", url),
    )
    return resp


def _allow_all_targets(url: str) -> None:
    """No-op replacement for _check_target_allowed used in redirect-mechanics tests."""
    pass


# Path used to patch the allowlist check inside the http_client module.
_ALLOWLIST_PATCH = "agent_framework.tools.http_client._check_target_allowed"


class TestSafeRequestRedirectChain:
    """Tests for _safe_request redirect-following with SSRF validation.

    Tests that focus on redirect *mechanics* (history, method changes, body
    stripping) patch out _check_target_allowed to avoid coupling to allowlist
    path matching.  Tests that verify SSRF *blocking* on redirect hops use
    the real allowlist function.
    """

    async def test_no_redirect_returns_immediately(self) -> None:
        """Non-redirect response is returned as-is with empty history."""
        client = AsyncMock(spec=httpx.AsyncClient)
        final = _make_response(200, "http://a.com/page", content=b"ok")
        client.request = AsyncMock(return_value=final)

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "GET", "http://a.com/page")

        assert resp.status_code == 200
        assert resp.history == []

    async def test_follows_single_redirect(self) -> None:
        """A single 302 redirect is followed and history is populated."""
        redirect_resp = _make_response(
            302,
            "http://a.com/old",
            headers={"location": "http://a.com/new"},
        )
        final_resp = _make_response(200, "http://a.com/new", content=b"done")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "GET", "http://a.com/old")

        assert resp.status_code == 200
        assert len(resp.history) == 1
        assert resp.history[0].status_code == 302

    async def test_follows_multi_hop_redirect_chain(self) -> None:
        """A chain of 3 redirects (301 -> 302 -> 200) is followed correctly."""
        r1 = _make_response(301, "http://a.com/1", headers={"location": "http://a.com/2"})
        r2 = _make_response(302, "http://a.com/2", headers={"location": "http://a.com/3"})
        r3 = _make_response(200, "http://a.com/3", content=b"final")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[r1, r2, r3])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "GET", "http://a.com/1")

        assert resp.status_code == 200
        assert len(resp.history) == 2
        assert resp.history[0].status_code == 301
        assert resp.history[1].status_code == 302

    async def test_redirect_to_disallowed_host_blocked(self) -> None:
        """Redirect to a host outside the allowlist raises ValueError (SSRF prevention).

        Uses the real _check_target_allowed to verify SSRF protection.
        """
        redirect_resp = _make_response(
            302,
            "http://allowed.com/start",
            headers={"location": "http://evil.internal/admin"},
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://allowed.com"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await _safe_request(client, "GET", "http://allowed.com/start")

    async def test_second_hop_to_disallowed_host_blocked(self) -> None:
        """First redirect is allowed, but second hop to evil host is blocked.

        Uses the real _check_target_allowed. Both hops stay on allowed.com
        except the second Location which points to internal.corp.
        """
        r1 = _make_response(
            302,
            "http://allowed.com/app/a",
            headers={"location": "http://allowed.com/app/b"},
        )
        r2 = _make_response(
            302,
            "http://allowed.com/app/b",
            headers={"location": "http://internal.corp/secret"},
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[r1, r2])

        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://allowed.com/app"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await _safe_request(client, "GET", "http://allowed.com/app/a")

    async def test_too_many_redirects_raises(self) -> None:
        """Exceeding _MAX_REDIRECTS raises httpx.TooManyRedirects."""

        def make_redirect(n: int) -> httpx.Response:
            return _make_response(
                302,
                f"http://a.com/r/{n}",
                headers={"location": f"http://a.com/r/{n + 1}"},
            )

        responses = [make_redirect(i) for i in range(_MAX_REDIRECTS)]

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=responses)

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            with pytest.raises(httpx.TooManyRedirects, match=f"Exceeded {_MAX_REDIRECTS}"):
                await _safe_request(client, "GET", "http://a.com/r/0")

    async def test_missing_location_header_stops_redirect(self) -> None:
        """A 302 without a Location header returns that response instead of looping."""
        resp_no_loc = _make_response(302, "http://a.com/no-loc")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=resp_no_loc)

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "GET", "http://a.com/no-loc")

        assert resp.status_code == 302
        assert resp.history == []

    async def test_follow_redirects_false_skips_chain(self) -> None:
        """When follow_redirects=False, the redirect is returned without following."""
        redirect_resp = _make_response(
            302,
            "http://a.com/old",
            headers={"location": "http://a.com/new"},
        )

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        resp = await _safe_request(client, "GET", "http://a.com/old", follow_redirects=False)

        assert resp.status_code == 302
        # client.request called directly, no redirect following
        client.request.assert_called_once()

    async def test_303_changes_method_to_get(self) -> None:
        """A 303 response should change the method to GET for the next request."""
        redirect_resp = _make_response(
            303,
            "http://a.com/submit",
            headers={"location": "http://a.com/result"},
        )
        final_resp = _make_response(200, "http://a.com/result", content=b"ok")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(
                client, "POST", "http://a.com/submit", json={"data": "value"}
            )

        assert resp.status_code == 200
        # Second call should be GET (method changed from POST)
        second_call = client.request.call_args_list[1]
        assert second_call[0][0] == "GET"

    async def test_301_post_changes_method_to_get(self) -> None:
        """A 301 with POST should change method to GET (browser behavior)."""
        redirect_resp = _make_response(
            301,
            "http://a.com/old",
            headers={"location": "http://a.com/new"},
        )
        final_resp = _make_response(200, "http://a.com/new", content=b"ok")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "POST", "http://a.com/old", content=b"body")

        assert resp.status_code == 200
        second_call = client.request.call_args_list[1]
        assert second_call[0][0] == "GET"

    async def test_302_post_changes_method_to_get(self) -> None:
        """A 302 with POST should change method to GET (browser behavior)."""
        redirect_resp = _make_response(
            302,
            "http://a.com/old",
            headers={"location": "http://a.com/new"},
        )
        final_resp = _make_response(200, "http://a.com/new", content=b"ok")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "POST", "http://a.com/old", data={"key": "val"})

        assert resp.status_code == 200
        second_call = client.request.call_args_list[1]
        assert second_call[0][0] == "GET"

    async def test_307_preserves_method(self) -> None:
        """A 307 redirect should preserve the original HTTP method."""
        redirect_resp = _make_response(
            307,
            "http://a.com/old",
            headers={"location": "http://a.com/new"},
        )
        final_resp = _make_response(200, "http://a.com/new", content=b"ok")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "POST", "http://a.com/old", json={"k": "v"})

        assert resp.status_code == 200
        second_call = client.request.call_args_list[1]
        assert second_call[0][0] == "POST"

    async def test_308_preserves_method(self) -> None:
        """A 308 redirect should preserve the original HTTP method."""
        redirect_resp = _make_response(
            308,
            "http://a.com/old",
            headers={"location": "http://a.com/new"},
        )
        final_resp = _make_response(200, "http://a.com/new", content=b"ok")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "PUT", "http://a.com/old", content=b"body")

        assert resp.status_code == 200
        second_call = client.request.call_args_list[1]
        assert second_call[0][0] == "PUT"

    async def test_303_strips_body_kwargs(self) -> None:
        """On method downgrade (303), content/json/data kwargs are removed."""
        redirect_resp = _make_response(
            303,
            "http://a.com/submit",
            headers={"location": "http://a.com/result"},
        )
        final_resp = _make_response(200, "http://a.com/result", content=b"ok")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            await _safe_request(
                client,
                "POST",
                "http://a.com/submit",
                content=b"post-body",
                json={"a": 1},
                data={"b": 2},
            )

        second_call_kwargs = client.request.call_args_list[1][1]
        assert "content" not in second_call_kwargs
        assert "json" not in second_call_kwargs
        assert "data" not in second_call_kwargs

    async def test_303_strips_files_kwarg(self) -> None:
        """On method downgrade (303), files kwarg is also removed to prevent data exfiltration."""
        redirect_resp = _make_response(
            303,
            "http://a.com/upload",
            headers={"location": "http://a.com/result"},
        )
        final_resp = _make_response(200, "http://a.com/result", content=b"ok")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            await _safe_request(
                client,
                "POST",
                "http://a.com/upload",
                files={"file": ("test.txt", b"secret-data")},
            )

        second_call_kwargs = client.request.call_args_list[1][1]
        assert "files" not in second_call_kwargs

    async def test_301_get_preserves_method(self) -> None:
        """A 301 with GET should keep GET (only POST triggers method change)."""
        redirect_resp = _make_response(
            301,
            "http://a.com/old",
            headers={"location": "http://a.com/new"},
        )
        final_resp = _make_response(200, "http://a.com/new", content=b"ok")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
            resp = await _safe_request(client, "GET", "http://a.com/old")

        assert resp.status_code == 200
        second_call = client.request.call_args_list[1]
        assert second_call[0][0] == "GET"

    async def test_all_redirect_status_codes_followed(self) -> None:
        """Status codes 301, 302, 303, 307, 308 all trigger redirect following."""
        for code in (301, 302, 303, 307, 308):
            redirect_resp = _make_response(
                code,
                "http://a.com/start",
                headers={"location": "http://a.com/end"},
            )
            final_resp = _make_response(200, "http://a.com/end", content=b"ok")

            client = AsyncMock(spec=httpx.AsyncClient)
            client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

            with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
                resp = await _safe_request(client, "GET", "http://a.com/start")

            assert resp.status_code == 200, f"Failed for status code {code}"
            assert len(resp.history) == 1, f"History wrong for status code {code}"

    async def test_non_redirect_status_codes_not_followed(self) -> None:
        """4xx and 5xx codes with a Location header should NOT be followed."""
        for code in (400, 401, 403, 404, 500):
            resp_with_loc = _make_response(
                code,
                "http://a.com/page",
                headers={"location": "http://a.com/other"},
            )

            client = AsyncMock(spec=httpx.AsyncClient)
            client.request = AsyncMock(return_value=resp_with_loc)

            with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets):
                resp = await _safe_request(client, "GET", "http://a.com/page")

            assert resp.status_code == code
            assert resp.history == []
            client.request.assert_called_once()

    async def test_allowlist_called_for_each_redirect_hop(self) -> None:
        """_check_target_allowed is called once per redirect hop."""
        r1 = _make_response(302, "http://a.com/1", headers={"location": "http://a.com/2"})
        r2 = _make_response(302, "http://a.com/2", headers={"location": "http://a.com/3"})
        r3 = _make_response(200, "http://a.com/3", content=b"done")

        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[r1, r2, r3])

        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all_targets) as mock_check:
            await _safe_request(client, "GET", "http://a.com/1")

        # Called once for http://a.com/2 and once for http://a.com/3
        assert mock_check.call_count == 2
        called_urls = [call.args[0] for call in mock_check.call_args_list]
        assert "http://a.com/2" in called_urls
        assert "http://a.com/3" in called_urls


class TestRedactSensitiveExtended:
    """Extended tests for _redact_sensitive credential leakage prevention."""

    def test_non_string_values_are_stringified(self) -> None:
        """Non-string values should be converted to str for non-sensitive fields."""
        result = _redact_sensitive({"count": 42, "active": True, "items": [1, 2]})
        assert result["count"] == "42"
        assert result["active"] == "True"
        assert result["items"] == "[1, 2]"

    def test_non_string_sensitive_values_are_redacted_not_stringified(self) -> None:
        """Sensitive fields with non-string values should still be redacted."""
        result = _redact_sensitive({"token": 12345, "password": None})
        assert result["token"] == "[REDACTED]"
        assert result["password"] == "[REDACTED]"

    def test_preserves_original_key_casing(self) -> None:
        """Original key casing is preserved in the output, even when value is redacted."""
        result = _redact_sensitive({"API-KEY": "secret", "Content-Type": "text/html"})
        assert "API-KEY" in result
        assert "Content-Type" in result
        assert "api_key" not in result
        assert "api-key" not in result

    def test_mixed_hyphen_underscore_normalization(self) -> None:
        """Both 'set-cookie' and 'set_cookie' should match the sensitive list."""
        result_hyphen = _redact_sensitive({"set-cookie": "sid=abc"})
        result_underscore = _redact_sensitive({"set_cookie": "sid=abc"})
        assert result_hyphen["set-cookie"] == "[REDACTED]"
        assert result_underscore["set_cookie"] == "[REDACTED]"

    def test_partial_field_name_not_redacted(self) -> None:
        """Fields that partially match (e.g. 'passwords') should NOT be redacted."""
        result = _redact_sensitive(
            {
                "passwords": "list_of_passwords",
                "my_token_field": "some_value",
                "tokens_count": "5",
            }
        )
        assert result["passwords"] == "list_of_passwords"
        assert result["my_token_field"] == "some_value"
        assert result["tokens_count"] == "5"

    def test_empty_string_value_preserved(self) -> None:
        """Empty string values on non-sensitive fields are preserved."""
        result = _redact_sensitive({"username": "", "password": ""})
        assert result["username"] == ""
        assert result["password"] == "[REDACTED]"

    def test_sensitive_with_mixed_case_variations(self) -> None:
        """Various mixed-case forms of sensitive fields are redacted."""
        result = _redact_sensitive(
            {
                "ACCESS_TOKEN": "tok1",
                "access-token": "tok2",
                "Access-Token": "tok3",
                "ACCESS-TOKEN": "tok4",
            }
        )
        for key in ("ACCESS_TOKEN", "access-token", "Access-Token", "ACCESS-TOKEN"):
            assert result[key] == "[REDACTED]", f"Key {key!r} was not redacted"

    def test_return_type_is_dict_str_str(self) -> None:
        """All values in the returned dict should be strings."""
        result = _redact_sensitive(
            {
                "password": "secret",
                "count": 42,
                "name": "test",
            }
        )
        for k, v in result.items():
            assert isinstance(v, str), f"Value for {k!r} is {type(v).__name__}, not str"
