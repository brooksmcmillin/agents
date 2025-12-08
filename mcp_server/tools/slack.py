"""Slack webhook tool.

This tool sends messages to Slack using incoming webhooks.
Useful for posting content, notifications, and updates to Slack channels.
"""

import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


async def send_slack_message(
    text: str,
    webhook_url: str | None = None,
    username: str | None = None,
    icon_emoji: str | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    """
    Send a message to Slack using an incoming webhook.

    This tool sends messages to Slack channels via incoming webhooks. The webhook
    URL can be provided directly or will be loaded from the SLACK_WEBHOOK_URL
    environment variable. The webhook URL determines the default channel, but can
    be overridden. Supports custom usernames and emoji icons.

    Args:
        text: The message text to send (supports Slack markdown formatting)
        webhook_url: Optional Slack incoming webhook URL. If not provided, uses
            SLACK_WEBHOOK_URL from environment (e.g., https://hooks.slack.com/services/...)
        username: Optional custom username for the message (overrides webhook default)
        icon_emoji: Optional emoji icon (e.g., ":robot_face:", ":tada:")
        channel: Optional channel override (e.g., "#general", "@username")

    Returns:
        Dictionary containing:
            - success: Boolean indicating if message was sent successfully
            - message: Success or error message
            - webhook_url: The webhook URL used (sanitized for logging)

    Raises:
        ValueError: If webhook URL is not provided and not set in environment
        ValueError: If webhook URL is invalid
        httpx.HTTPError: If Slack API returns an error
    """
    logger.info("Sending message to Slack webhook")

    # Use provided webhook_url or fall back to environment variable
    if not webhook_url:
        webhook_url = settings.slack_webhook_url
        if not webhook_url:
            raise ValueError(
                "webhook_url is required. Either provide it as a parameter or set "
                "SLACK_WEBHOOK_URL in your environment/.env file"
            )

    if not webhook_url.startswith("https://hooks.slack.com/"):
        raise ValueError(
            "Invalid Slack webhook URL. Must start with 'https://hooks.slack.com/'"
        )

    if not text:
        raise ValueError("text is required")

    # Build Slack message payload
    payload: dict[str, Any] = {
        "text": text,
    }

    # Add optional parameters
    if username:
        payload["username"] = username

    if icon_emoji:
        # Ensure emoji is wrapped in colons
        if not icon_emoji.startswith(":"):
            icon_emoji = f":{icon_emoji}"
        if not icon_emoji.endswith(":"):
            icon_emoji = f"{icon_emoji}:"
        payload["icon_emoji"] = icon_emoji

    if channel:
        payload["channel"] = channel

    try:
        # Send POST request to Slack webhook
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook_url,
                json=payload,
            )
            response.raise_for_status()

        # Slack webhooks return "ok" on success
        if response.text == "ok":
            logger.info("Successfully sent message to Slack")
            return {
                "success": True,
                "message": "Message sent successfully to Slack",
                "webhook_url": webhook_url[:50] + "...",  # Sanitized for logging
            }
        else:
            logger.warning(f"Unexpected response from Slack: {response.text}")
            return {
                "success": False,
                "message": f"Unexpected response from Slack: {response.text}",
                "webhook_url": webhook_url[:50] + "...",
            }

    except httpx.HTTPError as e:
        logger.error(f"Failed to send message to Slack: {e}")
        raise ValueError(f"Failed to send message to Slack: {e}")

    except Exception as e:
        logger.error(f"Error sending Slack message: {e}")
        raise
