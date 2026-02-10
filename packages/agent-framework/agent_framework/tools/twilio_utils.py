"""Shared Twilio utility functions.

Common validation and sanitization logic used by both twilio_sms and
twilio_sms_clarification modules.
"""

import re

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
    error_str = str(error)
    # Remove any potential auth tokens or credentials from error messages
    # Twilio auth tokens are 32 hex characters
    sanitized = re.sub(r"[a-f0-9]{32}", "[REDACTED]", error_str, flags=re.IGNORECASE)
    # Also redact anything that looks like a bearer token or basic auth
    sanitized = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"Basic\s+\S+", "Basic [REDACTED]", sanitized, flags=re.IGNORECASE)
    return sanitized
