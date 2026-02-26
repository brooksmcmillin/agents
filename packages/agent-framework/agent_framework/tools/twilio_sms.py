"""Twilio SMS tool.

This tool sends SMS messages to the admin using Twilio's REST API.
Uses the same Twilio credentials as the chasm voice package.

For security, SMS messages can only be sent to the configured admin phone number
(ADMIN_PHONE_NUMBER environment variable), similar to how send_agent_report
only sends emails to the admin email address.
"""

import logging
from typing import Any
from urllib.parse import quote

from ..core.config import settings
from .twilio_utils import (
    get_twilio_resource,
    post_twilio_message,
    validate_twilio_credentials,
)
from .twilio_utils import (
    validate_message_sid as _validate_message_sid,
)
from .twilio_utils import (
    validate_phone_number as _validate_phone_number,
)

logger = logging.getLogger(__name__)


async def send_sms_to_admin(
    body: str,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """
    Send an SMS message to the admin using Twilio.

    This tool sends SMS messages via Twilio's REST API to the configured admin
    phone number. For security, messages can ONLY be sent to ADMIN_PHONE_NUMBER.
    This prevents agents from sending unsolicited messages to arbitrary numbers.

    Similar to send_agent_report for email, this tool is designed for agents to
    send notifications, alerts, and status updates to the system administrator.

    IMPORTANT: This tool requires:
    1. ADMIN_PHONE_NUMBER environment variable set (recipient)
    2. TWILIO_PHONE_NUMBER environment variable set (sender)
    3. TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN for authentication

    The agent_name parameter is automatically injected by the Agent class.

    Args:
        body: The message text to send (max 1600 characters for standard SMS,
            will be split into multiple segments if longer than 160 characters)
        agent_name: Agent name (auto-injected by Agent class). Included in the
            message prefix for identification.

    Returns:
        Dictionary containing:
            - success: Boolean indicating if message was queued successfully
            - message_sid: Twilio message SID for tracking
            - to: Admin phone number
            - from: Twilio phone number
            - status: Message status (queued, sending, sent, delivered, failed)
            - segments: Number of SMS segments (messages > 160 chars are split)
            - error: Error message if failed
    """
    # Validate admin phone number is configured
    if not settings.admin_phone_number:
        return {
            "success": False,
            "error": "ADMIN_PHONE_NUMBER environment variable is not configured. "
            "Set it to the phone number where agent notifications should be sent.",
        }

    # Validate Twilio credentials
    creds = validate_twilio_credentials()
    if isinstance(creds, str):
        return {"success": False, "error": creds}

    if not settings.twilio_phone_number:
        return {
            "success": False,
            "error": "TWILIO_PHONE_NUMBER is required. Set it in your environment or .env file.",
        }

    # Validate and normalize phone numbers
    try:
        to_normalized = _validate_phone_number(settings.admin_phone_number, "ADMIN_PHONE_NUMBER")
        from_normalized = _validate_phone_number(
            settings.twilio_phone_number, "TWILIO_PHONE_NUMBER"
        )
    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
        }

    # Validate body
    if not body:
        return {
            "success": False,
            "error": "body is required - cannot send empty SMS",
        }

    # Add agent prefix if provided
    if agent_name:
        safe_agent_name = agent_name.replace("_", "-").title()
        message_body = f"[{safe_agent_name}] {body}"
    else:
        message_body = body

    if len(message_body) > 1600:
        return {
            "success": False,
            "error": f"Message body too long ({len(message_body)} characters). "
            "Maximum is 1600 characters for a single API call.",
        }

    logger.info("Sending SMS to admin from agent: %s", agent_name or "unknown")

    # Send via shared helper
    post_result = await post_twilio_message(
        credentials=creds,
        to=to_normalized,
        from_number=from_normalized,
        body=message_body,
    )

    if not post_result["success"]:
        return {
            "success": False,
            "error": post_result["error"],
            "to": to_normalized,
            "from": from_normalized,
        }

    result = post_result["result"]

    # Calculate approximate segments (160 chars for GSM-7, 70 for Unicode)
    has_unicode = any(ord(c) > 127 for c in message_body)
    segment_size = 70 if has_unicode else 160
    segments = (len(message_body) + segment_size - 1) // segment_size

    logger.info(
        "SMS queued successfully: %s (%d segment%s)",
        result.get("sid"),
        segments,
        "s" if segments > 1 else "",
    )

    return {
        "success": True,
        "message_sid": result.get("sid"),
        "to": result.get("to"),
        "from": result.get("from"),
        "status": result.get("status"),
        "segments": segments,
        "date_created": result.get("date_created"),
        "agent_name": agent_name,
    }


