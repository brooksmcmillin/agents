"""Tests for the fail-closed API_KEY requirement.

The server must refuse to start unless one of:
  1. API_KEY is set (authentication enabled), or
  2. DISABLE_AUTH=true is explicitly set (developer opt-out).

This prevents accidental deployment of an unauthenticated API.
"""

import os
from unittest.mock import patch

import pytest


class TestLifespanAuthRequirement:
    """Tests for the lifespan auth gate."""

    @pytest.mark.asyncio
    async def test_refuses_startup_without_api_key_or_disable_auth(self) -> None:
        """Server must raise RuntimeError when neither API_KEY nor DISABLE_AUTH is set."""
        env = {"API_KEY": "", "DISABLE_AUTH": "", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            # Re-import with clean env to reset _api_key at module level
            with patch("api.server._api_key", None):
                from api.server import app, lifespan

                with pytest.raises(RuntimeError, match="API_KEY environment variable is required"):
                    async with lifespan(app):
                        pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_starts_with_api_key_set(self) -> None:
        """Server should start normally when API_KEY is set."""
        with patch("api.server._api_key", "test-secret-key"):
            from api.server import app, lifespan

            # Should not raise — lifespan completes startup
            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_starts_with_disable_auth_true(self) -> None:
        """Server should start when DISABLE_AUTH=true (explicit dev opt-out)."""
        env = {"DISABLE_AUTH": "true", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False), patch("api.server._api_key", None):
            from api.server import app, lifespan

            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_starts_with_disable_auth_yes(self) -> None:
        """DISABLE_AUTH=yes should also be accepted."""
        env = {"DISABLE_AUTH": "yes", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False), patch("api.server._api_key", None):
            from api.server import app, lifespan

            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_starts_with_disable_auth_one(self) -> None:
        """DISABLE_AUTH=1 should also be accepted."""
        env = {"DISABLE_AUTH": "1", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False), patch("api.server._api_key", None):
            from api.server import app, lifespan

            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_refuses_with_disable_auth_false(self) -> None:
        """DISABLE_AUTH=false should NOT bypass the requirement."""
        env = {"DISABLE_AUTH": "false", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False), patch("api.server._api_key", None):
            from api.server import app, lifespan

            with pytest.raises(RuntimeError, match="API_KEY environment variable is required"):
                async with lifespan(app):
                    pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_refuses_with_disable_auth_random_string(self) -> None:
        """DISABLE_AUTH=please should NOT bypass the requirement."""
        env = {"DISABLE_AUTH": "please", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False), patch("api.server._api_key", None):
            from api.server import app, lifespan

            with pytest.raises(RuntimeError, match="API_KEY environment variable is required"):
                async with lifespan(app):
                    pass  # pragma: no cover
