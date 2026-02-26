"""Multi-channel notification utilities.

Sends notifications via both Slack and SMS. Each channel is independent —
a failure in one does not block the other.
"""

import logging

from agent_framework.tools.slack import send_slack_message
from agent_framework.tools.twilio_sms import send_sms_to_admin

logger = logging.getLogger(__name__)


async def notify_task_completion(
    task_title: str,
    task_id: str,
    summary: str,
    agent_name: str = "TaskManager",
) -> None:
    """Send task completion notification via Slack and SMS.

    Args:
        task_title: Title of the completed task.
        task_id: ID of the completed task.
        summary: Brief summary of what was done.
        agent_name: Name of the agent that completed the task.
    """
    message = f"Task completed: {task_title} (#{task_id})\n{summary}"

    try:
        await send_slack_message(
            text=message,
            username=agent_name,
            icon_emoji=":white_check_mark:",
        )
    except Exception:
        logger.exception("Failed to send Slack notification for task completion")

    try:
        await send_sms_to_admin(
            body=message,
            agent_name=agent_name,
        )
    except Exception:
        logger.exception("Failed to send SMS notification for task completion")


async def notify_routine_complete(
    routine_name: str,
    summary: str,
    agent_name: str = "TaskScheduler",
) -> None:
    """Send routine completion notification via Slack and SMS.

    Args:
        routine_name: Name of the routine (e.g. "Morning", "Evening").
        summary: Brief summary of the routine results.
        agent_name: Name of the agent that ran the routine.
    """
    message = f"{routine_name} routine complete\n{summary}"

    try:
        await send_slack_message(
            text=message,
            username=agent_name,
            icon_emoji=":calendar:",
        )
    except Exception:
        logger.exception("Failed to send Slack notification for routine completion")

    try:
        await send_sms_to_admin(
            body=message,
            agent_name=agent_name,
        )
    except Exception:
        logger.exception("Failed to send SMS notification for routine completion")


async def notify_error(
    context: str,
    error: str,
    agent_name: str = "TaskScheduler",
) -> None:
    """Send error notification via Slack and SMS.

    Args:
        context: What was happening when the error occurred.
        error: Error message or description.
        agent_name: Name of the agent that encountered the error.
    """
    message = f"Error in {context}: {error}"

    try:
        await send_slack_message(
            text=message,
            username=agent_name,
            icon_emoji=":x:",
        )
    except Exception:
        logger.exception("Failed to send Slack error notification")

    try:
        await send_sms_to_admin(
            body=message,
            agent_name=agent_name,
        )
    except Exception:
        logger.exception("Failed to send SMS error notification")
