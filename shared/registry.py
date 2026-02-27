"""Shared agent registry — single source of truth for both API and CLI.

Each entry maps a short name to (AgentClass, constructor kwargs, description).
Imports are deferred to build time so importing this module is cheap.
"""

import logging
import os
from typing import Any

from agent_framework import Agent

from .constants import DEFAULT_MCP_RELAY_URL, DEFAULT_MCP_SERVER_URL, ENV_MCP_SERVER_URL

logger = logging.getLogger(__name__)

_GITHUB_PAT_PREFIXES = ("ghp_", "github_pat_", "gho_", "ghu_", "ghs_", "ghr_")

# Agents whose kwargs include a GitHub MCP config that requires GITHUB_MCP_PAT.
# Their kwargs are built lazily so that --list / health checks don't fail when
# the env var is unset.
GITHUB_MCP_AGENTS = frozenset({"security", "business"})

AgentEntry = tuple[type[Agent], dict[str, Any] | None, str]


def get_github_pat() -> str:
    """Get and validate GitHub PAT from environment.

    Returns:
        The GitHub PAT token.

    Raises:
        ValueError: If the token is not set.
    """
    token = os.getenv("GITHUB_MCP_PAT")
    if not token:
        raise ValueError(
            "GITHUB_MCP_PAT environment variable is required for GitHub MCP. "
            "Set it in your .env file or environment."
        )
    if not token.startswith(_GITHUB_PAT_PREFIXES):
        logger.warning(
            "GITHUB_MCP_PAT has unexpected format (expected prefix: %s). "
            "Verify your token is valid.",
            ", ".join(_GITHUB_PAT_PREFIXES),
        )
    return token


def github_mcp_config() -> dict[str, Any]:
    """Build MCP config for GitHub Copilot MCP server."""
    return {
        "mcp_urls": ["https://api.githubcopilot.com/mcp/"],
        "mcp_client_config": {
            "auth_token": get_github_pat(),
        },
    }


def build_agent_registry() -> dict[str, AgentEntry]:
    """Build the agent registry.

    Imports are deferred to here so the module can be imported without
    triggering heavyweight side-effects (Anthropic client init, etc.).

    Returns:
        Mapping of agent short name to (AgentClass, kwargs, description).
    """
    from agents.business_advisor.main import BusinessAdvisorAgent
    from agents.chatbot.main import ChatbotAgent
    from agents.code_analysis.main import CodeAnalysisAgent
    from agents.events.main import EventsAgent
    from agents.pr_agent.main import PRAgent
    from agents.red_team.main import RedTeamAgent
    from agents.security_researcher.main import SecurityResearcherAgent
    from agents.system_admin.main import SystemAdminAgent
    from agents.task_manager.main import TaskManagerAgent

    mcp_task_config: dict[str, Any] = {
        "mcp_urls": [os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)],
        "mcp_client_config": {"prefer_device_flow": True},
    }

    mcp_relay_config: dict[str, Any] = {
        "mcp_urls": [DEFAULT_MCP_RELAY_URL],
        "mcp_client_config": {"prefer_device_flow": True},
    }

    return {
        "chatbot": (
            ChatbotAgent,
            {**mcp_relay_config},
            "General-purpose chatbot with full MCP tool access",
        ),
        "code-analysis": (
            CodeAnalysisAgent,
            {**mcp_task_config},
            "Repository analysis agent for security, logic, performance, and architecture improvements",
        ),
        "events": (
            EventsAgent,
            None,
            "Local events discovery with preference learning",
        ),
        "pr": (
            PRAgent,
            None,
            "PR and content strategy assistant",
        ),
        "red-team": (
            RedTeamAgent,
            None,
            "Red team security testing agent",
        ),
        "tasks": (
            TaskManagerAgent,
            {**mcp_task_config},
            "Interactive task management agent",
        ),
        "security": (
            SecurityResearcherAgent,
            None,  # kwargs built lazily via github_mcp_config()
            "Security research assistant",
        ),
        "business": (
            BusinessAdvisorAgent,
            None,  # kwargs built lazily via github_mcp_config()
            "Business strategy and monetization advisor",
        ),
        "sysadmin": (
            SystemAdminAgent,
            None,
            "Network and system security assessment agent",
        ),
    }
