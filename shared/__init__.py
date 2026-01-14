"""Shared utilities and base classes for all agents.

This module contains common code that can be reused across multiple agents,
including:
- Base agent classes
- Common configuration
- Utility functions

OAuth and MCP client utilities have been moved to agent-framework.
Use `from agent_framework.oauth import ...` for OAuth functionality.
Use `from agent_framework.core import RemoteMCPClient` for remote MCP.
"""

from .agent_runner import run_agent
from .constants import (
    DEFAULT_MCP_SERVER_URL,
    ENV_ANTHROPIC_API_KEY,
    ENV_MCP_AUTH_TOKEN,
    ENV_MCP_SERVER_URL,
    ENV_SLACK_APP_TOKEN,
    ENV_SLACK_BOT_TOKEN,
    ENV_SLACK_WEBHOOK_URL,
)
from .env_utils import check_env_vars, env_file_exists
from .logging_config import setup_logging

__all__ = [
    "DEFAULT_MCP_SERVER_URL",
    "ENV_ANTHROPIC_API_KEY",
    "ENV_MCP_AUTH_TOKEN",
    "ENV_MCP_SERVER_URL",
    "ENV_SLACK_APP_TOKEN",
    "ENV_SLACK_BOT_TOKEN",
    "ENV_SLACK_WEBHOOK_URL",
    "check_env_vars",
    "env_file_exists",
    "run_agent",
    "setup_logging",
]
__version__ = "0.1.0"
