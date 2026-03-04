"""Email Responder agent.

Monitors incoming emails, evaluates which ones need replies,
and saves draft responses for human review. Never sends emails directly.
"""

from shared import EMAIL_DRAFT_TOOLS, create_simple_agent

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

EmailResponderAgent = create_simple_agent(
    name="EmailResponderAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=EMAIL_DRAFT_TOOLS,
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent email-responder")
    sys.exit(1)
