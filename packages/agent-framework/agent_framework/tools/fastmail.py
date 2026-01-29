"""FastMail JMAP email tool.

This tool provides email functionality using FastMail's JMAP API.
Supports reading, searching, sending, and organizing emails.

FastMail uses the JMAP (JSON Meta Application Protocol) standard (RFC 8620, RFC 8621).
API documentation: https://www.fastmail.com/dev/
"""

import logging
from typing import Any

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

# JMAP Constants
JMAP_SESSION_URL = "https://api.fastmail.com/jmap/session"
JMAP_CAPABILITIES = {
    "core": "urn:ietf:params:jmap:core",
    "mail": "urn:ietf:params:jmap:mail",
    "submission": "urn:ietf:params:jmap:submission",
}


class JMAPClient:
    """JMAP client for FastMail API interactions."""

    def __init__(self, api_token: str | None = None):
        """Initialize JMAP client.

        Args:
            api_token: FastMail API token. If not provided, uses FASTMAIL_API_TOKEN
                from environment.
        """
        self.api_token = api_token or settings.fastmail_api_token
        if not self.api_token:
            raise ValueError(
                "FastMail API token required. Set FASTMAIL_API_TOKEN environment variable "
                "or provide api_token parameter. Generate a token at: "
                "Settings -> Privacy & Security -> Integrations -> API tokens"
            )

        self._session: dict[str, Any] | None = None
        self._account_id: str | None = None
        self._api_url: str | None = None

    async def _ensure_session(self) -> None:
        """Ensure we have a valid JMAP session."""
        if self._session is not None:
            return

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                JMAP_SESSION_URL,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            self._session = response.json()

        # Extract primary account ID and API URL
        accounts = self._session.get("accounts", {})
        primary_accounts = self._session.get("primaryAccounts", {})

        # Get the primary mail account
        mail_account_id = primary_accounts.get(JMAP_CAPABILITIES["mail"])
        if mail_account_id:
            self._account_id = mail_account_id
        elif accounts:
            # Fallback to first account
            self._account_id = next(iter(accounts.keys()))

        self._api_url = self._session.get("apiUrl")

        if not self._account_id or not self._api_url:
            raise ValueError("Could not determine FastMail account or API URL from session")

        logger.info(f"JMAP session established for account: {self._account_id}")

    async def _call(self, method_calls: list[list[Any]]) -> dict[str, Any]:
        """Make a JMAP API call.

        Args:
            method_calls: List of JMAP method calls in format [[method, args, id], ...]

        Returns:
            JMAP response with methodResponses
        """
        await self._ensure_session()

        request_body = {
            "using": list(JMAP_CAPABILITIES.values()),
            "methodCalls": method_calls,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._api_url,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            return response.json()

    @property
    def account_id(self) -> str:
        """Get the account ID (requires session to be established)."""
        if not self._account_id:
            raise ValueError("Session not established. Call a method first.")
        return self._account_id


def _get_client(api_token: str | None = None) -> JMAPClient:
    """Get a JMAP client instance."""
    return JMAPClient(api_token)


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


# =============================================================================
# Public Tool Functions
# =============================================================================


async def list_mailboxes(
    api_token: str | None = None,
) -> dict[str, Any]:
    """
    List all mailboxes (folders) in the FastMail account.

    Returns mailboxes with their roles (inbox, sent, drafts, trash, etc.),
    email counts, and unread counts. Useful for understanding the account
    structure before querying emails.

    Args:
        api_token: Optional FastMail API token. If not provided, uses
            FASTMAIL_API_TOKEN from environment.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - mailboxes: List of mailbox objects with id, name, role, counts
            - total_count: Number of mailboxes
            - message: Status message
    """
    logger.info("Listing FastMail mailboxes")

    try:
        client = _get_client(api_token)

        response = await client._call(
            [
                [
                    "Mailbox/get",
                    {
                        "accountId": client.account_id,
                        "properties": [
                            "id",
                            "name",
                            "role",
                            "parentId",
                            "totalEmails",
                            "unreadEmails",
                            "totalThreads",
                            "unreadThreads",
                            "sortOrder",
                            "isSubscribed",
                        ],
                    },
                    "mailbox-list",
                ]
            ]
        )

        # Extract mailboxes from response
        method_responses = response.get("methodResponses", [])
        if not method_responses:
            return {
                "status": "error",
                "message": "No response from JMAP server",
            }

        result = method_responses[0]
        if result[0] == "error":
            return {
                "status": "error",
                "message": f"JMAP error: {result[1].get('description', 'Unknown error')}",
            }

        mailboxes = result[1].get("list", [])
        formatted = [_format_mailbox(m) for m in mailboxes]

        # Sort by role priority then name
        role_priority = {
            "inbox": 0,
            "drafts": 1,
            "sent": 2,
            "archive": 3,
            "trash": 4,
            "junk": 5,
        }
        formatted.sort(key=lambda m: (role_priority.get(m["role"], 99), m["name"]))

        logger.info(f"Found {len(formatted)} mailboxes")
        return {
            "status": "success",
            "mailboxes": formatted,
            "total_count": len(formatted),
            "message": f"Found {len(formatted)} mailboxes",
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error listing mailboxes: {e}")
        if e.response.status_code == 401:
            return {
                "status": "error",
                "message": "Authentication failed. Check your FastMail API token.",
            }
        return {
            "status": "error",
            "message": f"HTTP error: {e.response.status_code}",
        }
    except Exception as e:
        logger.error(f"Error listing mailboxes: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def get_emails(
    mailbox_id: str | None = None,
    mailbox_role: str | None = None,
    limit: int = 20,
    position: int = 0,
    sort_by: str = "receivedAt",
    sort_descending: bool = True,
    filter_unread: bool | None = None,
    filter_flagged: bool | None = None,
    filter_from: str | None = None,
    filter_subject: str | None = None,
    api_token: str | None = None,
) -> dict[str, Any]:
    """
    Get emails from a mailbox with filtering and pagination.

    Retrieves email summaries (not full content) for listing. Use get_email()
    to get the full content of a specific email.

    Args:
        mailbox_id: Specific mailbox ID to query. Takes precedence over mailbox_role.
        mailbox_role: Mailbox role to query: "inbox", "sent", "drafts", "trash",
            "junk", "archive". Used if mailbox_id not provided.
        limit: Maximum number of emails to return (1-100, default: 20)
        position: Starting position for pagination (default: 0)
        sort_by: Sort field: "receivedAt", "sentAt", "from", "subject" (default: receivedAt)
        sort_descending: Sort in descending order (default: True, newest first)
        filter_unread: Filter to only unread (True) or read (False) emails
        filter_flagged: Filter to only flagged (True) or unflagged (False) emails
        filter_from: Filter by sender email address (partial match)
        filter_subject: Filter by subject (partial match)
        api_token: Optional FastMail API token.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - emails: List of email summaries
            - total_count: Total matching emails
            - position: Current position
            - message: Status message
    """
    logger.info(f"Getting emails from mailbox_id={mailbox_id}, role={mailbox_role}")

    try:
        client = _get_client(api_token)

        # If role specified, first get the mailbox ID
        target_mailbox_id = mailbox_id
        if not target_mailbox_id and mailbox_role:
            mailbox_response = await client._call(
                [
                    [
                        "Mailbox/query",
                        {
                            "accountId": client.account_id,
                            "filter": {"role": mailbox_role},
                        },
                        "find-mailbox",
                    ]
                ]
            )

            responses = mailbox_response.get("methodResponses", [])
            if responses and responses[0][0] == "Mailbox/query":
                ids = responses[0][1].get("ids", [])
                if ids:
                    target_mailbox_id = ids[0]
                else:
                    return {
                        "status": "error",
                        "message": f"No mailbox found with role: {mailbox_role}",
                    }

        # Build filter
        email_filter: dict[str, Any] = {}
        if target_mailbox_id:
            email_filter["inMailbox"] = target_mailbox_id

        # Build conditions for AND filter
        conditions = []
        if filter_unread is not None:
            if filter_unread:
                conditions.append({"notKeyword": "$seen"})
            else:
                conditions.append({"hasKeyword": "$seen"})

        if filter_flagged is not None:
            if filter_flagged:
                conditions.append({"hasKeyword": "$flagged"})
            else:
                conditions.append({"notKeyword": "$flagged"})

        if filter_from:
            conditions.append({"from": filter_from})

        if filter_subject:
            conditions.append({"subject": filter_subject})

        # Combine filters
        if conditions:
            if target_mailbox_id:
                conditions.insert(0, {"inMailbox": target_mailbox_id})
            email_filter = {"operator": "AND", "conditions": conditions}

        # Build sort
        sort_property = (
            sort_by if sort_by in ["receivedAt", "sentAt", "from", "subject"] else "receivedAt"
        )
        sort = [{"property": sort_property, "isAscending": not sort_descending}]

        # Clamp limit
        limit = max(1, min(100, limit))

        # Query emails
        response = await client._call(
            [
                [
                    "Email/query",
                    {
                        "accountId": client.account_id,
                        "filter": email_filter,
                        "sort": sort,
                        "position": position,
                        "limit": limit,
                        "calculateTotal": True,
                    },
                    "email-query",
                ],
                [
                    "Email/get",
                    {
                        "accountId": client.account_id,
                        "#ids": {
                            "resultOf": "email-query",
                            "name": "Email/query",
                            "path": "/ids",
                        },
                        "properties": [
                            "id",
                            "threadId",
                            "mailboxIds",
                            "from",
                            "to",
                            "subject",
                            "receivedAt",
                            "keywords",
                            "hasAttachment",
                            "preview",
                        ],
                    },
                    "email-get",
                ],
            ]
        )

        method_responses = response.get("methodResponses", [])

        # Get query results
        query_result = None
        get_result = None
        for resp in method_responses:
            if resp[0] == "Email/query":
                query_result = resp[1]
            elif resp[0] == "Email/get":
                get_result = resp[1]
            elif resp[0] == "error":
                return {
                    "status": "error",
                    "message": f"JMAP error: {resp[1].get('description', 'Unknown error')}",
                }

        if not query_result or not get_result:
            return {
                "status": "error",
                "message": "Incomplete response from JMAP server",
            }

        emails = get_result.get("list", [])
        formatted = [_format_email_summary(e) for e in emails]
        total = query_result.get("total", len(formatted))

        logger.info(f"Retrieved {len(formatted)} emails (total: {total})")
        return {
            "status": "success",
            "emails": formatted,
            "total_count": total,
            "position": position,
            "has_more": position + len(formatted) < total,
            "message": f"Retrieved {len(formatted)} of {total} emails",
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error getting emails: {e}")
        if e.response.status_code == 401:
            return {
                "status": "error",
                "message": "Authentication failed. Check your FastMail API token.",
            }
        return {
            "status": "error",
            "message": f"HTTP error: {e.response.status_code}",
        }
    except Exception as e:
        logger.error(f"Error getting emails: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def get_email(
    email_id: str,
    api_token: str | None = None,
) -> dict[str, Any]:
    """
    Get the full content of a specific email.

    Retrieves complete email including body text/HTML, all headers, and metadata.
    Use this after finding an email with get_emails() or search_emails().

    Args:
        email_id: The unique email ID to retrieve
        api_token: Optional FastMail API token.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - email: Full email object with body content
            - message: Status message
    """
    logger.info(f"Getting email: {email_id}")

    try:
        client = _get_client(api_token)

        response = await client._call(
            [
                [
                    "Email/get",
                    {
                        "accountId": client.account_id,
                        "ids": [email_id],
                        "properties": [
                            "id",
                            "threadId",
                            "mailboxIds",
                            "from",
                            "to",
                            "cc",
                            "bcc",
                            "replyTo",
                            "subject",
                            "receivedAt",
                            "sentAt",
                            "keywords",
                            "hasAttachment",
                            "preview",
                            "inReplyTo",
                            "references",
                            "messageId",
                            "size",
                            "textBody",
                            "htmlBody",
                            "bodyValues",
                        ],
                        "fetchTextBodyValues": True,
                        "fetchHTMLBodyValues": True,
                        "maxBodyValueBytes": 1000000,  # 1MB max
                    },
                    "email-get",
                ]
            ]
        )

        method_responses = response.get("methodResponses", [])
        if not method_responses:
            return {
                "status": "error",
                "message": "No response from JMAP server",
            }

        result = method_responses[0]
        if result[0] == "error":
            return {
                "status": "error",
                "message": f"JMAP error: {result[1].get('description', 'Unknown error')}",
            }

        emails = result[1].get("list", [])
        not_found = result[1].get("notFound", [])

        if email_id in not_found:
            return {
                "status": "not_found",
                "message": f"Email not found: {email_id}",
            }

        if not emails:
            return {
                "status": "error",
                "message": "No email returned",
            }

        email = _format_email_full(emails[0])

        logger.info(f"Retrieved email: {email.get('subject', '(no subject)')}")
        return {
            "status": "success",
            "email": email,
            "message": "Email retrieved successfully",
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error getting email: {e}")
        if e.response.status_code == 401:
            return {
                "status": "error",
                "message": "Authentication failed. Check your FastMail API token.",
            }
        return {
            "status": "error",
            "message": f"HTTP error: {e.response.status_code}",
        }
    except Exception as e:
        logger.error(f"Error getting email: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def search_emails(
    query: str,
    mailbox_id: str | None = None,
    limit: int = 20,
    api_token: str | None = None,
) -> dict[str, Any]:
    """
    Search emails using full-text search.

    Searches email content, subject, sender, and recipients. Returns matching
    emails with search snippets highlighting the matches.

    Args:
        query: Search query text
        mailbox_id: Optional mailbox ID to limit search scope
        limit: Maximum number of results (1-50, default: 20)
        api_token: Optional FastMail API token.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - emails: List of matching emails with snippets
            - total_count: Total matching emails
            - message: Status message
    """
    logger.info(f"Searching emails: {query}")

    try:
        client = _get_client(api_token)

        # Build filter
        email_filter: dict[str, Any] = {"text": query}
        if mailbox_id:
            email_filter = {
                "operator": "AND",
                "conditions": [
                    {"inMailbox": mailbox_id},
                    {"text": query},
                ],
            }

        # Clamp limit
        limit = max(1, min(50, limit))

        response = await client._call(
            [
                [
                    "Email/query",
                    {
                        "accountId": client.account_id,
                        "filter": email_filter,
                        "sort": [{"property": "receivedAt", "isAscending": False}],
                        "limit": limit,
                        "calculateTotal": True,
                    },
                    "search-query",
                ],
                [
                    "Email/get",
                    {
                        "accountId": client.account_id,
                        "#ids": {
                            "resultOf": "search-query",
                            "name": "Email/query",
                            "path": "/ids",
                        },
                        "properties": [
                            "id",
                            "threadId",
                            "mailboxIds",
                            "from",
                            "to",
                            "subject",
                            "receivedAt",
                            "keywords",
                            "hasAttachment",
                            "preview",
                        ],
                    },
                    "search-get",
                ],
                [
                    "SearchSnippet/get",
                    {
                        "accountId": client.account_id,
                        "filter": email_filter,
                        "#emailIds": {
                            "resultOf": "search-query",
                            "name": "Email/query",
                            "path": "/ids",
                        },
                    },
                    "search-snippets",
                ],
            ]
        )

        method_responses = response.get("methodResponses", [])

        query_result = None
        get_result = None
        snippets_result = None

        for resp in method_responses:
            if resp[0] == "Email/query":
                query_result = resp[1]
            elif resp[0] == "Email/get":
                get_result = resp[1]
            elif resp[0] == "SearchSnippet/get":
                snippets_result = resp[1]
            elif resp[0] == "error":
                return {
                    "status": "error",
                    "message": f"JMAP error: {resp[1].get('description', 'Unknown error')}",
                }

        if not query_result or not get_result:
            return {
                "status": "error",
                "message": "Incomplete response from JMAP server",
            }

        emails = get_result.get("list", [])
        formatted = [_format_email_summary(e) for e in emails]

        # Add search snippets
        if snippets_result:
            snippets = {s["emailId"]: s for s in snippets_result.get("list", [])}
            for email in formatted:
                snippet = snippets.get(email["id"], {})
                email["search_snippet_subject"] = snippet.get("subject")
                email["search_snippet_preview"] = snippet.get("preview")

        total = query_result.get("total", len(formatted))

        logger.info(f"Search found {len(formatted)} emails (total: {total})")
        return {
            "status": "success",
            "emails": formatted,
            "total_count": total,
            "query": query,
            "message": f"Found {total} emails matching '{query}'",
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error searching emails: {e}")
        if e.response.status_code == 401:
            return {
                "status": "error",
                "message": "Authentication failed. Check your FastMail API token.",
            }
        return {
            "status": "error",
            "message": f"HTTP error: {e.response.status_code}",
        }
    except Exception as e:
        logger.error(f"Error searching emails: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def send_email(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    reply_to_email_id: str | None = None,
    is_html: bool = False,
    api_token: str | None = None,
) -> dict[str, Any]:
    """
    Send an email via FastMail.

    Creates and sends an email using JMAP EmailSubmission. Supports plain text
    or HTML body, CC/BCC recipients, and replying to existing emails.

    Args:
        to: List of recipient email addresses
        subject: Email subject line
        body: Email body content (plain text or HTML)
        cc: Optional list of CC recipients
        bcc: Optional list of BCC recipients
        reply_to_email_id: Optional email ID to reply to (sets In-Reply-To header)
        is_html: If True, body is treated as HTML (default: False for plain text)
        api_token: Optional FastMail API token.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - email_id: ID of the created email
            - message: Status message
    """
    logger.info(f"Sending email to {to}, subject: {subject}")

    if not to:
        return {
            "status": "error",
            "message": "At least one recipient (to) is required",
        }

    if not subject:
        return {
            "status": "error",
            "message": "Subject is required",
        }

    try:
        client = _get_client(api_token)

        # Get identities to find the sender
        identity_response = await client._call(
            [
                [
                    "Identity/get",
                    {
                        "accountId": client.account_id,
                    },
                    "identity-get",
                ]
            ]
        )

        identity_result = identity_response.get("methodResponses", [[]])[0]
        if identity_result[0] == "error":
            return {
                "status": "error",
                "message": f"Failed to get identity: {identity_result[1].get('description')}",
            }

        identities = identity_result[1].get("list", [])
        if not identities:
            return {
                "status": "error",
                "message": "No email identity found. Cannot send email.",
            }

        # Use the first identity (primary)
        identity = identities[0]
        identity_id = identity["id"]
        from_address = identity.get("email")
        from_name = identity.get("name", "")

        # Build email object
        email_create: dict[str, Any] = {
            "from": [{"email": from_address, "name": from_name}]
            if from_name
            else [{"email": from_address}],
            "to": [{"email": addr} for addr in to],
            "subject": subject,
        }

        if cc:
            email_create["cc"] = [{"email": addr} for addr in cc]

        if bcc:
            email_create["bcc"] = [{"email": addr} for addr in bcc]

        # Set body
        if is_html:
            email_create["htmlBody"] = [{"partId": "body", "type": "text/html"}]
            email_create["bodyValues"] = {"body": {"value": body, "isEncodingProblem": False}}
        else:
            email_create["textBody"] = [{"partId": "body", "type": "text/plain"}]
            email_create["bodyValues"] = {"body": {"value": body, "isEncodingProblem": False}}

        # Handle reply
        if reply_to_email_id:
            # Get the original email for threading
            orig_response = await client._call(
                [
                    [
                        "Email/get",
                        {
                            "accountId": client.account_id,
                            "ids": [reply_to_email_id],
                            "properties": ["messageId", "references", "threadId"],
                        },
                        "orig-get",
                    ]
                ]
            )

            orig_result = orig_response.get("methodResponses", [[]])[0]
            if orig_result[0] == "Email/get":
                orig_emails = orig_result[1].get("list", [])
                if orig_emails:
                    orig = orig_emails[0]
                    message_ids = orig.get("messageId", [])
                    if message_ids:
                        email_create["inReplyTo"] = message_ids[0]
                        # Build references chain
                        refs = list(orig.get("references", []))
                        refs.extend(message_ids)
                        email_create["references"] = refs

        # Get drafts mailbox for temporary storage
        drafts_response = await client._call(
            [
                [
                    "Mailbox/query",
                    {
                        "accountId": client.account_id,
                        "filter": {"role": "drafts"},
                    },
                    "drafts-query",
                ]
            ]
        )

        drafts_result = drafts_response.get("methodResponses", [[]])[0]
        drafts_mailbox_id = None
        if drafts_result[0] == "Mailbox/query":
            drafts_ids = drafts_result[1].get("ids", [])
            if drafts_ids:
                drafts_mailbox_id = drafts_ids[0]

        if not drafts_mailbox_id:
            return {
                "status": "error",
                "message": "Could not find drafts mailbox",
            }

        # Set mailbox and keywords
        email_create["mailboxIds"] = {drafts_mailbox_id: True}
        email_create["keywords"] = {"$draft": True}

        # Create email and submit in one call
        response = await client._call(
            [
                [
                    "Email/set",
                    {
                        "accountId": client.account_id,
                        "create": {"draft": email_create},
                    },
                    "email-create",
                ],
                [
                    "EmailSubmission/set",
                    {
                        "accountId": client.account_id,
                        "create": {
                            "send": {
                                "identityId": identity_id,
                                "emailId": "#draft",
                            }
                        },
                        "onSuccessUpdateEmail": {
                            "#send": {
                                "mailboxIds": {drafts_mailbox_id: None},  # Remove from drafts
                                "keywords": {"$draft": None, "$sent": True},
                            }
                        },
                    },
                    "email-submit",
                ],
            ]
        )

        method_responses = response.get("methodResponses", [])

        for resp in method_responses:
            if resp[0] == "error":
                return {
                    "status": "error",
                    "message": f"JMAP error: {resp[1].get('description', 'Unknown error')}",
                }

            if resp[0] == "Email/set":
                created = resp[1].get("created", {})
                not_created = resp[1].get("notCreated", {})
                if "draft" in not_created:
                    error = not_created["draft"]
                    return {
                        "status": "error",
                        "message": f"Failed to create email: {error.get('description', error.get('type'))}",
                    }

            if resp[0] == "EmailSubmission/set":
                created = resp[1].get("created", {})
                not_created = resp[1].get("notCreated", {})
                if "send" in not_created:
                    error = not_created["send"]
                    return {
                        "status": "error",
                        "message": f"Failed to send email: {error.get('description', error.get('type'))}",
                    }
                if "send" in created:
                    submission = created["send"]
                    email_id = submission.get("emailId")
                    logger.info(f"Email sent successfully: {email_id}")
                    return {
                        "status": "success",
                        "email_id": email_id,
                        "message": f"Email sent successfully to {', '.join(to)}",
                    }

        return {
            "status": "error",
            "message": "Unexpected response from server",
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error sending email: {e}")
        if e.response.status_code == 401:
            return {
                "status": "error",
                "message": "Authentication failed. Check your FastMail API token.",
            }
        return {
            "status": "error",
            "message": f"HTTP error: {e.response.status_code}",
        }
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def move_email(
    email_id: str,
    to_mailbox_id: str | None = None,
    to_mailbox_role: str | None = None,
    api_token: str | None = None,
) -> dict[str, Any]:
    """
    Move an email to a different mailbox.

    Moves the email from its current mailbox(es) to the specified destination.
    Can specify destination by ID or role (inbox, archive, trash, etc.).

    Args:
        email_id: The email ID to move
        to_mailbox_id: Destination mailbox ID (takes precedence over role)
        to_mailbox_role: Destination mailbox role: "inbox", "archive", "trash", etc.
        api_token: Optional FastMail API token.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - email_id: The moved email ID
            - mailbox_id: The destination mailbox ID
            - message: Status message
    """
    logger.info(f"Moving email {email_id} to mailbox_id={to_mailbox_id}, role={to_mailbox_role}")

    if not to_mailbox_id and not to_mailbox_role:
        return {
            "status": "error",
            "message": "Either to_mailbox_id or to_mailbox_role is required",
        }

    try:
        client = _get_client(api_token)

        # Resolve mailbox ID from role if needed
        target_mailbox_id = to_mailbox_id
        if not target_mailbox_id and to_mailbox_role:
            mailbox_response = await client._call(
                [
                    [
                        "Mailbox/query",
                        {
                            "accountId": client.account_id,
                            "filter": {"role": to_mailbox_role},
                        },
                        "find-mailbox",
                    ]
                ]
            )

            responses = mailbox_response.get("methodResponses", [])
            if responses and responses[0][0] == "Mailbox/query":
                ids = responses[0][1].get("ids", [])
                if ids:
                    target_mailbox_id = ids[0]
                else:
                    return {
                        "status": "error",
                        "message": f"No mailbox found with role: {to_mailbox_role}",
                    }

        # Get current mailboxes for the email
        get_response = await client._call(
            [
                [
                    "Email/get",
                    {
                        "accountId": client.account_id,
                        "ids": [email_id],
                        "properties": ["mailboxIds"],
                    },
                    "email-get",
                ]
            ]
        )

        get_result = get_response.get("methodResponses", [[]])[0]
        if get_result[0] == "error":
            return {
                "status": "error",
                "message": f"JMAP error: {get_result[1].get('description')}",
            }

        emails = get_result[1].get("list", [])
        not_found = get_result[1].get("notFound", [])

        if email_id in not_found:
            return {
                "status": "not_found",
                "message": f"Email not found: {email_id}",
            }

        if not emails:
            return {
                "status": "error",
                "message": "Could not retrieve email",
            }

        current_mailboxes = emails[0].get("mailboxIds", {})

        # Build update: remove from all current, add to target
        mailbox_update = {target_mailbox_id: True}
        for mailbox_id in current_mailboxes:
            if mailbox_id != target_mailbox_id:
                mailbox_update[mailbox_id] = None  # Remove

        # Update email
        response = await client._call(
            [
                [
                    "Email/set",
                    {
                        "accountId": client.account_id,
                        "update": {
                            email_id: {"mailboxIds": mailbox_update},
                        },
                    },
                    "email-move",
                ]
            ]
        )

        method_responses = response.get("methodResponses", [])
        if not method_responses:
            return {
                "status": "error",
                "message": "No response from server",
            }

        result = method_responses[0]
        if result[0] == "error":
            return {
                "status": "error",
                "message": f"JMAP error: {result[1].get('description')}",
            }

        updated = result[1].get("updated", {})
        not_updated = result[1].get("notUpdated", {})

        if email_id in not_updated:
            error = not_updated[email_id]
            return {
                "status": "error",
                "message": f"Failed to move email: {error.get('description', error.get('type'))}",
            }

        if email_id in updated or updated is None:
            logger.info(f"Email moved to mailbox {target_mailbox_id}")
            return {
                "status": "success",
                "email_id": email_id,
                "mailbox_id": target_mailbox_id,
                "message": "Email moved successfully",
            }

        return {
            "status": "error",
            "message": "Unexpected response from server",
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error moving email: {e}")
        if e.response.status_code == 401:
            return {
                "status": "error",
                "message": "Authentication failed. Check your FastMail API token.",
            }
        return {
            "status": "error",
            "message": f"HTTP error: {e.response.status_code}",
        }
    except Exception as e:
        logger.error(f"Error moving email: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def update_email_flags(
    email_id: str,
    mark_read: bool | None = None,
    mark_flagged: bool | None = None,
    api_token: str | None = None,
) -> dict[str, Any]:
    """
    Update email flags (read/unread, flagged/unflagged).

    Modifies the read status and/or flagged status of an email.

    Args:
        email_id: The email ID to update
        mark_read: Set to True to mark as read, False for unread, None to leave unchanged
        mark_flagged: Set to True to flag, False to unflag, None to leave unchanged
        api_token: Optional FastMail API token.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - email_id: The updated email ID
            - is_read: Current read status
            - is_flagged: Current flagged status
            - message: Status message
    """
    logger.info(f"Updating flags for email {email_id}: read={mark_read}, flagged={mark_flagged}")

    if mark_read is None and mark_flagged is None:
        return {
            "status": "error",
            "message": "At least one of mark_read or mark_flagged must be specified",
        }

    try:
        client = _get_client(api_token)

        # Build keywords update
        keywords_update: dict[str, bool | None] = {}

        if mark_read is not None:
            keywords_update["$seen"] = True if mark_read else None

        if mark_flagged is not None:
            keywords_update["$flagged"] = True if mark_flagged else None

        response = await client._call(
            [
                [
                    "Email/set",
                    {
                        "accountId": client.account_id,
                        "update": {
                            email_id: {"keywords": keywords_update},
                        },
                    },
                    "email-flags",
                ]
            ]
        )

        method_responses = response.get("methodResponses", [])
        if not method_responses:
            return {
                "status": "error",
                "message": "No response from server",
            }

        result = method_responses[0]
        if result[0] == "error":
            return {
                "status": "error",
                "message": f"JMAP error: {result[1].get('description')}",
            }

        _updated = result[1].get("updated", {})  # Reserved for future validation
        not_updated = result[1].get("notUpdated", {})

        if email_id in not_updated:
            error = not_updated[email_id]
            if error.get("type") == "notFound":
                return {
                    "status": "not_found",
                    "message": f"Email not found: {email_id}",
                }
            return {
                "status": "error",
                "message": f"Failed to update email: {error.get('description', error.get('type'))}",
            }

        logger.info(f"Email flags updated: {email_id}")
        return {
            "status": "success",
            "email_id": email_id,
            "is_read": mark_read if mark_read is not None else None,
            "is_flagged": mark_flagged if mark_flagged is not None else None,
            "message": "Email flags updated successfully",
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error updating email flags: {e}")
        if e.response.status_code == 401:
            return {
                "status": "error",
                "message": "Authentication failed. Check your FastMail API token.",
            }
        return {
            "status": "error",
            "message": f"HTTP error: {e.response.status_code}",
        }
    except Exception as e:
        logger.error(f"Error updating email flags: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def delete_email(
    email_id: str,
    permanent: bool = False,
    api_token: str | None = None,
) -> dict[str, Any]:
    """
    Delete an email (move to trash or permanently delete).

    By default, moves the email to trash. Set permanent=True to permanently
    delete the email (cannot be undone).

    Args:
        email_id: The email ID to delete
        permanent: If True, permanently delete. If False (default), move to trash.
        api_token: Optional FastMail API token.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - email_id: The deleted email ID
            - permanent: Whether it was permanently deleted
            - message: Status message
    """
    logger.info(f"Deleting email {email_id}, permanent={permanent}")

    try:
        client = _get_client(api_token)

        if permanent:
            # Permanently delete
            response = await client._call(
                [
                    [
                        "Email/set",
                        {
                            "accountId": client.account_id,
                            "destroy": [email_id],
                        },
                        "email-delete",
                    ]
                ]
            )

            method_responses = response.get("methodResponses", [])
            if not method_responses:
                return {
                    "status": "error",
                    "message": "No response from server",
                }

            result = method_responses[0]
            if result[0] == "error":
                return {
                    "status": "error",
                    "message": f"JMAP error: {result[1].get('description')}",
                }

            destroyed = result[1].get("destroyed", [])
            not_destroyed = result[1].get("notDestroyed", {})

            if email_id in not_destroyed:
                error = not_destroyed[email_id]
                if error.get("type") == "notFound":
                    return {
                        "status": "not_found",
                        "message": f"Email not found: {email_id}",
                    }
                return {
                    "status": "error",
                    "message": f"Failed to delete email: {error.get('description', error.get('type'))}",
                }

            if email_id in destroyed:
                logger.info(f"Email permanently deleted: {email_id}")
                return {
                    "status": "success",
                    "email_id": email_id,
                    "permanent": True,
                    "message": "Email permanently deleted",
                }

            return {
                "status": "error",
                "message": "Unexpected response from server",
            }

        else:
            # Move to trash
            result = await move_email(
                email_id=email_id,
                to_mailbox_role="trash",
                api_token=api_token,
            )

            if result["status"] == "success":
                result["permanent"] = False
                result["message"] = "Email moved to trash"

            return result

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error deleting email: {e}")
        if e.response.status_code == 401:
            return {
                "status": "error",
                "message": "Authentication failed. Check your FastMail API token.",
            }
        return {
            "status": "error",
            "message": f"HTTP error: {e.response.status_code}",
        }
    except Exception as e:
        logger.error(f"Error deleting email: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


# ---------------------------------------------------------------------------
# Tool schema for MCP server auto-registration
# ---------------------------------------------------------------------------

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
]
