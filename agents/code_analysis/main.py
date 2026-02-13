"""Code Analysis agent.

Connects to a remote MCP server to create and manage tasks for code
analysis findings. Critically examines repositories for security
vulnerabilities, logic errors, performance issues, and architectural
improvements.
"""

import asyncio
import os

from shared import (
    COMMUNICATION_TOOLS,
    DEFAULT_MCP_SERVER_URL,
    ENV_MCP_SERVER_URL,
    MEMORY_TOOLS,
    create_simple_agent,
    run_agent,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

CodeAnalysisAgent = create_simple_agent(
    name="CodeAnalysisAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=(["fetch_web_content"] + MEMORY_TOOLS + COMMUNICATION_TOOLS),
)


async def main() -> None:
    """Start the Code Analysis agent.

    Connects to remote MCP server at MCP_SERVER_URL for task management.
    """
    mcp_url = os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)
    await run_agent(CodeAnalysisAgent, {"mcp_urls": [mcp_url]})


if __name__ == "__main__":
    asyncio.run(main())
