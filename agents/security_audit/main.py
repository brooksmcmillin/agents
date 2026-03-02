"""Security Audit Analyzer agent.

Reads structured JSON security audit reports produced by the non-LLM
collector (agents/security_audit/collector.py) and provides actionable
analysis using an LLM.

Two-part architecture:
    1. collector.py  — runs on target machines, no LLM, writes JSON reports
    2. This agent     — reads those reports via filesystem tools and analyzes them
"""

from shared import (
    COMMUNICATION_TOOLS,
    FILESYSTEM_TOOLS,
    MEMORY_TOOLS,
    create_simple_agent,
)

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

SecurityAuditAgent = create_simple_agent(
    name="SecurityAuditAgent",
    system_prompt=SYSTEM_PROMPT,
    greeting=USER_GREETING_PROMPT,
    allowed_tools=(FILESYSTEM_TOOLS + MEMORY_TOOLS + COMMUNICATION_TOOLS + ["fetch_web_content"]),
)

if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent security-audit")
    sys.exit(1)
