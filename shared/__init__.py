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
# Import SSRFValidator from agent-framework (moved from shared.security_utils)
from agent_framework.security import SSRFValidator

from .agent_factory import create_simple_agent
from .agent_runner import run_agent
from .auth_utils import get_valid_token_for_mcp
from .batch_agent import BatchAgent
from .constants import (
    CLAUDE_CODE_TOOLS,
    COMMUNICATION_TOOLS,
    CONTENT_TOOLS,
    DEFAULT_MCP_SERVER_URL,
    EMAIL_TOOLS,
    ENV_ANTHROPIC_API_KEY,
    ENV_MCP_AUTH_TOKEN,
    ENV_MCP_SERVER_URL,
    ENV_SLACK_APP_TOKEN,
    ENV_SLACK_BOT_TOKEN,
    ENV_SLACK_WEBHOOK_URL,
    FASTMAIL_TOOLS,
    FILESYSTEM_TOOLS,
    HTTP_CLIENT_TOOLS,
    MEMORY_TOOLS,
    NETWORK_ADMIN_TOOLS,
    RAG_TOOLS,
    SMS_TOOLS,
    WEB_RESEARCH_TOOLS,
)
from .env_utils import check_env_vars, env_file_exists
from .gh import REPO_RE, run_gh, validate_repo
from .json_parsing import strip_and_parse_json, strip_markdown_fences
from .logging_config import setup_logging
from .registry import GITHUB_MCP_AGENTS, build_agent_registry, github_mcp_config
from .task_utils import format_priority_emoji, parse_json_result, parse_priority, parse_task_result

__all__ = [
    "BatchAgent",
    "CLAUDE_CODE_TOOLS",
    "COMMUNICATION_TOOLS",
    "CONTENT_TOOLS",
    "DEFAULT_MCP_SERVER_URL",
    "EMAIL_TOOLS",
    "ENV_ANTHROPIC_API_KEY",
    "ENV_MCP_AUTH_TOKEN",
    "ENV_MCP_SERVER_URL",
    "ENV_SLACK_APP_TOKEN",
    "ENV_SLACK_BOT_TOKEN",
    "ENV_SLACK_WEBHOOK_URL",
    "FASTMAIL_TOOLS",
    "FILESYSTEM_TOOLS",
    "GITHUB_MCP_AGENTS",
    "HTTP_CLIENT_TOOLS",
    "MEMORY_TOOLS",
    "NETWORK_ADMIN_TOOLS",
    "RAG_TOOLS",
    "REPO_RE",
    "SMS_TOOLS",
    "SSRFValidator",
    "WEB_RESEARCH_TOOLS",
    "build_agent_registry",
    "check_env_vars",
    "create_simple_agent",
    "env_file_exists",
    "format_priority_emoji",
    "get_valid_token_for_mcp",
    "github_mcp_config",
    "parse_json_result",
    "parse_priority",
    "parse_task_result",
    "run_agent",
    "run_gh",
    "setup_logging",
    "strip_and_parse_json",
    "strip_markdown_fences",
    "validate_repo",
]
__version__ = "0.1.0"
