"""Main agent orchestrator for PR Assistant.

This module implements the agentic loop that:
1. Accepts user requests
2. Calls Claude via Anthropic SDK
3. Executes MCP tools as needed
4. Processes results and provides recommendations
"""

import asyncio

from agent_framework import Agent
from dotenv import load_dotenv

from shared import run_agent, setup_logging

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logging(__name__)


class PRAgent(Agent):
    """
    PR Assistant Agent using Claude and MCP tools.

    This agent orchestrates conversations with the user, leveraging
    Claude's capabilities and MCP tools to provide content strategy advice.
    """

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_greeting(self) -> str:
        return USER_GREETING_PROMPT


async def main():
    """Main entry point for the agent application."""
    await run_agent(PRAgent)


if __name__ == "__main__":
    """Run the agent application."""
    asyncio.run(main())
