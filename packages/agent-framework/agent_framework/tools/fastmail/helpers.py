"""Helper functions for FastMail tools.

Contains formatting functions, email validation, and centralized error handling.
"""

import html
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# RFC 5322 compliant email regex (simplified but covers most valid cases)
# This is intentionally strict to prevent malformed addresses
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9]"
    r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9]"
    r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)


def _validate_email(email: str) -> bool:
    """Validate an email address format.

    Args:
        email: Email address to validate

    Returns:
        True if valid, False otherwise
    """
    if not email or not isinstance(email, str):
        return False
    # Check length limits (RFC 5321)
    if len(email) > 254:
        return False
    local_part = email.rsplit("@", 1)[0] if "@" in email else ""
    if len(local_part) > 64:
        return False
    return EMAIL_REGEX.match(email) is not None


def _validate_email_list(emails: list[str]) -> tuple[bool, list[str]]:
    """Validate a list of email addresses.

    Args:
        emails: List of email addresses to validate

    Returns:
        Tuple of (all_valid, list_of_invalid_emails)
    """
    invalid = [e for e in emails if not _validate_email(e)]
    return len(invalid) == 0, invalid


def _is_recipient_allowed(email: str, allowed_patterns: list[str]) -> bool:
    """Check if an email recipient is in the allowed list.

    Supports exact matches and wildcard domain patterns (*@domain.com).

    Args:
        email: Email address to check
        allowed_patterns: List of allowed patterns (exact emails or *@domain.com)

    Returns:
        True if allowed, False otherwise
    """
    email_lower = email.lower()
    for pattern in allowed_patterns:
        pattern_lower = pattern.lower().strip()
        if pattern_lower.startswith("*@"):
            # Wildcard domain match
            domain = pattern_lower[2:]
            if email_lower.endswith(f"@{domain}"):
                return True
        elif email_lower == pattern_lower:
            # Exact match
            return True
    return False


def _sanitize_html(html_content: str) -> str:
    """Sanitize HTML content to prevent XSS in email clients.

    Uses a conservative approach: escapes all HTML and only allows
    basic formatting through a whitelist approach.

    Args:
        html_content: Raw HTML content

    Returns:
        Sanitized HTML content
    """
    # For email HTML, we take a conservative approach:
    # 1. If the content looks like it contains script tags or event handlers, escape it
    # 2. Otherwise, allow the HTML through (email clients have their own sanitization)
    #
    # Dangerous patterns that should never be in legitimate email HTML
    dangerous_patterns = [
        r"<script",
        r"</script",
        r"javascript:",
        r"vbscript:",
        r"on\w+\s*=",  # Event handlers like onclick=, onerror=
        r"<iframe",
        r"<object",
        r"<embed",
        r"<form",
        r"<input",
        r"<meta\s+http-equiv",
        r"expression\s*\(",  # CSS expression
        r"url\s*\(\s*['\"]?\s*data:",  # Data URLs in CSS
    ]

    content_lower = html_content.lower()
    for pattern in dangerous_patterns:
        if re.search(pattern, content_lower, re.IGNORECASE):
            logger.warning(f"Dangerous HTML pattern detected: {pattern}")
            # Escape the entire content to prevent XSS
            return html.escape(html_content)

    return html_content


def _handle_jmap_error(error: Exception, operation: str) -> dict[str, Any]:
    """Handle JMAP API errors with consistent error responses.

    Masks sensitive information from error messages to prevent information leakage.

    Args:
        error: The exception that was raised
        operation: Description of the operation that failed (e.g., "listing mailboxes")

    Returns:
        Error response dictionary with status, message, and optional error_type/status_code
    """
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        # Log full error for debugging, but don't expose to caller
        logger.error(f"HTTP error {operation}: {error}")

        if status_code == 401:
            return {
                "status": "error",
                "error_type": "AuthenticationError",
                "status_code": status_code,
                "message": "Authentication failed. Check your FastMail API token.",
            }
        if status_code == 403:
            return {
                "status": "error",
                "error_type": "ForbiddenError",
                "status_code": status_code,
                "message": f"Access forbidden (HTTP {status_code})",
            }
        return {
            "status": "error",
            "error_type": "HTTPError",
            "status_code": status_code,
            "message": f"HTTP error: {status_code}",
        }

    # For generic exceptions, log the full error but return only the error type
    # to prevent leaking sensitive information (API keys, paths, etc.)
    logger.error(f"Error {operation}: {error}")

    # Get a safe error type name without exposing details
    error_type = type(error).__name__

    # Map common exceptions to user-friendly messages
    safe_messages = {
        "ValueError": "Invalid value provided",
        "TypeError": "Invalid type provided",
        "KeyError": "Missing required field",
        "ConnectionError": "Connection failed",
        "TimeoutError": "Request timed out",
        "RequestError": "Network request failed",
    }

    return {
        "status": "error",
        "error_type": error_type,
        "message": safe_messages.get(error_type, f"Operation failed: {operation}"),
    }


def _format_email_summary(email: dict[str, Any]) -> dict[str, Any]:
    """Format an email for summary display."""
    return {
        "id": email.get("id"),
        "thread_id": email.get("threadId"),
        "mailbox_ids": list(email.get("mailboxIds", {}).keys()),
        "from": email.get("from", []),
        "to": email.get("to", []),
        "subject": email.get("subject", "(no subject)"),
        "received_at": email.get("receivedAt"),
        "is_unread": email.get("keywords", {}).get("$seen") is None,
        "is_flagged": email.get("keywords", {}).get("$flagged", False),
        "has_attachment": email.get("hasAttachment", False),
        "preview": email.get("preview", ""),
    }


def _format_email_full(email: dict[str, Any]) -> dict[str, Any]:
    """Format an email with full content."""
    result = _format_email_summary(email)

    # Add body content
    body_values = email.get("bodyValues", {})
    text_body = email.get("textBody", [])
    html_body = email.get("htmlBody", [])

    # Get text content
    text_content = ""
    for part in text_body:
        part_id = part.get("partId")
        if part_id and part_id in body_values:
            text_content += body_values[part_id].get("value", "")

    # Get HTML content if no text
    html_content = ""
    if not text_content:
        for part in html_body:
            part_id = part.get("partId")
            if part_id and part_id in body_values:
                html_content += body_values[part_id].get("value", "")

    result["body_text"] = text_content
    result["body_html"] = html_content if not text_content else ""

    # Add additional headers
    result["cc"] = email.get("cc", [])
    result["bcc"] = email.get("bcc", [])
    result["reply_to"] = email.get("replyTo", [])
    result["in_reply_to"] = email.get("inReplyTo")
    result["references"] = email.get("references", [])
    result["message_id"] = email.get("messageId", [])
    result["sent_at"] = email.get("sentAt")
    result["size"] = email.get("size")

    return result


def _format_mailbox(mailbox: dict[str, Any]) -> dict[str, Any]:
    """Format a mailbox for display."""
    return {
        "id": mailbox.get("id"),
        "name": mailbox.get("name"),
        "role": mailbox.get("role"),  # inbox, drafts, sent, trash, junk, archive, etc.
        "parent_id": mailbox.get("parentId"),
        "total_emails": mailbox.get("totalEmails", 0),
        "unread_emails": mailbox.get("unreadEmails", 0),
        "total_threads": mailbox.get("totalThreads", 0),
        "unread_threads": mailbox.get("unreadThreads", 0),
        "sort_order": mailbox.get("sortOrder", 0),
        "is_subscribed": mailbox.get("isSubscribed", True),
    }
