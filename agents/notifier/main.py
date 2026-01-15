"""Main notification script.

Fetches open tasks from remote MCP server and sends Slack notifications.

Uses shared token storage (~/.agents/tokens/) so you can authenticate
once via an interactive agent and the notifier will reuse those tokens.
"""

import asyncio
import os
from datetime import datetime, timedelta

import httpx

from agent_framework.core.remote_mcp_client import RemoteMCPClient

from shared import (
    DEFAULT_MCP_SERVER_URL,
    ENV_MCP_SERVER_URL,
    get_valid_token_for_mcp,
    parse_priority,
    parse_task_result,
    setup_logging,
)

# Configure logging
logger = setup_logging(__name__)


def format_task_message(
    overdue: list[dict], today: list[dict], upcoming: list[dict]
) -> str:
    """Format task data into a Slack message.

    Args:
        overdue: List of overdue tasks
        today: List of tasks due today
        upcoming: List of tasks due in the next 3 days

    Returns:
        Formatted Slack message with markdown
    """
    message_parts = []

    # Header
    now = datetime.now()
    message_parts.append(
        f"*Task Update - {now.strftime('%A, %B %d, %Y at %I:%M %p')}*\n"
    )

    # Overdue tasks
    if overdue:
        message_parts.append(
            f"\n:warning: *{len(overdue)} Overdue Task{'s' if len(overdue) != 1 else ''}*"
        )
        for task in overdue[:5]:  # Limit to 5 to avoid spam
            title = task.get("title", "Untitled")
            due = task.get("due_date", "No due date")
            priority = parse_priority(task.get("priority"))
            priority_emoji = (
                ":exclamation:" if priority >= 8 else ":small_orange_diamond:"
            )
            message_parts.append(f"{priority_emoji} {title} (due: {due})")

        if len(overdue) > 5:
            message_parts.append(f"...and {len(overdue) - 5} more")

    # Today's tasks
    if today:
        message_parts.append(
            f"\n:calendar: *{len(today)} Task{'s' if len(today) != 1 else ''} Due Today*"
        )
        for task in today[:5]:
            title = task.get("title", "Untitled")
            priority = parse_priority(task.get("priority"))
            priority_emoji = ":star:" if priority >= 8 else ":small_blue_diamond:"
            message_parts.append(f"{priority_emoji} {title}")

        if len(today) > 5:
            message_parts.append(f"...and {len(today) - 5} more")

    # Upcoming tasks (next 3 days)
    if upcoming:
        message_parts.append(
            f"\n:crystal_ball: *{len(upcoming)} Upcoming Task{'s' if len(upcoming) != 1 else ''} (Next 3 Days)*"
        )
        for task in upcoming[:5]:
            title = task.get("title", "Untitled")
            due = task.get("due_date", "No due date")
            message_parts.append(f"• {title} (due: {due})")

        if len(upcoming) > 5:
            message_parts.append(f"...and {len(upcoming) - 5} more")

    # Summary if nothing urgent
    if not overdue and not today:
        if not upcoming:
            message_parts.append(
                "\n:white_check_mark: *All caught up! No urgent tasks.*"
            )
        else:
            message_parts.append(
                "\n:thumbsup: *No overdue or today tasks. You're on track!*"
            )

    return "\n".join(message_parts)


async def fetch_tasks(
    client: RemoteMCPClient,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch overdue, today, and upcoming tasks from MCP server.

    Args:
        client: Connected RemoteMCPClient instance

    Returns:
        Tuple of (overdue_tasks, today_tasks, upcoming_tasks)
    """
    today = datetime.now().date()
    today_str = today.isoformat()
    tomorrow_str = (today + timedelta(days=1)).isoformat()
    upcoming_end = (today + timedelta(days=3)).isoformat()

    # Fetch overdue tasks (due before today, status pending or in_progress)
    logger.info("Fetching overdue tasks...")
    overdue_result = await client.call_tool(
        "get_tasks",
        {
            "status": "overdue",
        },
    )

    overdue_tasks = parse_task_result(overdue_result)

    # Fetch tasks due today
    logger.info("Fetching tasks due today...")
    today_result = await client.call_tool(
        "get_tasks",
        {
            "status": "pending",
            "start_date": today_str,
            "end_date": today_str,
        },
    )

    today_tasks = parse_task_result(today_result)

    # Fetch upcoming tasks (next 3 days, excluding today)
    logger.info("Fetching upcoming tasks...")
    upcoming_result = await client.call_tool(
        "get_tasks",
        {
            "status": "pending",
            "start_date": tomorrow_str,
            "end_date": upcoming_end,
        },
    )

    upcoming_tasks = parse_task_result(upcoming_result)

    logger.info(
        f"Found {len(overdue_tasks)} overdue, {len(today_tasks)} today, {len(upcoming_tasks)} upcoming"
    )

    return overdue_tasks, today_tasks, upcoming_tasks


async def send_slack_notification(message: str, webhook_url: str) -> bool:
    """Send notification to Slack via webhook.

    Args:
        message: Formatted message text
        webhook_url: Slack webhook URL

    Returns:
        True if successful, False otherwise
    """
    payload = {
        "text": message,
        "username": "Task Notifier",
        "icon_emoji": ":bell:",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()

        if response.text == "ok":
            logger.info("Successfully sent Slack notification")
            return True
        else:
            logger.warning(f"Unexpected Slack response: {response.text}")
            return False

    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
        return False


async def main():
    """Main entry point for task notifier."""
    try:
        # Get configuration from environment
        mcp_url = os.getenv(ENV_MCP_SERVER_URL, DEFAULT_MCP_SERVER_URL)
        webhook_url = os.getenv("SLACK_WEBHOOK_URL")

        if not webhook_url:
            logger.error("SLACK_WEBHOOK_URL not set in environment")
            print("\nError: SLACK_WEBHOOK_URL not set")
            print("Please add it to your .env file:")
            print("SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL")
            return

        # Get token from shared storage (with automatic refresh)
        auth_token = await get_valid_token_for_mcp(mcp_url)

        if not auth_token:
            logger.error("No valid token available")
            print("\nError: No valid authentication token found")
            print("\nTo authenticate, run an interactive agent first:")
            print("  uv run python -m agents.pr_agent.main")
            print("  uv run python -m agents.task_manager.main")
            print("\nThis will open a browser for OAuth login. Once authenticated,")
            print("the notifier will automatically use and refresh those tokens.")
            return

        # Connect to remote MCP server with token from storage
        logger.info(f"Connecting to MCP server at {mcp_url}...")
        async with RemoteMCPClient(
            mcp_url, auth_token=auth_token, enable_oauth=False
        ) as client:
            logger.info("Connected successfully")

            # Fetch tasks
            overdue, today, upcoming = await fetch_tasks(client)

            # Format message
            message = format_task_message(overdue, today, upcoming)

            # Send to Slack
            logger.info("Sending Slack notification...")
            success = await send_slack_notification(message, webhook_url)

            if success:
                print("\nNotification sent successfully!")
                print("\nMessage preview:")
                print("-" * 60)
                print(message)
                print("-" * 60)
            else:
                print("\nFailed to send notification. Check logs for details.")

    except Exception as e:
        logger.exception(f"Error in notification script: {e}")
        print(f"\nError: {e}")
        return


if __name__ == "__main__":
    """Run the task notifier."""
    asyncio.run(main())
