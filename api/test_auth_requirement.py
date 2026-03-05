"""Tests for the fail-closed API_KEY requirement.

The server must refuse to start unless one of:
  1. API_KEY is set (authentication enabled), or
  2. DISABLE_AUTH=true AND ENV=development are both explicitly set (developer opt-out).

This prevents accidental deployment of an unauthenticated API, including staging
environments that omit ENV=production but are still publicly accessible.
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
            from api.server import app, lifespan

            with pytest.raises(RuntimeError, match="API_KEY environment variable is required"):
                async with lifespan(app):
                    pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_starts_with_api_key_set(self) -> None:
        """Server should start normally when API_KEY is set."""
        env = {"API_KEY": "test-secret-key", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            from api.server import app, lifespan

            # Should not raise -- lifespan completes startup
            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_starts_with_disable_auth_true_and_env_development(self) -> None:
        """Server should start when DISABLE_AUTH=true and ENV=development (explicit dev opt-out)."""
        env = {"API_KEY": "", "DISABLE_AUTH": "true", "ENV": "development", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            from api.server import app, lifespan

            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_refuses_with_disable_auth_true_without_env_development(self) -> None:
        """DISABLE_AUTH=true without ENV=development must raise RuntimeError."""
        env = {"API_KEY": "", "DISABLE_AUTH": "true", "ENV": "", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            from api.server import app, lifespan

            with pytest.raises(RuntimeError, match="DISABLE_AUTH=true requires ENV=development"):
                async with lifespan(app):
                    pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_refuses_with_disable_auth_true_and_env_production(self) -> None:
        """DISABLE_AUTH=true with ENV=production must raise RuntimeError."""
        env = {"API_KEY": "", "DISABLE_AUTH": "true", "ENV": "production", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            from api.server import app, lifespan

            with pytest.raises(RuntimeError, match="DISABLE_AUTH=true requires ENV=development"):
                async with lifespan(app):
                    pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_starts_with_disable_auth_yes(self) -> None:
        """DISABLE_AUTH=yes with ENV=development should also be accepted."""
        env = {"API_KEY": "", "DISABLE_AUTH": "yes", "ENV": "development", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            from api.server import app, lifespan

            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_starts_with_disable_auth_one(self) -> None:
        """DISABLE_AUTH=1 with ENV=development should also be accepted."""
        env = {"API_KEY": "", "DISABLE_AUTH": "1", "ENV": "development", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            from api.server import app, lifespan

            async with lifespan(app):
                pass

    @pytest.mark.asyncio
    async def test_refuses_with_disable_auth_false(self) -> None:
        """DISABLE_AUTH=false should NOT bypass the requirement."""
        env = {"API_KEY": "", "DISABLE_AUTH": "false", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            from api.server import app, lifespan

            with pytest.raises(RuntimeError, match="API_KEY environment variable is required"):
                async with lifespan(app):
                    pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_refuses_with_disable_auth_random_string(self) -> None:
        """DISABLE_AUTH=please should NOT bypass the requirement."""
        env = {"API_KEY": "", "DISABLE_AUTH": "please", "DATABASE_URL": ""}
        with patch.dict(os.environ, env, clear=False):
            from api.server import app, lifespan

            with pytest.raises(RuntimeError, match="API_KEY environment variable is required"):
                async with lifespan(app):
                    pass  # pragma: no cover
