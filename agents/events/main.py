"""Local events discovery agent with preference learning."""

import asyncio

from shared import create_simple_agent, run_agent

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

EventsAgent = create_simple_agent(
    name="EventsAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=[
        "fetch_web_content",
        "get_memories",
        "save_memory",
        "search_memories",
    ],
)


async def main():
    """Start the events discovery agent."""
    await run_agent(EventsAgent)


if __name__ == "__main__":
    asyncio.run(main())
