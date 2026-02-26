"""Scheduled morning/evening routines for the Task Manager agent.

Runs the TaskManagerAgent in one-shot mode with a structured prompt
to perform routine task management operations.

Usage:
    uv run python -m agents.task_manager.scheduler morning
    uv run python -m agents.task_manager.scheduler evening
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

MORNING_PROMPT = """Run the morning task management routine. Complete ALL of these steps:

1. **Review overdue tasks**: Use get_tasks with status="overdue" to find all overdue tasks.
   For each overdue task, reschedule it to a realistic date in the next 1-2 weeks.
   Spread tasks evenly — don't overload any single day.

2. **Classify unclassified tasks**: Use get_agent_tasks(unclassified_only=True) to find
   tasks that haven't been classified yet. For each one, call classify_task with the
   appropriate action_type, agent_actionable, and autonomy_tier.

3. **Pre-research today's tasks**: Use get_tasks to find tasks due today.
   For each task, use fetch_web_content or analyze_website to gather relevant context.
   Add findings via add_agent_note.

4. **Send daily briefing**: Compose a morning briefing that includes:
   - Number of tasks due today (with titles)
   - Number of overdue tasks rescheduled
   - Number of tasks classified
   - Any blocked tasks that need attention
   Send this briefing via send_slack_message AND send_sms_to_admin.

Complete all steps and report what was done."""

EVENING_PROMPT = """Run the evening task management routine. Complete ALL of these steps:

1. **Review completed tasks**: Use get_tasks with status="completed" to see what was
   accomplished today. Note any patterns or achievements.

2. **Classify new tasks**: Use get_agent_tasks(unclassified_only=True) to find any
   tasks added during the day that haven't been classified. Classify each one.

3. **Update priorities**: Review tomorrow's tasks and adjust priorities based on
   what was (or wasn't) completed today. Use update_task to adjust as needed.

4. **Check blocked tasks**: Use get_agent_tasks to find tasks with agent_status="blocked".
   Review blocking reasons and see if any can be unblocked.

5. **Send EOD summary**: Compose an end-of-day summary that includes:
   - Tasks completed today
   - Tasks remaining/carried over
   - Tasks rescheduled
   - Any items needing attention tomorrow
   Send this summary via send_slack_message AND send_sms_to_admin.

Complete all steps and report what was done."""

# Truncation lengths for log previews vs notification summaries
LOG_PREVIEW_LEN = 500
NOTIFICATION_SUMMARY_LEN = 300


def _sanitize_error(exc: Exception) -> str:
    """Produce a safe error description for external notifications.

    Raw exception messages can leak sensitive data (API keys, connection
    strings, etc.), so we only expose the exception type and a truncated
    message for notifications. Full tracebacks are logged locally.
    """
    type_name = type(exc).__name__
    short_msg = str(exc)[:120]
    return f"{type_name}: {short_msg}"


async def _run_routine(name: str, prompt: str) -> None:
    """Create a TaskManagerAgent and run a routine prompt.

    Args:
        name: Routine name for logging (e.g. "Morning", "Evening").
        prompt: The prompt to send to the agent.
    """
    from shared.constants import DEFAULT_MCP_SERVER_URL, ENV_MCP_SERVER_URL
    from shared.notifications import notify_error, notify_routine_complete

    from .main import TaskManagerAgent

    mcp_urls: list[str] = [os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)]
    # No prefer_device_flow — the scheduler runs headlessly via systemd,
    # so it relies on pre-stored OAuth tokens (authenticate interactively
    # first via `uv run python scripts/mcp_auth.py`).
    mcp_client_config: dict[str, object] = {}

    logger.info(f"Starting {name} routine")

    try:
        agent = TaskManagerAgent(
            mcp_urls=mcp_urls,
            mcp_client_config=mcp_client_config,
        )
        response = await agent.process_message(prompt)
        logger.info(f"{name} routine completed")
        logger.info(f"Response: {response[:LOG_PREVIEW_LEN]}")

        await notify_routine_complete(
            routine_name=name,
            summary=response[:NOTIFICATION_SUMMARY_LEN],
            agent_name="TaskScheduler",
        )

    except Exception as e:
        logger.exception(f"{name} routine failed")
        await notify_error(
            context=f"{name} routine",
            error=_sanitize_error(e),
            agent_name="TaskScheduler",
        )
        raise


async def run_morning_routine() -> None:
    """Run the morning task management routine."""
    await _run_routine("Morning", MORNING_PROMPT)


async def run_evening_routine() -> None:
    """Run the evening task management routine."""
    await _run_routine("Evening", EVENING_PROMPT)


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2 or sys.argv[1] not in ("morning", "evening"):
        print("Usage: uv run python -m agents.task_manager.scheduler morning|evening")
        sys.exit(1)

    routine = sys.argv[1]
    if routine == "morning":
        asyncio.run(run_morning_routine())
    else:
        asyncio.run(run_evening_routine())


if __name__ == "__main__":
    main()
