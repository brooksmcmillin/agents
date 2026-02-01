"""Twilio SMS tool.

This tool sends SMS messages to the admin using Twilio's REST API.
Uses the same Twilio credentials as the chasm voice package.

For security, SMS messages can only be sent to the configured admin phone number
(ADMIN_PHONE_NUMBER environment variable), similar to how send_agent_report
only sends emails to the admin email address.
"""

import logging
import re
from typing import Any

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

# E.164 phone number format: +[country code][number]
E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")


def _validate_phone_number(phone: str, field_name: str) -> str:
    """Validate and normalize phone number to E.164 format.

    Args:
        phone: Phone number to validate
        field_name: Field name for error messages

    Returns:
        Normalized phone number in E.164 format

    Raises:
        ValueError: If phone number is invalid
    """
    # Strip whitespace and common separators
    normalized = re.sub(r"[\s\-\(\)\.]", "", phone)

    # Add + if missing and starts with country code
    if not normalized.startswith("+"):
        # Assume US/Canada if 10 digits
        if len(normalized) == 10 and normalized.isdigit():
            normalized = f"+1{normalized}"
        elif normalized.startswith("1") and len(normalized) == 11:
            normalized = f"+{normalized}"
        else:
            normalized = f"+{normalized}"

    if not E164_PATTERN.match(normalized):
        raise ValueError(
            f"Invalid {field_name}: '{phone}'. Must be in E.164 format "
            "(e.g., +15551234567) or a 10-digit US number."
        )

    return normalized


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

    Raises:
        ValueError: If required configuration is missing
    """
    # Validate admin phone number is configured
    if not settings.admin_phone_number:
        return {
            "success": False,
            "error": "ADMIN_PHONE_NUMBER environment variable is not configured. "
            "Set it to the phone number where agent notifications should be sent.",
        }

    # Validate Twilio credentials
    account_sid = settings.twilio_account_sid
    auth_token = settings.twilio_auth_token

    if not account_sid:
        return {
            "success": False,
            "error": "TWILIO_ACCOUNT_SID is required. Set it in your environment or .env file. "
            "Get it from: https://console.twilio.com/",
        }

    if not auth_token:
        return {
            "success": False,
            "error": "TWILIO_AUTH_TOKEN is required. Set it in your environment or .env file. "
            "Get it from: https://console.twilio.com/",
        }

    if not settings.twilio_phone_number:
        return {
            "success": False,
            "error": "TWILIO_PHONE_NUMBER is required. Set it in your environment or .env file.",
        }

    # Validate and normalize phone numbers
    try:
        to_normalized = _validate_phone_number(
            settings.admin_phone_number, "ADMIN_PHONE_NUMBER"
        )
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

    logger.info(f"Sending SMS to admin from agent: {agent_name or 'unknown'}")

    # Build request payload
    payload = {
        "To": to_normalized,
        "From": from_normalized,
        "Body": message_body,
    }

    # Twilio REST API endpoint
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                data=payload,
                auth=(account_sid, auth_token),
            )

            # Parse response
            result = response.json()

            if response.status_code == 201:
                # Calculate approximate segments (160 chars for GSM-7, 70 for Unicode)
                has_unicode = any(ord(c) > 127 for c in message_body)
                segment_size = 70 if has_unicode else 160
                segments = (len(message_body) + segment_size - 1) // segment_size

                logger.info(
                    f"SMS queued successfully: {result.get('sid')} "
                    f"({segments} segment{'s' if segments > 1 else ''})"
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
            else:
                error_code = result.get("code")
                error_message = result.get("message", "Unknown error")
                logger.error(f"Twilio API error: {error_code} - {error_message}")

                return {
                    "success": False,
                    "error": f"Twilio error {error_code}: {error_message}",
                    "to": to_normalized,
                    "from": from_normalized,
                }

    except httpx.HTTPError as e:
        logger.error(f"HTTP error sending SMS: {e}")
        return {
            "success": False,
            "error": f"Failed to send SMS: {e}",
        }

    except Exception as e:
        logger.error(f"Error sending SMS: {e}")
        return {
            "success": False,
            "error": f"Unexpected error: {e}",
        }


async def get_sms_status(message_sid: str) -> dict[str, Any]:
    """
    Get the delivery status of a sent SMS message.

    This tool retrieves the current status of a previously sent SMS message
    using its message SID. Useful for tracking delivery confirmation.

    Args:
        message_sid: The Twilio message SID (starts with 'SM' or 'MM')

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

    Raises:
        ValueError: If credentials are missing or message_sid is invalid
    """
    logger.info(f"Getting status for message: {message_sid}")

    # Validate credentials
    account_sid = settings.twilio_account_sid
    auth_token = settings.twilio_auth_token

    if not account_sid:
        return {
            "success": False,
            "error": "TWILIO_ACCOUNT_SID is required. Set it in your environment or .env file.",
        }

    if not auth_token:
        return {
            "success": False,
            "error": "TWILIO_AUTH_TOKEN is required. Set it in your environment or .env file.",
        }

    # Validate message SID format
    if not message_sid or not message_sid.startswith(("SM", "MM")):
        return {
            "success": False,
            "error": f"Invalid message_sid: '{message_sid}'. "
            "Must be a Twilio message SID starting with 'SM' or 'MM'.",
        }

    # Twilio REST API endpoint
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages/{message_sid}.json"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                auth=(account_sid, auth_token),
            )

            result = response.json()

            if response.status_code == 200:
                logger.info(f"Message status: {result.get('status')}")

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
            else:
                error_code = result.get("code")
                error_message = result.get("message", "Unknown error")
                logger.error(f"Twilio API error: {error_code} - {error_message}")

                return {
                    "success": False,
                    "error": f"Twilio error {error_code}: {error_message}",
                    "message_sid": message_sid,
                }

    except httpx.HTTPError as e:
        logger.error(f"HTTP error getting SMS status: {e}")
        return {
            "success": False,
            "error": f"Failed to get SMS status: {e}",
        }

    except Exception as e:
        logger.error(f"Error getting SMS status: {e}")
        return {
            "success": False,
            "error": f"Unexpected error: {e}",
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
