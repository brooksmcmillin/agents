"""General-purpose chatbot with all MCP tools enabled."""

import asyncio

from shared import create_simple_agent, run_agent

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

ChatbotAgent = create_simple_agent(
    name="ChatbotAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    # No allowed_tools restriction — access to all MCP tools
)


async def main():
    """Start the chatbot agent."""
    await run_agent(ChatbotAgent)


if __name__ == "__main__":
    asyncio.run(main())
