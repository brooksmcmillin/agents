"""Helper functions for FastMail tools.

Contains formatting functions and centralized error handling.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _handle_jmap_error(error: Exception, operation: str) -> dict[str, Any]:
    """Handle JMAP API errors with consistent error responses.

    Args:
        error: The exception that was raised
        operation: Description of the operation that failed (e.g., "listing mailboxes")

    Returns:
        Error response dictionary with status, message, and optional error_type/status_code
    """
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
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
                "message": f"HTTP error: {status_code}",
            }
        return {
            "status": "error",
            "error_type": "HTTPError",
            "status_code": status_code,
            "message": f"HTTP error: {status_code}",
        }

    logger.error(f"Error {operation}: {error}")
    return {
        "status": "error",
        "message": str(error),
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
