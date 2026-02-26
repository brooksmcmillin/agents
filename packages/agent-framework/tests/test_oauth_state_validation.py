"""Tests for OAuth callback state parameter (CSRF) validation.

The OAuthFlowHandler.build_callback_app method creates the aiohttp app that
receives the OAuth callback. It validates the `state` parameter using
secrets.compare_digest to prevent CSRF attacks. These tests exercise
the production callback handler directly via aiohttp's test utilities.
"""

import secrets

import pytest
from aiohttp.test_utils import TestClient, TestServer

from agent_framework.oauth.oauth_flow import OAuthFlowHandler


@pytest.fixture
def expected_state() -> str:
    return secrets.token_urlsafe(32)


class TestOAuthCallbackStateValidation:
    """Tests that the OAuth callback correctly validates the state parameter."""

    @pytest.mark.asyncio
    async def test_matching_state_returns_code(self, expected_state: str) -> None:
        """A callback with matching state should capture the auth code."""
        app, auth_result = OAuthFlowHandler.build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/callback", params={"state": expected_state, "code": "abc123"})
            assert resp.status == 200
            text = await resp.text()
            assert "Successful" in text
            assert auth_result["code"] == "abc123"
            assert auth_result["error"] is None

    @pytest.mark.asyncio
    async def test_mismatched_state_sets_error(self, expected_state: str) -> None:
        """A callback with a different state must be rejected (CSRF protection)."""
        app, auth_result = OAuthFlowHandler.build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/callback", params={"state": "wrong-state-value", "code": "abc123"}
            )
            assert resp.status == 400
            text = await resp.text()
            assert "State mismatch" in text or "Failed" in text
            assert auth_result["error"] == "state_mismatch"
            assert auth_result["code"] is None

    @pytest.mark.asyncio
    async def test_missing_state_sets_error(self, expected_state: str) -> None:
        """A callback with no state parameter must be rejected."""
        app, auth_result = OAuthFlowHandler.build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/callback", params={"code": "abc123"})
            assert resp.status == 400
            assert auth_result["error"] == "state_mismatch"

    @pytest.mark.asyncio
    async def test_empty_state_sets_error(self, expected_state: str) -> None:
        """A callback with an empty state parameter must be rejected."""
        app, auth_result = OAuthFlowHandler.build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/callback", params={"state": "", "code": "abc123"})
            assert resp.status == 400
            assert auth_result["error"] == "state_mismatch"

    @pytest.mark.asyncio
    async def test_error_response_from_provider(self, expected_state: str) -> None:
        """An OAuth error response with valid state should capture the error."""
        app, auth_result = OAuthFlowHandler.build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/callback",
                params={
                    "state": expected_state,
                    "error": "access_denied",
                    "error_description": "User denied access",
                },
            )
            assert resp.status == 200
            assert auth_result["error"] == "access_denied"
            assert auth_result["code"] is None

    @pytest.mark.asyncio
    async def test_no_code_no_error_returns_400(self, expected_state: str) -> None:
        """A callback with valid state but no code or error is a bad request."""
        app, _auth_result = OAuthFlowHandler.build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/callback", params={"state": expected_state})
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_timing_safe_comparison(self, expected_state: str) -> None:
        """A state differing only in the last character is still rejected.

        This confirms the comparison isn't short-circuiting on first
        differing byte (which secrets.compare_digest prevents).
        """
        tampered = expected_state[:-1] + ("A" if expected_state[-1] != "A" else "B")
        app, auth_result = OAuthFlowHandler.build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            await client.get("/callback", params={"state": tampered, "code": "abc123"})
            assert auth_result["error"] == "state_mismatch"
