#!/usr/bin/env python3
"""CLI runner for individual agents.

Usage:
    uv run python run_agent.py pr       # Run PR agent
    uv run python run_agent.py tasks    # Run Task Manager agent
    uv run python run_agent.py --list   # List available agents
"""

import argparse
import asyncio
import os
import sys

from agents.business_advisor.main import BusinessAdvisorAgent
from agents.pr_agent.main import PRAgent
from agents.task_manager.main import TaskManagerAgent
from agents.security_researcher.main import SecurityResearcherAgent
from shared import DEFAULT_MCP_SERVER_URL, ENV_MCP_SERVER_URL, run_agent

# Registry of available agents
AGENTS: dict[str, tuple[type, dict | None]] = {
    "pr": (PRAgent, None),
    "tasks": (
        TaskManagerAgent,
        {
            "mcp_urls": [os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)],
            "mcp_client_config": {
                "prefer_device_flow": True,  # Use Device Flow instead of browser
            },
        },
    ),
    "security": (SecurityResearcherAgent, None),
    "business": (
        BusinessAdvisorAgent,
        {
            "mcp_urls": ["https://api.githubcopilot.com/mcp/"],
            "mcp_client_config": {
                "auth_token": os.getenv("GITHUB_MCP_PAT"),
            },
        },
    ),
}


def list_agents() -> None:
    """Print available agents."""
    print("Available agents:")
    for name in AGENTS:
        print(f"  • {name}")


async def main() -> None:
    """Parse arguments and run the specified agent."""
    parser = argparse.ArgumentParser(
        description="Run a specific agent from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    uv run python run_agent.py pr       # Run PR agent
    uv run python run_agent.py tasks    # Run Task Manager agent
    uv run python run_agent.py --list   # List available agents
""",
    )
    parser.add_argument(
        "agent",
        nargs="?",
        choices=list(AGENTS.keys()),
        help="Agent to run",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available agents",
    )

    args = parser.parse_args()

    if args.list:
        list_agents()
        return

    if not args.agent:
        parser.print_help()
        sys.exit(1)

    agent_class, agent_kwargs = AGENTS[args.agent]
    print(f"Starting {args.agent} agent...")
    await run_agent(agent_class, agent_kwargs)


if __name__ == "__main__":
    asyncio.run(main())
