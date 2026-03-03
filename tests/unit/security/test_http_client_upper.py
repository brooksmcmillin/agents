"""Tests for http_client.py upper tool functions.

Covers:
- _parse_cookie_header: Set-Cookie attribute parsing (HttpOnly, Secure, SameSite)
- _safe_read_response: truncation for oversized responses
- http_inspect_headers: security/CORS/cookie analysis
- http_fuzz_parameter: valid responses, error responses, exception handling
- http_check_rate_limit: rate limit detection and header capture
"""

import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from agent_framework.tools.http_client import (
    _MAX_RESPONSE_BYTES,
    _parse_cookie_header,
    _safe_read_response,
    http_check_rate_limit,
    http_fuzz_parameter,
    http_inspect_headers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALLOWLIST_PATCH = "agent_framework.tools.http_client._check_target_allowed"
_SAFE_REQUEST_PATCH = "agent_framework.tools.http_client._safe_request"

# BASE_URL must match a prefix in REDTEAM_ALLOWED_TARGETS for real-allowlist tests.
BASE_URL = "http://example.com/app"
AGENT = "test-agent"


def _allow_all(url: str) -> None:
    """No-op stub that allows all URLs."""
    pass


def _make_response(
    status_code: int,
    url: str = BASE_URL,
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


# ---------------------------------------------------------------------------
# _parse_cookie_header tests
# ---------------------------------------------------------------------------


class TestParseCookieHeader:
    """Tests for _parse_cookie_header attribute parsing."""

    def test_parses_httponly_attribute(self) -> None:
        result = _parse_cookie_header("session=abc123; HttpOnly")
        assert result["name"] == "session"
        assert result["httponly"] is True
        assert result["secure"] is False
        assert result["samesite"] is None

    def test_parses_secure_attribute(self) -> None:
        result = _parse_cookie_header("token=xyz; Secure")
        assert result["name"] == "token"
        assert result["secure"] is True
        assert result["httponly"] is False

    def test_parses_samesite_strict(self) -> None:
        result = _parse_cookie_header("sid=abc; SameSite=Strict")
        assert result["samesite"] == "strict"

    def test_parses_samesite_lax(self) -> None:
        result = _parse_cookie_header("sid=abc; SameSite=Lax")
        assert result["samesite"] == "lax"

    def test_parses_samesite_none(self) -> None:
        result = _parse_cookie_header("sid=abc; SameSite=None")
        assert result["samesite"] == "none"

    def test_parses_all_security_attributes_together(self) -> None:
        result = _parse_cookie_header("session=abc; HttpOnly; Secure; SameSite=Strict")
        assert result["name"] == "session"
        assert result["httponly"] is True
        assert result["secure"] is True
        assert result["samesite"] == "strict"

    def test_parses_cookie_name_with_value(self) -> None:
        result = _parse_cookie_header("PHPSESSID=abc123def456")
        assert result["name"] == "PHPSESSID"

    def test_preserves_raw_header(self) -> None:
        raw = "session=abc; HttpOnly; Secure; SameSite=Lax"
        result = _parse_cookie_header(raw)
        assert result["raw"] == raw

    def test_no_security_attributes(self) -> None:
        """Cookie without any security attributes."""
        result = _parse_cookie_header("tracking=xyz; Path=/; Domain=example.com")
        assert result["name"] == "tracking"
        assert result["httponly"] is False
        assert result["secure"] is False
        assert result["samesite"] is None

    def test_handles_malformed_no_value(self) -> None:
        """Cookie with no '=' sign in name-value part uses whole string as name."""
        result = _parse_cookie_header("barecookie; HttpOnly")
        assert result["name"] == "barecookie"
        assert result["httponly"] is True

    def test_handles_empty_string(self) -> None:
        """Empty cookie header should not raise."""
        result = _parse_cookie_header("")
        assert result["name"] == "unknown"
        assert result["httponly"] is False
        assert result["secure"] is False
        assert result["samesite"] is None

    def test_case_insensitive_attribute_matching(self) -> None:
        """Attribute names are matched case-insensitively."""
        result = _parse_cookie_header("sid=abc; httponly; SECURE; samesite=Lax")
        assert result["httponly"] is True
        assert result["secure"] is True
        assert result["samesite"] == "lax"

    def test_httponly_substring_does_not_match_other_attrs(self) -> None:
        """An attribute like 'notHttpOnly' should not match HttpOnly."""
        result = _parse_cookie_header("sid=abc; notHttpOnly")
        assert result["httponly"] is False

    def test_secure_substring_does_not_match_other_attrs(self) -> None:
        """An attribute like 'Insecure' should not match Secure."""
        result = _parse_cookie_header("sid=abc; Insecure")
        assert result["secure"] is False


# ---------------------------------------------------------------------------
# _safe_read_response tests
# ---------------------------------------------------------------------------


class TestSafeReadResponse:
    """Tests for _safe_read_response size guarding and truncation."""

    async def test_returns_full_body_when_under_max_len(self) -> None:
        resp = _make_response(200, content=b"Hello World")
        result = await _safe_read_response(resp, max_len=10000)
        assert result == "Hello World"

    async def test_truncates_text_exceeding_max_len(self) -> None:
        content = b"x" * 200
        resp = _make_response(200, content=content)
        result = await _safe_read_response(resp, max_len=100)
        assert result.startswith("x" * 100)
        assert "truncated" in result
        assert "200" in result  # total char count in message

    async def test_truncates_oversized_bytes_before_decode(self) -> None:
        """Responses exceeding _MAX_RESPONSE_BYTES trigger byte-level truncation."""
        oversized_content = b"A" * (_MAX_RESPONSE_BYTES + 1)
        resp = _make_response(200, content=oversized_content)
        result = await _safe_read_response(resp, max_len=10000)
        assert "truncated" in result
        total_bytes = _MAX_RESPONSE_BYTES + 1
        assert str(total_bytes) in result

    async def test_truncation_message_includes_original_byte_count(self) -> None:
        """Byte-level truncation message shows original byte count."""
        size = _MAX_RESPONSE_BYTES + 500
        resp = _make_response(200, content=b"B" * size)
        result = await _safe_read_response(resp, max_len=100)
        assert str(size) in result

    async def test_exact_max_len_returns_without_truncation_message(self) -> None:
        """Content exactly at max_len boundary is returned without truncation notice."""
        content = b"y" * 50
        resp = _make_response(200, content=content)
        result = await _safe_read_response(resp, max_len=50)
        assert result == "y" * 50
        assert "truncated" not in result


# ---------------------------------------------------------------------------
# http_inspect_headers tests
# ---------------------------------------------------------------------------


class TestHttpInspectHeaders:
    """Tests for http_inspect_headers tool function."""

    async def test_returns_security_headers_present(self) -> None:
        response_headers = {
            "content-security-policy": "default-src 'self'",
            "strict-transport-security": "max-age=31536000",
            "x-frame-options": "DENY",
            "x-content-type-options": "nosniff",
        }
        mock_resp = _make_response(200, headers=response_headers)

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_inspect_headers(AGENT, BASE_URL)

        sec = result["security_headers"]
        assert sec["content-security-policy"] == "default-src 'self'"
        assert sec["strict-transport-security"] == "max-age=31536000"
        assert sec["x-frame-options"] == "DENY"
        assert sec["x-content-type-options"] == "nosniff"

    async def test_returns_none_for_absent_security_headers(self) -> None:
        mock_resp = _make_response(200, headers={})

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_inspect_headers(AGENT, BASE_URL)

        sec = result["security_headers"]
        assert sec["content-security-policy"] is None
        assert sec["strict-transport-security"] is None
        assert sec["x-frame-options"] is None

    async def test_returns_cors_headers(self) -> None:
        response_headers = {
            "access-control-allow-origin": "*",
            "access-control-allow-methods": "GET, POST",
            "access-control-allow-credentials": "true",
        }
        mock_resp = _make_response(200, headers=response_headers)

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_inspect_headers(AGENT, BASE_URL)

        cors = result["cors_headers"]
        assert cors["access-control-allow-origin"] == "*"
        assert cors["access-control-allow-methods"] == "GET, POST"
        assert cors["access-control-allow-credentials"] == "true"

    async def test_parses_set_cookie_attributes(self) -> None:
        """Set-Cookie headers are parsed into structured cookie_analysis."""
        # httpx flattens multi-value headers; provide them via repeated headers
        # by building the response with a raw header list
        raw_headers = [
            (b"set-cookie", b"session=abc; HttpOnly; Secure; SameSite=Strict"),
            (b"set-cookie", b"tracker=xyz; SameSite=None"),
        ]
        mock_resp = httpx.Response(
            status_code=200,
            headers=raw_headers,
            content=b"",
            request=httpx.Request("GET", BASE_URL),
        )

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_inspect_headers(AGENT, BASE_URL)

        cookies = result["cookie_analysis"]
        assert len(cookies) == 2

        session_cookie = next(c for c in cookies if c["name"] == "session")
        assert session_cookie["httponly"] is True
        assert session_cookie["secure"] is True
        assert session_cookie["samesite"] == "strict"

        tracker_cookie = next(c for c in cookies if c["name"] == "tracker")
        assert tracker_cookie["httponly"] is False
        assert tracker_cookie["secure"] is False
        assert tracker_cookie["samesite"] == "none"

    async def test_empty_cookie_analysis_when_no_set_cookie(self) -> None:
        mock_resp = _make_response(200, headers={})

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_inspect_headers(AGENT, BASE_URL)

        assert result["cookie_analysis"] == []

    async def test_returns_status_code(self) -> None:
        mock_resp = _make_response(403, headers={})

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_inspect_headers(AGENT, BASE_URL)

        assert result["status"] == 403

    async def test_origin_header_passed_to_build_client(self) -> None:
        """When origin is provided, _build_client receives it in extra_headers."""
        mock_resp = _make_response(200, headers={"access-control-allow-origin": "https://evil.com"})
        captured_extra_headers: list[dict] = []

        original_build_client = __import__(
            "agent_framework.tools.http_client", fromlist=["_build_client"]
        )._build_client

        def capturing_build_client(
            agent_name: str,
            session_name: object = None,
            extra_headers: dict | None = None,
            extra_cookies: object = None,
            timeout: float = 30.0,
        ) -> object:
            captured_extra_headers.append(extra_headers or {})
            return original_build_client(
                agent_name=agent_name,
                session_name=session_name,
                extra_headers=extra_headers,
                extra_cookies=extra_cookies,
                timeout=timeout,
            )

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
            patch(
                "agent_framework.tools.http_client._build_client",
                side_effect=capturing_build_client,
            ),
        ):
            await http_inspect_headers(AGENT, BASE_URL, origin="https://evil.com")

        assert len(captured_extra_headers) == 1
        assert captured_extra_headers[0].get("Origin") == "https://evil.com"

    async def test_raises_on_disallowed_url(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://other.com/api"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await http_inspect_headers(AGENT, BASE_URL)

    async def test_raises_when_redteam_targets_not_set(self) -> None:
        """Fail-secure: denies all requests when REDTEAM_ALLOWED_TARGETS is not configured."""
        env = {k: v for k, v in os.environ.items() if k != "REDTEAM_ALLOWED_TARGETS"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
                await http_inspect_headers(AGENT, BASE_URL)

    async def test_real_allowlist_acceptance_path(self) -> None:
        """Real _check_target_allowed accepts BASE_URL when correctly configured."""
        mock_resp = _make_response(200, headers={})

        with (
            patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/app"}),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_inspect_headers(AGENT, BASE_URL)

        assert result["status"] == 200

    async def test_all_headers_included_in_result(self) -> None:
        """all_headers key should contain the full header dict."""
        mock_resp = _make_response(200, headers={"x-custom-header": "test-value"})

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_inspect_headers(AGENT, BASE_URL)

        assert "x-custom-header" in result["all_headers"]
        assert result["all_headers"]["x-custom-header"] == "test-value"


# ---------------------------------------------------------------------------
# http_fuzz_parameter tests
# ---------------------------------------------------------------------------


class TestHttpFuzzParameter:
    """Tests for http_fuzz_parameter tool function."""

    async def test_returns_results_for_each_payload(self) -> None:
        mock_resp = _make_response(200, content=b"OK")

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_fuzz_parameter(
                AGENT,
                BASE_URL,
                parameter="q",
                payloads=["' OR 1=1--", "<script>", "../etc/passwd"],
                delay_ms=0,
            )

        assert result["total_payloads"] == 3
        assert len(result["results"]) == 3
        for r in result["results"]:
            assert r["status"] == 200
            assert "payload" in r
            assert "elapsed_seconds" in r

    async def test_status_distribution_counts_correctly(self) -> None:
        responses = [
            _make_response(200, content=b"ok"),
            _make_response(500, content=b"error"),
            _make_response(200, content=b"ok"),
        ]

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(side_effect=responses)),
        ):
            result = await http_fuzz_parameter(
                AGENT,
                BASE_URL,
                parameter="id",
                payloads=["1", "2", "3"],
                delay_ms=0,
            )

        dist = result["status_distribution"]
        assert dist[200] == 2
        assert dist[500] == 1

    async def test_exception_branch_records_error(self) -> None:
        """When _safe_request raises, the exception is caught and recorded in results."""
        error = httpx.ConnectError("Connection refused")

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(side_effect=error)),
        ):
            result = await http_fuzz_parameter(
                AGENT,
                BASE_URL,
                parameter="q",
                payloads=["payload1"],
                delay_ms=0,
            )

        assert len(result["results"]) == 1
        r = result["results"][0]
        assert "error" in r
        assert "Connection refused" in r["error"]
        assert r["payload"] == "payload1"
        assert "elapsed_seconds" in r
        # No status key on error result
        assert "status" not in r

    async def test_error_counted_as_status_zero_in_distribution(self) -> None:
        """Exception results are recorded with status 0 in status_distribution."""
        error = httpx.TimeoutException("Timeout")

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(side_effect=error)),
        ):
            result = await http_fuzz_parameter(
                AGENT,
                BASE_URL,
                parameter="q",
                payloads=["x"],
                delay_ms=0,
            )

        dist = result["status_distribution"]
        assert dist.get(0, 0) == 1

    async def test_inject_in_body_json(self) -> None:
        mock_resp = _make_response(200, content=b"accepted")

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_fuzz_parameter(
                AGENT,
                BASE_URL,
                method="POST",
                parameter="username",
                payloads=["admin"],
                inject_in="body_json",
                delay_ms=0,
            )

        assert result["inject_in"] == "body_json"
        assert result["results"][0]["status"] == 200

    async def test_inject_in_body_form(self) -> None:
        mock_resp = _make_response(200, content=b"accepted")

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_fuzz_parameter(
                AGENT,
                BASE_URL,
                method="POST",
                parameter="field",
                payloads=["value"],
                inject_in="body_form",
                delay_ms=0,
            )

        assert result["inject_in"] == "body_form"
        assert result["results"][0]["status"] == 200

    async def test_empty_payloads_returns_empty_results(self) -> None:
        with patch(_ALLOWLIST_PATCH, side_effect=_allow_all):
            result = await http_fuzz_parameter(
                AGENT,
                BASE_URL,
                parameter="q",
                payloads=[],
                delay_ms=0,
            )

        assert result["total_payloads"] == 0
        assert result["results"] == []
        assert result["status_distribution"] == {}

    async def test_parameter_and_inject_in_in_result(self) -> None:
        mock_resp = _make_response(200, content=b"ok")

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_fuzz_parameter(
                AGENT,
                BASE_URL,
                parameter="search",
                payloads=["test"],
                inject_in="query",
                delay_ms=0,
            )

        assert result["parameter"] == "search"
        assert result["inject_in"] == "query"

    async def test_raises_on_disallowed_url(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://other.com/api"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await http_fuzz_parameter(
                    AGENT,
                    BASE_URL,
                    parameter="q",
                    payloads=["x"],
                    delay_ms=0,
                )

    async def test_raises_when_redteam_targets_not_set(self) -> None:
        """Fail-secure: denies all requests when REDTEAM_ALLOWED_TARGETS is not configured."""
        env = {k: v for k, v in os.environ.items() if k != "REDTEAM_ALLOWED_TARGETS"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
                await http_fuzz_parameter(
                    AGENT,
                    BASE_URL,
                    parameter="q",
                    payloads=["x"],
                    delay_ms=0,
                )

    async def test_real_allowlist_acceptance_path(self) -> None:
        """Real _check_target_allowed accepts BASE_URL when correctly configured."""
        mock_resp = _make_response(200, content=b"ok")

        with (
            patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/app"}),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_fuzz_parameter(
                AGENT,
                BASE_URL,
                parameter="q",
                payloads=["test"],
                delay_ms=0,
            )

        assert result["results"][0]["status"] == 200

    async def test_mixed_success_and_error_payloads(self) -> None:
        """Mix of successful responses and exceptions."""
        success_resp = _make_response(200, content=b"ok")
        error = httpx.ConnectError("refused")

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(side_effect=[success_resp, error])),
        ):
            result = await http_fuzz_parameter(
                AGENT,
                BASE_URL,
                parameter="q",
                payloads=["safe", "bad"],
                delay_ms=0,
            )

        assert len(result["results"]) == 2
        assert result["results"][0]["status"] == 200
        assert "error" in result["results"][1]


