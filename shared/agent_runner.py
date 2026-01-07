"""Common agent startup utilities.

This module provides a standard way to run agents with consistent
error handling and logging configuration.
"""

import logging
from typing import Any

from agent_framework import Agent

logger = logging.getLogger(__name__)


async def run_agent(
    agent_class: type[Agent],
    agent_kwargs: dict[str, Any] | None = None,
) -> None:
    """Run an agent with standard error handling.

    This function provides a consistent way to start agents with proper
    error handling for common issues like missing API keys.

    Args:
        agent_class: Agent class to instantiate and run
        agent_kwargs: Keyword arguments to pass to agent constructor
    """
    try:
        agent = agent_class(**(agent_kwargs or {}))
        await agent.start()

    except ValueError as e:
        print(f"\nConfiguration error: {e}")
        print("\nPlease ensure:")
        print("1. You have a .env file with ANTHROPIC_API_KEY set")
        print("2. The API key is valid")

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        print(f"\nFatal error: {e}")
