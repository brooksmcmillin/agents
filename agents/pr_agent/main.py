"""PR Assistant agent.

Analyzes web content, provides content strategy advice, manages
user context via persistent memory, and can modify website source
code via Claude Code integration.
"""

import asyncio

from shared import (
    CLAUDE_CODE_TOOLS,
    COMMUNICATION_TOOLS,
    CONTENT_TOOLS,
    MEMORY_TOOLS,
    create_simple_agent,
    run_agent,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

PRAgent = create_simple_agent(
    name="PRAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=CONTENT_TOOLS + MEMORY_TOOLS + COMMUNICATION_TOOLS + CLAUDE_CODE_TOOLS,
)


async def main():
    """Start the PR Assistant agent."""
    await run_agent(PRAgent)


if __name__ == "__main__":
    asyncio.run(main())
