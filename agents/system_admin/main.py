"""System Admin agent.

Provides network discovery, port scanning, service auditing, configuration
review, default credential detection, and security reporting for local
infrastructure assessment.
"""

from shared import (
    COMMUNICATION_TOOLS,
    MEMORY_TOOLS,
    NETWORK_ADMIN_TOOLS,
    create_simple_agent,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

SystemAdminAgent = create_simple_agent(
    name="SystemAdminAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=(NETWORK_ADMIN_TOOLS + MEMORY_TOOLS + COMMUNICATION_TOOLS),
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent sysadmin")
    sys.exit(1)
