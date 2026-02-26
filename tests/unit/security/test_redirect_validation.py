"""Tests for _safe_request redirect validation in http_client.

The _safe_request function manually follows redirects while validating
each hop against the REDTEAM_ALLOWED_TARGETS allowlist. A bug here is
a direct SSRF vector — an attacker could use a 301 redirect from an
allowed host to reach an internal service.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from agent_framework.tools.http_client import _safe_request


def _mock_response(
    status_code: int = 200,
    headers: dict | None = None,
    url: str = "http://allowed.example.com/",
) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.url = httpx.URL(url)
    resp.history = []
    return resp


@pytest.fixture(autouse=True)
def _allow_example(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the allowlist for all tests in this module."""
    monkeypatch.setenv("REDTEAM_ALLOWED_TARGETS", "http://allowed.example.com")


def _allow_all(url: str) -> None:
    """Stub for _check_target_allowed that allows any URL on allowed.example.com."""
    parsed = httpx.URL(url)
    if parsed.host != "allowed.example.com":
        raise ValueError(f"URL {url!r} not in REDTEAM_ALLOWED_TARGETS")


class TestSafeRequestRedirectValidation:
    """Tests for redirect hop validation in _safe_request."""

    @pytest.mark.asyncio
    async def test_non_redirect_response_returned_directly(self) -> None:
        """A 200 response should be returned as-is."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_mock_response(200))

        with patch("agent_framework.tools.http_client._check_target_allowed"):
            resp = await _safe_request(client, "GET", "http://allowed.example.com/")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_redirect_to_allowed_host_is_followed(self) -> None:
        """A redirect staying within the allowlist should be followed."""
        redirect_resp = _mock_response(
            301,
            headers={"location": "http://allowed.example.com/new-page"},
            url="http://allowed.example.com/old-page",
        )
        final_resp = _mock_response(200, url="http://allowed.example.com/new-page")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(
            "agent_framework.tools.http_client._check_target_allowed",
            side_effect=_allow_all,
        ):
            resp = await _safe_request(client, "GET", "http://allowed.example.com/old-page")
        assert resp.status_code == 200
        assert client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_redirect_to_disallowed_host_is_blocked(self) -> None:
        """A redirect to a host outside the allowlist must raise ValueError."""
        redirect_resp = _mock_response(
            302,
            headers={"location": "http://internal.corp/secret"},
            url="http://allowed.example.com/",
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
            await _safe_request(client, "GET", "http://allowed.example.com/")

    @pytest.mark.asyncio
    async def test_redirect_to_localhost_is_blocked(self) -> None:
        """A redirect to localhost must be blocked."""
        redirect_resp = _mock_response(
            302,
            headers={"location": "http://localhost/admin"},
            url="http://allowed.example.com/",
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
            await _safe_request(client, "GET", "http://allowed.example.com/")

    @pytest.mark.asyncio
    async def test_redirect_to_private_ip_is_blocked(self) -> None:
        """A redirect to a private IP must be blocked."""
        redirect_resp = _mock_response(
            302,
            headers={"location": "http://192.168.1.1/router"},
            url="http://allowed.example.com/",
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
            await _safe_request(client, "GET", "http://allowed.example.com/")

    @pytest.mark.asyncio
    async def test_redirect_chain_validated_at_each_hop(self) -> None:
        """Each hop in a redirect chain must be validated.

        First hop redirects within allowed host (passes), second hop
        redirects to an evil host (must be blocked).
        """
        hop1 = _mock_response(
            301,
            headers={"location": "http://allowed.example.com/step2"},
            url="http://allowed.example.com/step1",
        )
        hop2 = _mock_response(
            302,
            headers={"location": "http://evil.com/steal"},
            url="http://allowed.example.com/step2",
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[hop1, hop2])

        with patch(
            "agent_framework.tools.http_client._check_target_allowed",
            side_effect=_allow_all,
        ):
            with pytest.raises(ValueError, match="not in REDTEAM_ALLOWED_TARGETS"):
                await _safe_request(client, "GET", "http://allowed.example.com/step1")

    @pytest.mark.asyncio
    async def test_too_many_redirects_raises(self) -> None:
        """Exceeding max redirects should raise TooManyRedirects."""
        redirect_resp = _mock_response(
            301,
            headers={"location": "http://allowed.example.com/loop"},
            url="http://allowed.example.com/loop",
        )
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=redirect_resp)

        with patch(
            "agent_framework.tools.http_client._check_target_allowed",
            side_effect=_allow_all,
        ):
            with pytest.raises(httpx.TooManyRedirects):
                await _safe_request(client, "GET", "http://allowed.example.com/loop")

    @pytest.mark.asyncio
    async def test_redirect_without_location_returns_response(self) -> None:
        """A redirect status without Location header should return the response."""
        resp = _mock_response(301, headers={}, url="http://allowed.example.com/")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=resp)

        with patch("agent_framework.tools.http_client._check_target_allowed"):
            result = await _safe_request(client, "GET", "http://allowed.example.com/")
        assert result.status_code == 301

    @pytest.mark.asyncio
    async def test_303_redirect_converts_post_to_get(self) -> None:
        """A 303 redirect should convert the method to GET."""
        redirect_resp = _mock_response(
            303,
            headers={"location": "http://allowed.example.com/result"},
            url="http://allowed.example.com/submit",
        )
        final_resp = _mock_response(200, url="http://allowed.example.com/result")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(
            "agent_framework.tools.http_client._check_target_allowed",
            side_effect=_allow_all,
        ):
            await _safe_request(
                client, "POST", "http://allowed.example.com/submit", json={"data": 1}
            )
        # Second call should be GET (not POST)
        second_call = client.request.call_args_list[1]
        assert second_call[0][0] == "GET"

    @pytest.mark.asyncio
    async def test_follow_redirects_false_skips_validation(self) -> None:
        """When follow_redirects=False, just make the raw request."""
        resp = _mock_response(302, headers={"location": "http://evil.com/"})
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=resp)

        result = await _safe_request(
            client, "GET", "http://allowed.example.com/", follow_redirects=False
        )
        assert result.status_code == 302
        # Should NOT have followed the redirect
        assert client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_history_populated_on_redirect(self) -> None:
        """The final response should have redirect history populated."""
        redirect_resp = _mock_response(
            301,
            headers={"location": "http://allowed.example.com/new"},
            url="http://allowed.example.com/old",
        )
        final_resp = _mock_response(200, url="http://allowed.example.com/new")
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(side_effect=[redirect_resp, final_resp])

        with patch(
            "agent_framework.tools.http_client._check_target_allowed",
            side_effect=_allow_all,
        ):
            result = await _safe_request(client, "GET", "http://allowed.example.com/old")
        assert len(result.history) == 1
        assert result.history[0].status_code == 301
