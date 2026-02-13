"""Local events discovery agent with preference learning."""

from shared import create_simple_agent

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

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent events")
    sys.exit(1)
