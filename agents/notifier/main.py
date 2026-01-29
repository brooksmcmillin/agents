"""Main notification script.

Fetches open tasks from remote MCP server and sends Slack notifications.

Uses shared token storage (~/.agents/tokens/) so you can authenticate
once via an interactive agent and the notifier will reuse those tokens.
"""

import asyncio
import os
from datetime import datetime, timedelta

from agent_framework.tools import send_slack_message

from shared import BatchAgent, parse_priority, parse_task_result


class TaskNotifier(BatchAgent):
    """Batch agent that fetches tasks and sends Slack notifications."""

    def get_name(self) -> str:
        return "TaskNotifier"

    async def execute(self) -> None:
        webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        if not webhook_url:
            print("\nError: SLACK_WEBHOOK_URL not set")
            print("Please add it to your .env file:")
            print("SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL")
            return

        # Fetch tasks
        overdue, today, upcoming = await self._fetch_tasks()

        # Format message
        message = _format_task_message(overdue, today, upcoming)

        # Send to Slack using the shared tool
        result = await send_slack_message(
            text=message,
            webhook_url=webhook_url,
            username="Task Notifier",
            icon_emoji=":bell:",
        )

        if result.get("success"):
            print("\nNotification sent successfully!")
            print("\nMessage preview:")
            print("-" * 60)
            print(message)
            print("-" * 60)
        else:
            print(f"\nFailed to send notification: {result.get('message')}")

    async def _fetch_tasks(self) -> tuple[list[dict], list[dict], list[dict]]:
        """Fetch overdue, today, and upcoming tasks from MCP server."""
        today = datetime.now().date()
        today_str = today.isoformat()
        tomorrow_str = (today + timedelta(days=1)).isoformat()
        upcoming_end = (today + timedelta(days=3)).isoformat()

        overdue_result = await self.call_tool("get_tasks", {"status": "overdue"})
        overdue_tasks = parse_task_result(overdue_result)

        today_result = await self.call_tool(
            "get_tasks",
            {"status": "pending", "start_date": today_str, "end_date": today_str},
        )
        today_tasks = parse_task_result(today_result)

        upcoming_result = await self.call_tool(
            "get_tasks",
            {"status": "pending", "start_date": tomorrow_str, "end_date": upcoming_end},
        )
        upcoming_tasks = parse_task_result(upcoming_result)

        return overdue_tasks, today_tasks, upcoming_tasks


def _format_task_message(overdue: list[dict], today: list[dict], upcoming: list[dict]) -> str:
    """Format task data into a Slack message."""
    parts = []

    now = datetime.now()
    parts.append(f"*Task Update - {now.strftime('%A, %B %d, %Y at %I:%M %p')}*\n")

    if overdue:
        parts.append(f"\n:warning: *{len(overdue)} Overdue Task{'s' if len(overdue) != 1 else ''}*")
        for task in overdue[:5]:
            title = task.get("title", "Untitled")
            due = task.get("due_date", "No due date")
            priority = parse_priority(task.get("priority"))
            emoji = ":exclamation:" if priority >= 8 else ":small_orange_diamond:"
            parts.append(f"{emoji} {title} (due: {due})")
        if len(overdue) > 5:
            parts.append(f"...and {len(overdue) - 5} more")

    if today:
        parts.append(f"\n:calendar: *{len(today)} Task{'s' if len(today) != 1 else ''} Due Today*")
        for task in today[:5]:
            title = task.get("title", "Untitled")
            priority = parse_priority(task.get("priority"))
            emoji = ":star:" if priority >= 8 else ":small_blue_diamond:"
            parts.append(f"{emoji} {title}")
        if len(today) > 5:
            parts.append(f"...and {len(today) - 5} more")

    if upcoming:
        parts.append(
            f"\n:crystal_ball: *{len(upcoming)} Upcoming Task{'s' if len(upcoming) != 1 else ''} (Next 3 Days)*"
        )
        for task in upcoming[:5]:
            title = task.get("title", "Untitled")
            due = task.get("due_date", "No due date")
            parts.append(f"• {title} (due: {due})")
        if len(upcoming) > 5:
            parts.append(f"...and {len(upcoming) - 5} more")

    if not overdue and not today:
        if not upcoming:
            parts.append("\n:white_check_mark: *All caught up! No urgent tasks.*")
        else:
            parts.append("\n:thumbsup: *No overdue or today tasks. You're on track!*")

    return "\n".join(parts)


async def main():
    """Main entry point for task notifier."""
    try:
        notifier = TaskNotifier()
        await notifier.run()
    except Exception as e:
        print(f"\nError: {e}")


if __name__ == "__main__":
    asyncio.run(main())
