"""Main agent orchestrator for Security Researcher.

This module implements the agentic loop that:
1. Accepts user requests about AI security
2. Calls Claude via Anthropic SDK
3. Executes MCP tools as needed for research and analysis
4. Provides security insights, fact-checking, and review recommendations
"""

import asyncio

from agent_framework import Agent
from dotenv import load_dotenv
from typing import Any

from shared import run_agent, setup_logging

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

# Load environment variables
load_dotenv()

# Configure logging
logger = setup_logging(__name__)


class SecurityResearcherAgent(Agent):
    """
    Security Researcher Agent using Claude and MCP tools.

    This agent orchestrates conversations with the user, leveraging
    Claude's capabilities and MCP tools to provide AI security research
    assistance, blog post fact-checking, and system security reviews.

    Key capabilities:
    - Answer questions about AI/ML security research and best practices
    - Fact-check and review technical blog posts for accuracy
    - Conduct security reviews of AI/LLM system architectures
    - Help manage and query AI security knowledge bases
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            allowed_tools=[
                "add_document",
                "delete_document",
                "fetch_web_content",
                "get_document",
                "get_memories",
                "get_rag_stats",
                "list_documents",
                "save_memory",
                "search_documents",
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
    """Main entry point for the security researcher agent."""
    await run_agent(SecurityResearcherAgent)


if __name__ == "__main__":
    """Run the security researcher agent."""
    asyncio.run(main())