async def get_sms_status(message_sid: str) -> dict[str, Any]:
    """
    Get the delivery status of a sent SMS message.

    This tool retrieves the current status of a previously sent SMS message
    using its message SID. Useful for tracking delivery confirmation.

    Args:
        message_sid: The Twilio message SID (format: SM or MM followed by 32 hex chars)

    Returns:
        Dictionary containing:
            - success: Boolean indicating if status was retrieved
            - message_sid: The message SID
            - status: Current status (queued, sending, sent, delivered, undelivered, failed)
            - to: Recipient phone number
            - from: Sender phone number
            - date_sent: When the message was sent
            - error_code: Error code if failed
            - error_message: Error description if failed
    """
    logger.info("Getting status for message: %s", message_sid)

    # Validate credentials
    creds = validate_twilio_credentials()
    if isinstance(creds, str):
        return {"success": False, "error": creds}

    # Validate message SID format with strict pattern matching
    if not message_sid or not _validate_message_sid(message_sid):
        return {
            "success": False,
            "error": f"Invalid message_sid: '{message_sid}'. "
            "Must be a Twilio message SID (SM or MM followed by 32 hex characters).",
        }

    # Twilio REST API endpoint - URL encode both IDs to prevent injection
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{quote(creds.account_sid, safe='')}/"
        f"Messages/{quote(message_sid, safe='')}.json"
    )

    # Fetch via shared helper
    get_result = await get_twilio_resource(credentials=creds, url=url)

    if not get_result["success"]:
        return {
            "success": False,
            "error": get_result["error"],
            "message_sid": message_sid,
        }

    result = get_result["result"]
    logger.info("Message status: %s", result.get("status"))

    return {
        "success": True,
        "message_sid": result.get("sid"),
        "status": result.get("status"),
        "to": result.get("to"),
        "from": result.get("from"),
        "body": result.get("body"),
        "date_sent": result.get("date_sent"),
        "date_updated": result.get("date_updated"),
        "error_code": result.get("error_code"),
        "error_message": result.get("error_message"),
    }


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "send_sms_to_admin",
        "description": (
            "Send an SMS text message to the admin using Twilio. "
            "Use this to send notifications, alerts, and status updates to the system administrator. "
            "For security, messages can ONLY be sent to the configured ADMIN_PHONE_NUMBER. "
            "The agent name is automatically prefixed to the message for identification. "
            "Messages longer than 160 characters are automatically split into multiple segments. "
            "Returns a message SID that can be used to track delivery status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "body": {
                    "type": "string",
                    "description": (
                        "The message text to send. Max 1600 characters. "
                        "Messages over 160 characters are split into multiple segments. "
                        "The agent name will be automatically prefixed."
                    ),
                },
            },
            "required": ["body"],
        },
        "handler": send_sms_to_admin,
    },
    {
        "name": "get_sms_status",
        "description": (
            "Get the delivery status of a previously sent SMS message. "
            "Use this to confirm if a message was delivered or check for errors. "
            "Requires the message SID returned from send_sms_to_admin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_sid": {
                    "type": "string",
                    "description": (
                        "The Twilio message SID (starts with 'SM' or 'MM') "
                        "returned from send_sms_to_admin"
                    ),
                },
            },
            "required": ["message_sid"],
        },
        "handler": get_sms_status,
    },
]
