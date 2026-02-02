"""PII (Personally Identifiable Information) masking utilities.

This module provides utilities for masking sensitive data like phone numbers
before logging or displaying them, to prevent exposure in log files.
"""

import re


def mask_phone_number(phone: str) -> str:
    """Mask a phone number for safe logging.

    Preserves the first few and last few digits to allow identification
    while hiding the middle portion.

    Args:
        phone: Phone number in any format (E.164 preferred)

    Returns:
        Masked phone number, e.g., "+1555***4567"

    Examples:
        >>> mask_phone_number("+15551234567")
        '+1555***4567'
        >>> mask_phone_number("5551234567")
        '555***4567'
        >>> mask_phone_number("")
        '[no phone]'
    """
    if not phone:
        return "[no phone]"

    # Extract just digits and the + prefix if present
    has_plus = phone.startswith("+")
    digits = re.sub(r"[^\d]", "", phone)

    if len(digits) <= 6:
        # Too short to meaningfully mask - hide all but last 2
        return ("+" if has_plus else "") + "***" + digits[-2:] if len(digits) >= 2 else "***"

    # For standard phone numbers (7+ digits):
    # Show first 4 digits (includes country/area code) and last 4 digits
    prefix = digits[:4]
    suffix = digits[-4:]

    return ("+" if has_plus else "") + prefix + "***" + suffix


def mask_phone_in_text(text: str) -> str:
    """Mask any phone numbers found in text.

    Finds patterns that look like phone numbers and masks them.

    Args:
        text: Text that may contain phone numbers

    Returns:
        Text with phone numbers masked
    """
    # Match E.164 format: +[country][number]
    e164_pattern = r"\+\d{10,15}"
    # Match common US formats: (555) 123-4567, 555-123-4567, 5551234567
    us_pattern = r"(?:\(\d{3}\)\s*|\d{3}[-.\s]?)\d{3}[-.\s]?\d{4}"

    def mask_match(match: re.Match[str]) -> str:
        return mask_phone_number(match.group(0))

    text = re.sub(e164_pattern, mask_match, text)
    text = re.sub(us_pattern, mask_match, text)

    return text
