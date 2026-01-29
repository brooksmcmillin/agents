"""Example: Using the Slack webhook tool.

This example demonstrates how to send messages to Slack using the send_slack_message tool.
You'll need a Slack incoming webhook URL to use this example.

To get a webhook URL:
1. Go to https://api.slack.com/messaging/webhooks
2. Create a new app or use an existing one
3. Enable Incoming Webhooks
4. Create a webhook for your desired channel
5. Copy the webhook URL
"""

import asyncio

from agent_framework.tools import send_slack_message


async def main():
    """Example usage of the Slack webhook tool."""

    # Option 1: Use webhook URL from environment variable (SLACK_WEBHOOK_URL)
    # Just provide the text - webhook URL will be loaded from .env
    print("Sending basic message using environment variable...")
    result = await send_slack_message(
        text="Hello from the PR Agent! 🚀",
    )
    print(f"Result: {result}")

    # Option 2: Explicitly provide webhook URL (overrides environment variable)
    webhook_url = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
    print("\nSending message with explicit webhook URL...")
    result = await send_slack_message(
        text="Using explicit webhook URL",
        webhook_url=webhook_url,
    )
    print(f"Result: {result}")

    # Message with custom username and emoji (uses environment webhook)
    print("\nSending message with custom username and emoji...")
    result = await send_slack_message(
        text="Content analysis complete! Your SEO score is 8/10.",
        username="PR Agent Bot",
        icon_emoji="robot_face",
    )
    print(f"Result: {result}")

    # Message with channel override (uses environment webhook)
    print("\nSending message to specific channel...")
    result = await send_slack_message(
        text="Weekly content report is ready!",
        username="Content Reporter",
        icon_emoji="chart_with_upwards_trend",
        channel="#marketing",  # Override default channel
    )
    print(f"Result: {result}")

    # Formatted message using Slack markdown (uses environment webhook)
    print("\nSending formatted message...")
    formatted_text = """
*Content Analysis Results*

📊 *SEO Score:* 8/10
✍️ *Readability:* Excellent
🎯 *Engagement Potential:* High

_Recommendations:_
• Add more internal links
• Optimize meta description
• Include more subheadings

View full report: https://example.com/report
"""
    result = await send_slack_message(
        text=formatted_text,
        username="Content Analyzer",
        icon_emoji="bar_chart",
    )
    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
