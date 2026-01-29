"""Security Researcher agent.

Provides AI security research assistance, blog post fact-checking,
and system security reviews with RAG-backed knowledge base.
"""

import asyncio

from shared import (
    COMMUNICATION_TOOLS,
    MEMORY_TOOLS,
    RAG_TOOLS,
    create_simple_agent,
    run_agent,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

SecurityResearcherAgent = create_simple_agent(
    name="SecurityResearcherAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=(
        ["fetch_web_content"] + RAG_TOOLS + MEMORY_TOOLS + COMMUNICATION_TOOLS
    ),
)


async def main():
    """Start the Security Researcher agent."""
    await run_agent(SecurityResearcherAgent)


if __name__ == "__main__":
    asyncio.run(main())