# ---------------------------------------------------------------------------
# http_check_rate_limit tests
# ---------------------------------------------------------------------------


class TestHttpCheckRateLimit:
    """Tests for http_check_rate_limit tool function."""

    async def test_sends_specified_number_of_requests(self) -> None:
        mock_resp = _make_response(200)

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=5)

        assert result["total_requests"] == 5
        assert len(result["results"]) == 5

    async def test_caps_num_requests_at_100(self) -> None:
        mock_resp = _make_response(200)

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=200)

        assert result["total_requests"] == 100
        assert len(result["results"]) == 100

    async def test_detects_first_429_response(self) -> None:
        """first_rate_limited_at is set to the request number of the first 429."""
        responses = [
            _make_response(200),
            _make_response(200),
            _make_response(429),
            _make_response(429),
        ]

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(side_effect=responses)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=4)

        assert result["first_rate_limited_at"] == 3

    async def test_first_rate_limited_is_none_when_no_429(self) -> None:
        mock_resp = _make_response(200)

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=3)

        assert result["first_rate_limited_at"] is None

    async def test_captures_rate_limit_headers(self) -> None:
        rl_headers = {
            "x-ratelimit-limit": "100",
            "x-ratelimit-remaining": "0",
            "retry-after": "60",
        }
        mock_resp = _make_response(429, headers=rl_headers)

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=1)

        rl = result["rate_limit_headers"]
        assert rl["x-ratelimit-limit"] == "100"
        assert rl["x-ratelimit-remaining"] == "0"
        assert rl["retry-after"] == "60"

    async def test_captures_ratelimit_headers_without_x_prefix(self) -> None:
        """ratelimit-limit/remaining/reset (no x- prefix) are also captured."""
        rl_headers = {
            "ratelimit-limit": "50",
            "ratelimit-remaining": "5",
            "ratelimit-reset": "1700000000",
        }
        mock_resp = _make_response(200, headers=rl_headers)

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=1)

        rl = result["rate_limit_headers"]
        assert rl["ratelimit-limit"] == "50"
        assert rl["ratelimit-remaining"] == "5"
        assert rl["ratelimit-reset"] == "1700000000"

    async def test_result_entries_include_request_number(self) -> None:
        mock_resp = _make_response(200)

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=3)

        numbers = [r["request_number"] for r in result["results"]]
        assert numbers == [1, 2, 3]

    async def test_rate_limited_flag_on_429_results(self) -> None:
        responses = [_make_response(200), _make_response(429)]

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(side_effect=responses)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=2)

        assert "rate_limited" not in result["results"][0]
        assert result["results"][1].get("rate_limited") is True

    async def test_exception_in_request_recorded_as_error(self) -> None:
        error = httpx.ConnectError("connection refused")

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(side_effect=error)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=1)

        assert len(result["results"]) == 1
        r = result["results"][0]
        assert "error" in r
        assert "connection refused" in r["error"]
        assert "elapsed_seconds" in r
        assert r["request_number"] == 1

    async def test_returns_url_and_method_in_result(self) -> None:
        mock_resp = _make_response(200)

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, method="POST", num_requests=1)

        assert result["url"] == BASE_URL
        assert result["method"] == "POST"

    async def test_raises_on_disallowed_url(self) -> None:
        with patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://other.com/api"}):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await http_check_rate_limit(AGENT, BASE_URL, num_requests=1)

    async def test_raises_when_redteam_targets_not_set(self) -> None:
        """Fail-secure: denies all requests when REDTEAM_ALLOWED_TARGETS is not configured."""
        env = {k: v for k, v in os.environ.items() if k != "REDTEAM_ALLOWED_TARGETS"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="REDTEAM_ALLOWED_TARGETS is not set"):
                await http_check_rate_limit(AGENT, BASE_URL, num_requests=1)

    async def test_real_allowlist_acceptance_path(self) -> None:
        """Real _check_target_allowed accepts BASE_URL when correctly configured."""
        mock_resp = _make_response(200)

        with (
            patch.dict(os.environ, {"REDTEAM_ALLOWED_TARGETS": "http://example.com/app"}),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=1)

        assert result["results"][0]["status"] == 200

    async def test_empty_rate_limit_headers_when_absent(self) -> None:
        mock_resp = _make_response(200, headers={})

        with (
            patch(_ALLOWLIST_PATCH, side_effect=_allow_all),
            patch(_SAFE_REQUEST_PATCH, new=AsyncMock(return_value=mock_resp)),
        ):
            result = await http_check_rate_limit(AGENT, BASE_URL, num_requests=1)

        assert result["rate_limit_headers"] == {}
