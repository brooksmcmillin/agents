"""Twilio SMS tool.

This tool sends SMS messages using Twilio's REST API.
Uses the same Twilio credentials as the chasm voice package.
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


async def send_sms(
    to: str,
    body: str,
    from_number: str | None = None,
    status_callback: str | None = None,
) -> dict[str, Any]:
    """
    Send an SMS message using Twilio.

    This tool sends SMS messages via Twilio's REST API. The Twilio credentials
    (Account SID, Auth Token) and default phone number are loaded from environment
    variables. You can optionally override the 'from' number.

    Args:
        to: Recipient phone number in E.164 format (e.g., +15551234567) or
            10-digit US format (5551234567)
        body: The message text to send (max 1600 characters for standard SMS,
            will be split into multiple segments if longer than 160 characters)
        from_number: Optional sender phone number in E.164 format. If not provided,
            uses TWILIO_PHONE_NUMBER from environment
        status_callback: Optional webhook URL to receive delivery status updates

    Returns:
        Dictionary containing:
            - success: Boolean indicating if message was queued successfully
            - message_sid: Twilio message SID for tracking
            - to: Recipient phone number (normalized)
            - from: Sender phone number
            - status: Message status (queued, sending, sent, delivered, failed)
            - segments: Number of SMS segments (messages > 160 chars are split)
            - error: Error message if failed

    Raises:
        ValueError: If required credentials are missing or phone numbers are invalid
        httpx.HTTPError: If Twilio API returns an error
    """
    logger.info(f"Sending SMS to {to[:6]}***")

    # Validate credentials
    account_sid = settings.twilio_account_sid
    auth_token = settings.twilio_auth_token

    if not account_sid:
        raise ValueError(
            "TWILIO_ACCOUNT_SID is required. Set it in your environment or .env file. "
            "Get it from: https://console.twilio.com/"
        )

    if not auth_token:
        raise ValueError(
            "TWILIO_AUTH_TOKEN is required. Set it in your environment or .env file. "
            "Get it from: https://console.twilio.com/"
        )

    # Validate and normalize phone numbers
    to_normalized = _validate_phone_number(to, "recipient phone number (to)")

    if from_number:
        from_normalized = _validate_phone_number(from_number, "sender phone number (from)")
    else:
        from_normalized = settings.twilio_phone_number
        if not from_normalized:
            raise ValueError(
                "from_number is required. Either provide it as a parameter or set "
                "TWILIO_PHONE_NUMBER in your environment/.env file"
            )
        from_normalized = _validate_phone_number(from_normalized, "TWILIO_PHONE_NUMBER")

    # Validate body
    if not body:
        raise ValueError("body is required - cannot send empty SMS")

    if len(body) > 1600:
        raise ValueError(
            f"Message body too long ({len(body)} characters). "
            "Maximum is 1600 characters for a single API call."
        )

    # Build request payload
    payload = {
        "To": to_normalized,
        "From": from_normalized,
        "Body": body,
    }

    if status_callback:
        payload["StatusCallback"] = status_callback

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
                has_unicode = any(ord(c) > 127 for c in body)
                segment_size = 70 if has_unicode else 160
                segments = (len(body) + segment_size - 1) // segment_size

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
        raise ValueError(f"Failed to send SMS: {e}")

    except Exception as e:
        logger.error(f"Error sending SMS: {e}")
        raise


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
        httpx.HTTPError: If Twilio API returns an error
    """
    logger.info(f"Getting status for message: {message_sid}")

    # Validate credentials
    account_sid = settings.twilio_account_sid
    auth_token = settings.twilio_auth_token

    if not account_sid:
        raise ValueError(
            "TWILIO_ACCOUNT_SID is required. Set it in your environment or .env file."
        )

    if not auth_token:
        raise ValueError(
            "TWILIO_AUTH_TOKEN is required. Set it in your environment or .env file."
        )

    # Validate message SID format
    if not message_sid or not message_sid.startswith(("SM", "MM")):
        raise ValueError(
            f"Invalid message_sid: '{message_sid}'. "
            "Must be a Twilio message SID starting with 'SM' or 'MM'."
        )

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
        raise ValueError(f"Failed to get SMS status: {e}")

    except Exception as e:
        logger.error(f"Error getting SMS status: {e}")
        raise


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "send_sms",
        "description": (
            "Send an SMS text message using Twilio. "
            "Sends a message to any phone number worldwide. "
            "The recipient phone number can be in E.164 format (+15551234567) "
            "or 10-digit US format (5551234567). "
            "Messages longer than 160 characters are automatically split into multiple segments. "
            "Returns a message SID that can be used to track delivery status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": (
                        "Recipient phone number. Accepts E.164 format (+15551234567) "
                        "or 10-digit US format (5551234567)"
                    ),
                },
                "body": {
                    "type": "string",
                    "description": (
                        "The message text to send. Max 1600 characters. "
                        "Messages over 160 characters are split into multiple segments."
                    ),
                },
                "from_number": {
                    "type": "string",
                    "description": (
                        "Optional sender phone number in E.164 format. "
                        "If not provided, uses TWILIO_PHONE_NUMBER from environment."
                    ),
                },
                "status_callback": {
                    "type": "string",
                    "description": (
                        "Optional webhook URL to receive delivery status updates "
                        "(queued, sent, delivered, failed)"
                    ),
                },
            },
            "required": ["to", "body"],
        },
        "handler": send_sms,
    },
    {
        "name": "get_sms_status",
        "description": (
            "Get the delivery status of a previously sent SMS message. "
            "Use this to confirm if a message was delivered or check for errors. "
            "Requires the message SID returned from send_sms."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_sid": {
                    "type": "string",
                    "description": (
                        "The Twilio message SID (starts with 'SM' or 'MM') "
                        "returned from send_sms"
                    ),
                },
            },
            "required": ["message_sid"],
        },
        "handler": get_sms_status,
    },
]
