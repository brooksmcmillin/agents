"""Business Advisor agent.

Analyzes GitHub repos and websites, generates monetization ideas,
and develops comprehensive business plans.
"""

import asyncio
import os

from shared import (
    COMMUNICATION_TOOLS,
    MEMORY_TOOLS,
    create_simple_agent,
    run_agent,
    setup_logging,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

logger = setup_logging(__name__)

BusinessAdvisorAgent = create_simple_agent(
    name="BusinessAdvisorAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=["fetch_web_content"] + MEMORY_TOOLS + COMMUNICATION_TOOLS,
)


async def main():
    """Start the Business Advisor agent.

    Optionally connects to GitHub MCP server if GITHUB_MCP_SERVER is set.
    """
    github_mcp_config = os.getenv("GITHUB_MCP_SERVER")

    mcp_config = {}
    if github_mcp_config:
        mcp_config["mcp_urls"] = [github_mcp_config]
        logger.info(f"Using GitHub MCP server: {github_mcp_config}")

    await run_agent(BusinessAdvisorAgent, mcp_config if mcp_config else None)


if __name__ == "__main__":
    asyncio.run(main())
