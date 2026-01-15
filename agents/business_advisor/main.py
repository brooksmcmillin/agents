"""Main agent orchestrator for Business Advisor.

This module implements the agentic loop that:
1. Analyzes user's GitHub repos and websites
2. Generates monetization ideas with executive summaries
3. Develops comprehensive business plans on request
4. Provides strategic guidance for side income opportunities
"""

import asyncio
import os

from agent_framework import Agent
from typing import Any

from shared import run_agent, setup_logging

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

# Configure logging
logger = setup_logging(__name__)


class BusinessAdvisorAgent(Agent):
    """
    Business Advisor Agent using Claude and MCP tools.

    This agent helps users identify monetization opportunities based on
    their existing software projects, technical skills, and online presence.
    It can analyze GitHub repositories, websites, and professional resources
    to generate business ideas and develop comprehensive business plans.

    Features:
    - GitHub repository analysis for skill assessment
    - Website and portfolio evaluation
    - Business idea generation with executive summaries
    - Full business plan development
    - Market research and competitive analysis
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            allowed_tools=[
                "fetch_web_content",
                "get_memories",
                "save_memory",
                "search_memories",
                "send_slack_message",
            ],
            **kwargs,
        )

    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        return SYSTEM_PROMPT

    def get_greeting(self) -> str:
        """Return the greeting message for this agent."""
        return USER_GREETING_PROMPT


async def main():
    """Start the Business Advisor agent.

    Connects to local MCP server for web analysis and memory tools.
    Optionally connects to GitHub MCP server if GITHUB_MCP_SERVER is set.
    Requires ANTHROPIC_API_KEY in environment.
    """
    # Check for GitHub MCP configuration
    github_mcp_config = os.getenv("GITHUB_MCP_SERVER")

    mcp_config = {}
    if github_mcp_config:
        # If a GitHub MCP server URL is configured, add it
        mcp_config["mcp_urls"] = [github_mcp_config]
        logger.info(f"Using GitHub MCP server: {github_mcp_config}")

    await run_agent(BusinessAdvisorAgent, mcp_config if mcp_config else None)


if __name__ == "__main__":
    """Run the business advisor agent."""
    asyncio.run(main())
