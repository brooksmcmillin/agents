"""Red team security testing agent.

Performs authorized dynamic security testing against web applications
using HTTP client tools, memory for persisting findings, and email
for sending reports.
"""

from shared import (
    COMMUNICATION_TOOLS,
    EMAIL_TOOLS,
    HTTP_CLIENT_TOOLS,
    MEMORY_TOOLS,
    create_simple_agent,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

RedTeamAgent = create_simple_agent(
    name="RedTeamAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=(
        HTTP_CLIENT_TOOLS + MEMORY_TOOLS + COMMUNICATION_TOOLS + EMAIL_TOOLS + ["fetch_web_content"]
    ),
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent red-team")
    sys.exit(1)
