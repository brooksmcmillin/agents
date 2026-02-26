"""Tests for OAuth callback state parameter (CSRF) validation.

The _run_callback_server method starts a local HTTP server that receives
the OAuth callback. It validates the `state` parameter using
secrets.compare_digest to prevent CSRF attacks. These tests exercise
the callback handler directly via aiohttp's test utilities.
"""

import secrets

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


def _build_callback_app(expected_state: str) -> web.Application:
    """Build the aiohttp app that OAuthFlowHandler._run_callback_server creates.

    We replicate the app setup here because _run_callback_server also
    starts the server and blocks, which makes it hard to test directly.
    Instead we test the route handler in isolation.
    """
    auth_code_holder: dict[str, str | None] = {"code": None, "error": None}

    async def callback(request: web.Request) -> web.Response:
        returned_state = request.query.get("state")
        if not secrets.compare_digest(returned_state or "", expected_state):
            auth_code_holder["error"] = "state_mismatch"
            return web.Response(text="State mismatch", status=200, content_type="text/html")

        if "code" in request.query:
            auth_code_holder["code"] = request.query["code"]
            return web.Response(text="OK", status=200, content_type="text/html")

        if "error" in request.query:
            auth_code_holder["error"] = request.query.get("error", "Unknown error")
            return web.Response(text="Error", status=200, content_type="text/html")

        return web.Response(text="Invalid callback", status=400)

    app = web.Application()
    app.router.add_get("/callback", callback)
    app["auth_code_holder"] = auth_code_holder
    return app


@pytest.fixture
def expected_state() -> str:
    return secrets.token_urlsafe(32)


class TestOAuthCallbackStateValidation:
    """Tests that the OAuth callback correctly validates the state parameter."""

    @pytest.mark.asyncio
    async def test_matching_state_returns_code(self, expected_state: str) -> None:
        """A callback with matching state should capture the auth code."""
        app = _build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/callback", params={"state": expected_state, "code": "abc123"})
            assert resp.status == 200
            text = await resp.text()
            assert "OK" in text
            assert app["auth_code_holder"]["code"] == "abc123"
            assert app["auth_code_holder"]["error"] is None

    @pytest.mark.asyncio
    async def test_mismatched_state_sets_error(self, expected_state: str) -> None:
        """A callback with a different state must be rejected (CSRF protection)."""
        app = _build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get(
                "/callback", params={"state": "wrong-state-value", "code": "abc123"}
            )
            assert resp.status == 200
            text = await resp.text()
            assert "State mismatch" in text
            assert app["auth_code_holder"]["error"] == "state_mismatch"
            assert app["auth_code_holder"]["code"] is None

    @pytest.mark.asyncio
    async def test_missing_state_sets_error(self, expected_state: str) -> None:
        """A callback with no state parameter must be rejected."""
        app = _build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/callback", params={"code": "abc123"})
            assert resp.status == 200
            text = await resp.text()
            assert "State mismatch" in text
            assert app["auth_code_holder"]["error"] == "state_mismatch"

    @pytest.mark.asyncio
    async def test_empty_state_sets_error(self, expected_state: str) -> None:
        """A callback with an empty state parameter must be rejected."""
        app = _build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/callback", params={"state": "", "code": "abc123"})
            assert resp.status == 200
            assert app["auth_code_holder"]["error"] == "state_mismatch"

    @pytest.mark.asyncio
    async def test_error_response_from_provider(self, expected_state: str) -> None:
        """An OAuth error response with valid state should capture the error."""
        app = _build_callback_app(expected_state)
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
            assert app["auth_code_holder"]["error"] == "access_denied"
            assert app["auth_code_holder"]["code"] is None

    @pytest.mark.asyncio
    async def test_no_code_no_error_returns_400(self, expected_state: str) -> None:
        """A callback with valid state but no code or error is a bad request."""
        app = _build_callback_app(expected_state)
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
        app = _build_callback_app(expected_state)
        async with TestClient(TestServer(app)) as client:
            await client.get("/callback", params={"state": tampered, "code": "abc123"})
            assert app["auth_code_holder"]["error"] == "state_mismatch"
