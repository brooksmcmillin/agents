"""Business Advisor agent.

Analyzes GitHub repos and websites, generates monetization ideas,
and develops comprehensive business plans.
"""

from shared import (
    COMMUNICATION_TOOLS,
    MEMORY_TOOLS,
    create_simple_agent,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

BusinessAdvisorAgent = create_simple_agent(
    name="BusinessAdvisorAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=["fetch_web_content"] + MEMORY_TOOLS + COMMUNICATION_TOOLS,
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent business")
    sys.exit(1)
