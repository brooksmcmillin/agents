"""General-purpose chatbot with all MCP tools enabled."""

from shared import create_simple_agent

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

ChatbotAgent = create_simple_agent(
    name="ChatbotAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    # No allowed_tools restriction — access to all MCP tools
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent chatbot")
    sys.exit(1)
