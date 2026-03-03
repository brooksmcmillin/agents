"""Tool schemas for MCP server auto-registration.

Contains TOOL_SCHEMAS list with all FastMail tool definitions.
"""

from .calendar import get_calendar_events, list_calendars
from .mailbox import list_mailboxes
from .manage import delete_email, move_email, update_email_flags
from .read import get_email, get_emails, search_emails
from .send import send_agent_report, send_email

TOOL_SCHEMAS = [
    {
        "name": "list_mailboxes",
        "description": (
            "List all mailboxes (folders) in the FastMail account. "
            "Returns mailboxes with their roles (inbox, sent, drafts, trash, etc.), "
            "email counts, and unread counts. Use this first to understand the account "
            "structure before querying emails."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token. If not provided, uses FASTMAIL_API_TOKEN from environment.",
                },
            },
            "required": [],
        },
        "handler": list_mailboxes,
    },
    {
        "name": "get_emails",
        "description": (
            "Get emails from a FastMail mailbox with filtering and pagination. "
            "Retrieves email summaries (not full content) for listing. "
            "Specify mailbox by ID or role (inbox, sent, drafts, trash, archive, junk). "
            "Use get_email() to get full content of a specific email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox_id": {
                    "type": "string",
                    "description": "Specific mailbox ID to query. Takes precedence over mailbox_role.",
                },
                "mailbox_role": {
                    "type": "string",
                    "enum": ["inbox", "sent", "drafts", "trash", "junk", "archive"],
                    "description": "Mailbox role to query. Used if mailbox_id not provided.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "description": "Maximum number of emails to return (default: 20)",
                },
                "position": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Starting position for pagination",
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["receivedAt", "sentAt", "from", "subject"],
                    "default": "receivedAt",
                    "description": "Sort field (default: receivedAt)",
                },
                "sort_descending": {
                    "type": "boolean",
                    "default": True,
                    "description": "Sort in descending order (default: True, newest first)",
                },
                "filter_unread": {
                    "type": "boolean",
                    "description": "Filter to only unread (true) or read (false) emails",
                },
                "filter_flagged": {
                    "type": "boolean",
                    "description": "Filter to only flagged (true) or unflagged (false) emails",
                },
                "filter_from": {
                    "type": "string",
                    "description": "Filter by sender email address (partial match)",
                },
                "filter_subject": {
                    "type": "string",
                    "description": "Filter by subject (partial match)",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": [],
        },
        "handler": get_emails,
    },
    {
        "name": "get_email",
        "description": (
            "Get the full content of a specific FastMail email. "
            "Retrieves complete email including body text/HTML, all headers, and metadata. "
            "Use this after finding an email with get_emails() or search_emails()."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The unique email ID to retrieve",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["email_id"],
        },
        "handler": get_email,
    },
    {
        "name": "search_emails",
        "description": (
            "Search FastMail emails using full-text search. "
            "Searches email content, subject, sender, and recipients. "
            "Returns matching emails with search snippets highlighting the matches."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query text",
                },
                "mailbox_id": {
                    "type": "string",
                    "description": "Optional mailbox ID to limit search scope",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                    "description": "Maximum number of results (default: 20)",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["query"],
        },
        "handler": search_emails,
    },
    {
        "name": "send_email",
        "description": (
            "Send an email via FastMail. "
            "Creates and sends an email using JMAP EmailSubmission. "
            "Supports plain text or HTML body, CC/BCC recipients, and replying to existing emails."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of recipient email addresses",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content (plain text or HTML)",
                },
                "cc": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of CC recipients",
                },
                "bcc": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of BCC recipients",
                },
                "reply_to_email_id": {
                    "type": "string",
                    "description": "Optional email ID to reply to (sets In-Reply-To header)",
                },
                "is_html": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, body is treated as HTML (default: false for plain text)",
                },
                "identity_email": {
                    "type": "string",
                    "description": "Optional email address to send from. Must match a configured identity in FastMail. If not specified, uses the primary identity.",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["to", "subject", "body"],
        },
        "handler": send_email,
    },
    {
        "name": "move_email",
        "description": (
            "Move a FastMail email to a different mailbox. "
            "Moves the email from its current mailbox(es) to the specified destination. "
            "Can specify destination by ID or role (inbox, archive, trash, etc.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email ID to move",
                },
                "to_mailbox_id": {
                    "type": "string",
                    "description": "Destination mailbox ID (takes precedence over role)",
                },
                "to_mailbox_role": {
                    "type": "string",
                    "enum": ["inbox", "archive", "trash", "junk", "drafts", "sent"],
                    "description": "Destination mailbox role",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["email_id"],
        },
        "handler": move_email,
    },
    {
        "name": "update_email_flags",
        "description": (
            "Update FastMail email flags (read/unread, flagged/unflagged). "
            "Modifies the read status and/or flagged status of an email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email ID to update",
                },
                "mark_read": {
                    "type": "boolean",
                    "description": "Set to true to mark as read, false for unread",
                },
                "mark_flagged": {
                    "type": "boolean",
                    "description": "Set to true to flag, false to unflag",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["email_id"],
        },
        "handler": update_email_flags,
    },
    {
        "name": "delete_email",
        "description": (
            "Delete a FastMail email (move to trash or permanently delete). "
            "By default, moves the email to trash. Set permanent=true to permanently "
            "delete the email (cannot be undone)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email ID to delete",
                },
                "permanent": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, permanently delete. If false (default), move to trash.",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["email_id"],
        },
        "handler": delete_email,
    },
    {
        "name": "send_agent_report",
        "description": (
            "Send a report/notification email from this agent to the admin. "
            "Use this to send status updates, reports, task completions, alerts, or any "
            "notification to the system administrator. The sender email is automatically "
            "derived from your agent name (e.g., chatbot@brooksmcmillin.com) and the "
            "recipient is the configured admin email address. Requires ADMIN_EMAIL_ADDRESS "
            "to be configured and the agent's email identity set up in FastMail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Email subject line (be descriptive, e.g., 'Daily Task Report - Jan 30')",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content (plain text or HTML). Include relevant details, summaries, or data.",
                },
                "is_html": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, body is treated as HTML (default: false for plain text)",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["subject", "body"],
        },
        "handler": send_agent_report,
    },
    {
        "name": "list_calendars",
        "description": (
            "List all calendars in the FastMail account. "
            "Returns calendars with their name, color, visibility, and subscription status. "
            "Use this to discover available calendars before querying events."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token. If not provided, uses FASTMAIL_API_TOKEN from environment.",
                },
            },
            "required": [],
        },
        "handler": list_calendars,
    },
    {
        "name": "get_calendar_events",
        "description": (
            "Query calendar events by date range. "
            "Retrieves events within the specified date range with title, start time, "
            "duration, location, description, and participants. "
            "Optionally filter by calendar ID or title text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "after": {
                    "type": "string",
                    "description": "Start of date range in ISO 8601 format (e.g. '2025-03-01T00:00:00')",
                },
                "before": {
                    "type": "string",
                    "description": "End of date range in ISO 8601 format (e.g. '2025-03-31T23:59:59')",
                },
                "calendar_id": {
                    "type": "string",
                    "description": "Optional calendar ID to filter events by. Use list_calendars to find IDs.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional title text to filter by (partial match)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 50,
                    "description": "Maximum number of events to return (default: 50)",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["after", "before"],
        },
        "handler": get_calendar_events,
    },
]
