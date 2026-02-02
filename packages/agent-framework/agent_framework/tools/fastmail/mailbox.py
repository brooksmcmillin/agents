"""Mailbox operations for FastMail.

Contains the list_mailboxes function.
"""

import logging
from typing import Any

from .client import _get_client
from .helpers import _format_mailbox, _handle_jmap_error

logger = logging.getLogger(__name__)


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
        await client._ensure_session()

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

    except Exception as e:
        return _handle_jmap_error(e, "listing mailboxes")
