"""Email reading operations for FastMail.

Contains get_emails, get_email, and search_emails functions.
"""

import logging
from typing import Any

from .client import _get_client
from .helpers import _format_email_full, _format_email_summary, _handle_jmap_error

logger = logging.getLogger(__name__)


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
        await client._ensure_session()

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

    except Exception as e:
        return _handle_jmap_error(e, "getting emails")


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
        await client._ensure_session()

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

    except Exception as e:
        return _handle_jmap_error(e, "getting email")


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
        await client._ensure_session()

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

    except Exception as e:
        return _handle_jmap_error(e, "searching emails")
