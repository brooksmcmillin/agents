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

    Also configures agent-to-agent delegation on the Agent base class
    via :func:`shared.delegation.setup_delegation`.

    Returns:
        Mapping of agent short name to (AgentClass, kwargs, description).
    """
    from agents.business_advisor.main import BusinessAdvisorAgent
    from agents.chatbot.main import ChatbotAgent
    from agents.code_analysis.main import CodeAnalysisAgent
    from agents.events.main import EventsAgent
    from agents.log_analysis.main import LogAnalysisAgent
    from agents.pr_agent.main import PRAgent
    from agents.red_team.main import RedTeamAgent
    from agents.security_audit.main import SecurityAuditAgent
    from agents.security_researcher.main import SecurityResearcherAgent
    from agents.system_admin.main import SystemAdminAgent
    from agents.task_manager.main import TaskManagerAgent
    from agents.web_analysis.main import WebAnalysisAgent
    from agents.website_tester.main import WebsiteTesterAgent
    from shared.delegation import seed_registry_cache, setup_delegation

    mcp_task_config: dict[str, Any] = {
        "mcp_urls": [os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)],
        "mcp_client_config": {"prefer_device_flow": True},
    }

    # NOTE: the MCP relay server does not validate the ``sender`` field that
    # relay tools accept. Any caller can set sender to an arbitrary name,
    # including reserved names like "system". Treat the sender field as
    # untrusted and advisory-only; never use it for authorization decisions.
    # See RESERVED_RELAY_SENDER_NAMES and validate_relay_sender() in
    # shared/constants.py for the reserved-name list and best-effort check.
    mcp_relay_config: dict[str, Any] = {
        "mcp_urls": [DEFAULT_MCP_RELAY_URL],
        "mcp_client_config": {"prefer_device_flow": True},
    }

    # Delegation: enable_delegation=True gives the agent a request_agent tool
    # that lets it consult other agents in the registry. The delegated agent
    # inherits the caller's permissions via ExecutionContext intersection.
    delegation_config: dict[str, Any] = {"enable_delegation": True}

    # Configure the Agent base class for delegation support
    setup_delegation()

    registry = {
        "chatbot": (
            ChatbotAgent,
            {**mcp_relay_config, **delegation_config},
            "General-purpose chatbot with full MCP tool access",
        ),
        "code-analysis": (
            CodeAnalysisAgent,
            {**mcp_task_config, **delegation_config},
            "Repository analysis agent for security, logic, performance, and architecture improvements",
        ),
        "events": (
            EventsAgent,
            None,
            "Local events discovery with preference learning",
        ),
        "log-analysis": (
            LogAnalysisAgent,
            None,
            "Log analysis agent with automatic pinning of critical findings",
        ),
        "pr": (
            PRAgent,
            delegation_config,
            "PR and content strategy assistant",
        ),
        "red-team": (
            RedTeamAgent,
            None,
            "Red team security testing agent",
        ),
        "tasks": (
            TaskManagerAgent,
            {**mcp_task_config, **delegation_config},
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
        "security-audit": (
            SecurityAuditAgent,
            None,
            "Security audit analyzer (reads reports from non-LLM collector)",
        ),
        "sysadmin": (
            SystemAdminAgent,
            None,
            "Network and system security assessment agent",
        ),
        "web-analysis": (
            WebAnalysisAgent,
            {**mcp_task_config},
            "Website auditing with automatic task creation for issues found",
        ),
        "website-tester": (
            WebsiteTesterAgent,
            None,
            "Automated website testing with headless Playwright browser",
        ),
    }

    # Seed the delegation module's cache so the first delegation call
    # doesn't trigger another build_agent_registry() call
    seed_registry_cache(registry)

    return registry
