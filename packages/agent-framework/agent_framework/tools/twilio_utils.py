"""Shared Twilio utility functions.

Common validation and sanitization logic used by both twilio_sms and
twilio_sms_clarification modules.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

# E.164 phone number format: +[country code][number]
E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")

# Twilio Account SID format: AC followed by 32 hex characters
ACCOUNT_SID_PATTERN = re.compile(r"^AC[a-f0-9]{32}$", re.IGNORECASE)

# Twilio Message SID format: SM or MM followed by 32 hex characters
MESSAGE_SID_PATTERN = re.compile(r"^[SM]M[a-f0-9]{32}$", re.IGNORECASE)


def validate_account_sid(account_sid: str) -> bool:
    """Validate Twilio Account SID format.

    Args:
        account_sid: The account SID to validate

    Returns:
        True if valid, False otherwise
    """
    return bool(ACCOUNT_SID_PATTERN.match(account_sid))


def validate_message_sid(message_sid: str) -> bool:
    """Validate Twilio Message SID format.

    Args:
        message_sid: The message SID to validate

    Returns:
        True if valid, False otherwise
    """
    return bool(MESSAGE_SID_PATTERN.match(message_sid))


def validate_phone_number(phone: str, field_name: str) -> str:
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

    # Add + if missing and handle common formats
    if not normalized.startswith("+"):
        # US/Canada: 10 digits (area code + number)
        if len(normalized) == 10 and normalized.isdigit():
            normalized = f"+1{normalized}"
        # US/Canada: 11 digits starting with 1 (country code + area code + number)
        elif normalized.startswith("1") and len(normalized) == 11 and normalized.isdigit():
            normalized = f"+{normalized}"
        # Other formats: reject if not clearly valid after adding +
        elif normalized.isdigit() and len(normalized) >= 7:
            # Only add + if it looks like a valid international number
            normalized = f"+{normalized}"
        else:
            raise ValueError(
                f"Invalid {field_name}: '{phone}'. Must be in E.164 format "
                "(e.g., +15551234567) or a 10-digit US number."
            )

    if not E164_PATTERN.match(normalized):
        raise ValueError(
            f"Invalid {field_name}: '{phone}'. Must be in E.164 format "
            "(e.g., +15551234567) or a 10-digit US number."
        )

    return normalized


def sanitize_error_message(error: Exception) -> str:
    """Sanitize error message to avoid exposing sensitive data.

    Args:
        error: The exception to sanitize

    Returns:
        Sanitized error message safe for logging
    """
    return _redact_sensitive_text(str(error))


def _redact_sensitive_text(text: str) -> str:
    """Remove credentials, tokens, and phone numbers from arbitrary text.

    Used to sanitize both exception messages and Twilio API error response
    bodies before they reach callers or log sinks.

    Args:
        text: The raw text to sanitize.

    Returns:
        Sanitized text safe for logging and returning to callers.
    """
    # Twilio auth tokens / account SIDs are 32 hex characters
    sanitized = re.sub(r"[a-f0-9]{32}", "[REDACTED]", text, flags=re.IGNORECASE)
    # Bearer / Basic auth headers
    sanitized = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"Basic\s+\S+", "Basic [REDACTED]", sanitized, flags=re.IGNORECASE)
    # Phone numbers in E.164 or near-E.164 formats
    sanitized = re.sub(r"\+?\d[\d\-\s]{8,}\d", "[PHONE REDACTED]", sanitized)
    return sanitized


# ---------------------------------------------------------------------------
# Credential validation and Twilio API helpers
# ---------------------------------------------------------------------------


@dataclass
class TwilioCredentials:
    """Validated Twilio credentials ready for API use."""

    account_sid: str
    auth_token: str = field(repr=False)


def validate_twilio_credentials() -> TwilioCredentials | str:
    """Validate that Twilio account_sid and auth_token are configured and well-formed.

    Reads credentials from the global ``settings`` object and checks that both
    are present and that the account SID matches the expected format.

    Returns:
        A ``TwilioCredentials`` instance on success, or a human-readable error
        string describing the first validation failure encountered.
    """
    account_sid = settings.twilio_account_sid
    auth_token = settings.twilio_auth_token

    if not account_sid:
        return (
            "TWILIO_ACCOUNT_SID is required. Set it in your environment or .env file. "
            "Get it from: https://console.twilio.com/"
        )

    if not validate_account_sid(account_sid):
        return "Invalid TWILIO_ACCOUNT_SID format. Must be 'AC' followed by 32 hex characters."

    if not auth_token:
        return (
            "TWILIO_AUTH_TOKEN is required. Set it in your environment or .env file. "
            "Get it from: https://console.twilio.com/"
        )

    return TwilioCredentials(account_sid=account_sid, auth_token=auth_token)


async def post_twilio_message(
    credentials: TwilioCredentials,
    to: str,
    from_number: str,
    body: str,
) -> dict[str, Any]:
    """Send an SMS via the Twilio REST API.

    Builds the Twilio Messages endpoint URL, POSTs the message, and returns a
    normalised result dict that both ``twilio_sms`` and
    ``twilio_sms_clarification`` can consume directly.

    Args:
        credentials: Validated Twilio credentials.
        to: Recipient phone number in E.164 format.
        from_number: Sender phone number in E.164 format.
        body: Message text to send.

    Returns:
        Dictionary with at least ``"success"`` (bool).  On success the dict
        also contains ``"result"`` (the parsed Twilio JSON response) and
        ``"status_code"`` (201).  On failure it contains ``"error"`` (str) and,
        when available, ``"status_code"``.
    """
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{quote(credentials.account_sid, safe='')}/Messages.json"
    )

    payload = {
        "To": to,
        "From": from_number,
        "Body": body,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                data=payload,
                auth=(credentials.account_sid, credentials.auth_token),
            )

            try:
                result = response.json()
            except ValueError:
                logger.error("Invalid JSON response from Twilio API")
                return {
                    "success": False,
                    "error": f"Invalid response from Twilio API (status {response.status_code})",
                    "status_code": response.status_code,
                }

            if response.status_code == 201:
                return {
                    "success": True,
                    "result": result,
                    "status_code": response.status_code,
                }
            else:
                error_code = result.get("code")
                raw_message = result.get("message", "Unknown error")
                safe_message = _redact_sensitive_text(raw_message)
                logger.error("Twilio API error: %s - %s", error_code, safe_message)
                return {
                    "success": False,
                    "error": f"Twilio error {error_code}: {safe_message}",
                    "status_code": response.status_code,
                }

    except httpx.HTTPError as e:
        sanitized = sanitize_error_message(e)
        logger.error("HTTP error sending SMS: %s", sanitized)
        return {
            "success": False,
            "error": f"Failed to send SMS: {sanitized}",
        }

    except Exception as e:
        sanitized = sanitize_error_message(e)
        logger.error("Error sending SMS: %s", sanitized)
        return {
            "success": False,
            "error": f"Unexpected error: {sanitized}",
        }


async def get_twilio_resource(
    credentials: TwilioCredentials,
    url: str,
) -> dict[str, Any]:
    """Fetch a resource from the Twilio REST API.

    Performs an authenticated GET request and returns a normalised result dict.

    Args:
        credentials: Validated Twilio credentials.
        url: Full Twilio API URL to fetch.

    Returns:
        Dictionary with at least ``"success"`` (bool).  On success the dict
        also contains ``"result"`` (the parsed Twilio JSON response) and
        ``"status_code"`` (200).  On failure it contains ``"error"`` (str) and,
        when available, ``"status_code"``.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                auth=(credentials.account_sid, credentials.auth_token),
            )

            try:
                result = response.json()
            except ValueError:
                logger.error("Invalid JSON response from Twilio API")
                return {
                    "success": False,
                    "error": f"Invalid response from Twilio API (status {response.status_code})",
                    "status_code": response.status_code,
                }

            if response.status_code == 200:
                return {
                    "success": True,
                    "result": result,
                    "status_code": response.status_code,
                }
            else:
                error_code = result.get("code")
                raw_message = result.get("message", "Unknown error")
                safe_message = _redact_sensitive_text(raw_message)
                logger.error("Twilio API error: %s - %s", error_code, safe_message)
                return {
                    "success": False,
                    "error": f"Twilio error {error_code}: {safe_message}",
                    "status_code": response.status_code,
                }

    except httpx.HTTPError as e:
        sanitized = sanitize_error_message(e)
        logger.error("HTTP error fetching Twilio resource: %s", sanitized)
        return {
            "success": False,
            "error": f"Failed to fetch resource: {sanitized}",
        }

    except Exception as e:
        sanitized = sanitize_error_message(e)
        logger.error("Error fetching Twilio resource: %s", sanitized)
        return {
            "success": False,
            "error": f"Unexpected error: {sanitized}",
        }
