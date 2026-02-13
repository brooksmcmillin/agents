"""Code Analysis agent.

Connects to a remote MCP server to create and manage tasks for code
analysis findings. Critically examines repositories for security
vulnerabilities, logic errors, performance issues, and architectural
improvements.
"""

from shared import (
    COMMUNICATION_TOOLS,
    FILESYSTEM_TOOLS,
    MEMORY_TOOLS,
    create_simple_agent,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

CodeAnalysisAgent = create_simple_agent(
    name="CodeAnalysisAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=(["fetch_web_content"] + MEMORY_TOOLS + COMMUNICATION_TOOLS + FILESYSTEM_TOOLS),
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent code-analysis")
    sys.exit(1)
