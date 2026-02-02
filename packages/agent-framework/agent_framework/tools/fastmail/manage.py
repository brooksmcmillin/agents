"""Email management operations for FastMail.

Contains move_email, update_email_flags, and delete_email functions.
"""

import logging
from typing import Any

from .client import _get_client
from .helpers import _handle_jmap_error

logger = logging.getLogger(__name__)


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
        await client._ensure_session()

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
        # Ensure target_mailbox_id is str for type checking
        target_mailbox_id = str(target_mailbox_id)
        mailbox_update: dict[str, bool | None] = {target_mailbox_id: True}
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

        updated = result[1].get("updated") or {}
        not_updated = result[1].get("notUpdated") or {}

        if email_id in not_updated:
            error = not_updated[email_id]
            return {
                "status": "error",
                "message": f"Failed to move email: {error.get('description', error.get('type'))}",
            }

        if email_id in updated or not updated:
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

    except Exception as e:
        return _handle_jmap_error(e, "moving email")


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
        await client._ensure_session()

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

        _updated = result[1].get("updated") or {}  # Reserved for future validation
        not_updated = result[1].get("notUpdated") or {}

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

    except Exception as e:
        return _handle_jmap_error(e, "updating email flags")


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
        await client._ensure_session()

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

            destroyed = result[1].get("destroyed") or []
            not_destroyed = result[1].get("notDestroyed") or {}

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

    except Exception as e:
        return _handle_jmap_error(e, "deleting email")
