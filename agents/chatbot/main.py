"""Main agent orchestrator for general chatbot.

This module implements a simple Claude chatbot with all MCP tools enabled.
"""

import asyncio

from agent_framework import Agent
from typing import Any

from shared import run_agent, setup_logging

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

# Configure logging
logger = setup_logging(__name__)


class ChatbotAgent(Agent):
    """
    Simple Claude chatbot with all MCP tools enabled.

    This agent provides a general-purpose conversational interface with
    access to all available MCP tools.
    """

    def __init__(self, **kwargs: Any) -> None:
        # Don't restrict tools - allow access to all MCP tools
        super().__init__(**kwargs)

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_greeting(self) -> str:
        return USER_GREETING_PROMPT


async def main():
    """Start the chatbot agent.

    Connects to local MCP server for all available tools.
    Requires ANTHROPIC_API_KEY in environment.
    """
    await run_agent(ChatbotAgent)


if __name__ == "__main__":
    """Run the agent application."""
    asyncio.run(main())
