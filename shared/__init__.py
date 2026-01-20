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

from dotenv import load_dotenv

# Load environment variables once when shared module is imported
load_dotenv()

# ruff: noqa: E402 - imports after load_dotenv() is intentional
from .agent_factory import create_simple_agent
from .agent_runner import run_agent
from .auth_utils import get_valid_token_for_mcp
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
from .task_utils import format_priority_emoji, parse_priority, parse_task_result

# Import SSRFValidator from agent-framework (moved from shared.security_utils)
from agent_framework.security import SSRFValidator

__all__ = [
    "DEFAULT_MCP_SERVER_URL",
    "ENV_ANTHROPIC_API_KEY",
    "ENV_MCP_AUTH_TOKEN",
    "ENV_MCP_SERVER_URL",
    "ENV_SLACK_APP_TOKEN",
    "ENV_SLACK_BOT_TOKEN",
    "ENV_SLACK_WEBHOOK_URL",
    "SSRFValidator",
    "check_env_vars",
    "create_simple_agent",
    "env_file_exists",
    "format_priority_emoji",
    "get_valid_token_for_mcp",
    "parse_priority",
    "parse_task_result",
    "run_agent",
    "setup_logging",
]
__version__ = "0.1.0"
