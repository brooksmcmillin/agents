#!/usr/bin/env python3
"""Oneshot agent runner — reads MESSAGE safely from the environment.

This script is called by the container entrypoint to process a single message.
It reads MESSAGE directly from os.environ, completely avoiding shell argument
interpolation of user-controlled content.

Usage (called by entrypoint.sh):
    AGENT_NAME=chatbot MESSAGE="Hello" python deploy/oneshot.py
"""

import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.chatbot.main import ChatbotAgent  # noqa: E402
from agents.code_analysis.main import CodeAnalysisAgent  # noqa: E402
from agents.log_analysis.main import LogAnalysisAgent  # noqa: E402
from agents.red_team.main import RedTeamAgent  # noqa: E402
from agents.security_audit.main import SecurityAuditAgent  # noqa: E402
from agents.security_researcher.main import SecurityResearcherAgent  # noqa: E402
from agents.system_admin.main import SystemAdminAgent  # noqa: E402
from agents.task_manager.main import TaskManagerAgent  # noqa: E402
from agents.web_analysis.main import WebAnalysisAgent  # noqa: E402
from agents.website_tester.main import WebsiteTesterAgent  # noqa: E402

logger = logging.getLogger(__name__)

# Mirror of the AGENTS registry in bin/run-agent (class only — no MCP config
# needed for oneshot since process_message handles tool setup internally).
AGENT_CLASSES: dict[str, type] = {
    "chatbot": ChatbotAgent,
    "code-analysis": CodeAnalysisAgent,
    "log-analysis": LogAnalysisAgent,
    "red-team": RedTeamAgent,
    "security": SecurityResearcherAgent,
    "security-audit": SecurityAuditAgent,
    "sysadmin": SystemAdminAgent,
    "tasks": TaskManagerAgent,
    "web-analysis": WebAnalysisAgent,
    "website-tester": WebsiteTesterAgent,
}


async def main() -> None:
    """Read MESSAGE from env, instantiate the agent, and run once."""
    agent_name = os.environ.get("AGENT_NAME", "")
    message = os.environ.get("MESSAGE", "")

    if not agent_name:
        print("ERROR: AGENT_NAME environment variable is required", file=sys.stderr)
        sys.exit(1)
    if not message:
        print("ERROR: MESSAGE environment variable is required", file=sys.stderr)
        sys.exit(1)

    agent_class = AGENT_CLASSES.get(agent_name)
    if agent_class is None:
        print(
            f"ERROR: Unknown agent '{agent_name}'. Available: {', '.join(sorted(AGENT_CLASSES))}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        agent = agent_class()
        print(f"Running {agent_class.__name__}...\n")
        response = await agent.process_message(message)
        print(response)
        print("\n---")
        print(f"Tokens: {agent.total_input_tokens:,} input, {agent.total_output_tokens:,} output")
    except ValueError as e:
        print(f"\nConfiguration error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        logger.exception("Fatal error in oneshot mode")
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
