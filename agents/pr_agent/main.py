"""Main agent orchestrator for PR Assistant.

This module implements the agentic loop that:
1. Accepts user requests
2. Calls Claude via Anthropic SDK
3. Executes MCP tools as needed
4. Processes results and provides recommendations
"""

import asyncio

from agent_framework import Agent
from typing import Any

from shared import run_agent, setup_logging

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

# Configure logging
logger = setup_logging(__name__)

"""
Possible Tools: ['fetch_web_content', 'save_memory', 'get_memories', 'search_memories',
'send_slack_message', 'add_document', 'search_documents', 'get_document', 'delete_document',
'list_documents', 'get_rag_stats', 'analyze_website', 'get_social_media_stats', 'suggest_content_topics']
"""


class PRAgent(Agent):
    """
    PR Assistant Agent using Claude and MCP tools.

    This agent orchestrates conversations with the user, leveraging
    Claude's capabilities and MCP tools to provide content strategy advice.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            allowed_tools=[
                "analyze_website",
                "fetch_web_content",
                "get_memories",
                "get_social_media_stats",
                "save_memory",
                "search_memories",
                "send_slack_message",
                "suggest_content_topics",
            ],
            **kwargs,
        )

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_greeting(self) -> str:
        return USER_GREETING_PROMPT


async def main():
    """Start the PR Assistant agent.

    Connects to local MCP server for content analysis and memory tools.
    Requires ANTHROPIC_API_KEY in environment.
    """
    await run_agent(PRAgent)


if __name__ == "__main__":
    """Run the agent application."""
    asyncio.run(main())
