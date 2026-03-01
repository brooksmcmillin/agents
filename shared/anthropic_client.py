"""Factory for creating Anthropic API clients.

Provides a single place to construct AsyncAnthropic clients so that
API key resolution is consistent across all agents and services.
"""

from anthropic import AsyncAnthropic


def get_anthropic_client(api_key: str | None = None) -> AsyncAnthropic:
    """Create an AsyncAnthropic client using the configured API key.

    Resolves the API key in priority order:
    1. Explicit ``api_key`` argument (if provided).
    2. ``settings.anthropic_api_key`` from the agent-framework configuration
       (which itself reads from the ``ANTHROPIC_API_KEY`` environment variable
       or the ``.env`` file).

    Args:
        api_key: Optional explicit API key. When ``None``, the key from
            ``settings`` is used.

    Returns:
        A configured ``AsyncAnthropic`` client instance.
    """
    if api_key is None:
        from agent_framework.core.config import settings

        api_key = settings.anthropic_api_key

    return AsyncAnthropic(api_key=api_key)
