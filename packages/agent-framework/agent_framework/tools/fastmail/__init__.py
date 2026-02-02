"""FastMail JMAP email tools.

This package provides email functionality using FastMail's JMAP API.
Supports reading, searching, sending, and organizing emails.

FastMail uses the JMAP (JSON Meta Application Protocol) standard (RFC 8620, RFC 8621).
API documentation: https://www.fastmail.com/dev/
"""

# Client and constants
from .client import JMAP_CAPABILITIES, JMAP_SESSION_URL, JMAPClient, _get_client

# Helper functions
from .helpers import (
    _format_email_full,
    _format_email_summary,
    _format_mailbox,
    _handle_jmap_error,
)

# Mailbox operations
from .mailbox import list_mailboxes

# Email management operations
from .manage import delete_email, move_email, update_email_flags

# Email reading operations
from .read import get_email, get_emails, search_emails

# Tool schemas for MCP registration
from .schemas import TOOL_SCHEMAS

# Email sending operations
from .send import send_agent_report, send_email

__all__ = [
    # Client
    "JMAPClient",
    "JMAP_SESSION_URL",
    "JMAP_CAPABILITIES",
    "_get_client",
    # Helpers
    "_format_email_summary",
    "_format_email_full",
    "_format_mailbox",
    "_handle_jmap_error",
    # Public tool functions
    "list_mailboxes",
    "get_emails",
    "get_email",
    "search_emails",
    "send_email",
    "send_agent_report",
    "move_email",
    "update_email_flags",
    "delete_email",
    # Schemas
    "TOOL_SCHEMAS",
]
