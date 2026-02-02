"""Email sending operations for FastMail.

Contains send_email and send_agent_report functions.
"""

import logging
from typing import Any

from .client import _get_client
from .helpers import _handle_jmap_error

logger = logging.getLogger(__name__)


async def send_email(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    reply_to_email_id: str | None = None,
    is_html: bool = False,
    identity_email: str | None = None,
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
        identity_email: Optional email address to send from. Must match a configured
            identity in FastMail. If not specified, uses the primary identity.
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
        await client._ensure_session()

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

        # Select identity based on identity_email parameter or use primary
        identity = None
        use_custom_from = False  # Track if we're using catch-all with custom address
        if identity_email:
            # First try exact match
            for ident in identities:
                if ident.get("email", "").lower() == identity_email.lower():
                    identity = ident
                    break

            # If no exact match, try catch-all pattern (*@domain)
            if not identity:
                requested_domain = identity_email.lower().split("@")[-1]
                for ident in identities:
                    ident_email = ident.get("email", "").lower()
                    # Check for catch-all pattern like *@domain
                    if ident_email.startswith("*@"):
                        catch_all_domain = ident_email[2:]  # Remove "*@" prefix
                        if catch_all_domain == requested_domain:
                            identity = ident
                            use_custom_from = True  # Use requested address, not *@domain
                            break

            if not identity:
                available = [i.get("email") for i in identities]
                return {
                    "status": "error",
                    "message": f"Identity '{identity_email}' not found. Available identities: {available}",
                }
        else:
            # Use the first identity (primary)
            identity = identities[0]

        identity_id = identity["id"]
        # Use requested email if we matched a catch-all, otherwise use identity's email
        from_address = identity_email if use_custom_from else identity.get("email")
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

        # Get drafts and sent mailboxes
        mailbox_response = await client._call(
            [
                [
                    "Mailbox/query",
                    {
                        "accountId": client.account_id,
                        "filter": {"role": "drafts"},
                    },
                    "drafts-query",
                ],
                [
                    "Mailbox/query",
                    {
                        "accountId": client.account_id,
                        "filter": {"role": "sent"},
                    },
                    "sent-query",
                ],
            ]
        )

        drafts_mailbox_id = None
        sent_mailbox_id = None
        for resp in mailbox_response.get("methodResponses", []):
            if resp[0] == "Mailbox/query":
                ids = resp[1].get("ids") or []
                if resp[2] == "drafts-query" and ids:
                    drafts_mailbox_id = ids[0]
                elif resp[2] == "sent-query" and ids:
                    sent_mailbox_id = ids[0]

        if not drafts_mailbox_id:
            return {
                "status": "error",
                "message": "Could not find drafts mailbox",
            }

        if not sent_mailbox_id:
            return {
                "status": "error",
                "message": "Could not find sent mailbox",
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
                                # Move from drafts to sent using JMAP patch notation
                                f"mailboxIds/{drafts_mailbox_id}": None,
                                f"mailboxIds/{sent_mailbox_id}": True,
                                "keywords/$draft": None,
                                "keywords/$sent": True,
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
                created = resp[1].get("created") or {}
                not_created = resp[1].get("notCreated") or {}
                if "draft" in not_created:
                    error = not_created["draft"]
                    return {
                        "status": "error",
                        "message": f"Failed to create email: {error.get('description', error.get('type'))}",
                    }

            if resp[0] == "EmailSubmission/set":
                created = resp[1].get("created") or {}
                not_created = resp[1].get("notCreated") or {}
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

    except Exception as e:
        return _handle_jmap_error(e, "sending email")


async def send_agent_report(
    subject: str,
    body: str,
    is_html: bool = False,
    agent_name: str | None = None,
    api_token: str | None = None,
) -> dict[str, Any]:
    """
    Send a report/notification email from an agent to the admin.

    This tool is designed for agents to send status updates, reports, and
    notifications. The sender email is automatically derived from the agent name
    (e.g., chatbot@brooksmcmillin.com) and the recipient is the configured
    admin email address.

    IMPORTANT: This tool requires:
    1. ADMIN_EMAIL_ADDRESS environment variable set
    2. AGENT_EMAIL_DOMAIN environment variable (defaults to brooksmcmillin.com)
    3. The agent's email identity configured in FastMail

    The agent_name parameter is automatically injected by the Agent class.

    Args:
        subject: Email subject line
        body: Email body content (plain text or HTML)
        is_html: If True, body is treated as HTML (default: False for plain text)
        agent_name: Agent name (auto-injected by Agent class). Used to derive
            the sender email address as {agent_name}@{domain}.
        api_token: Optional FastMail API token.

    Returns:
        Dictionary containing:
            - status: "success" or "error"
            - email_id: ID of the created email (on success)
            - from_address: The sender email address used
            - to_address: The admin email address
            - message: Status message
    """
    from ...core.config import settings

    # Validate required configuration
    if not settings.admin_email_address:
        return {
            "status": "error",
            "message": "ADMIN_EMAIL_ADDRESS environment variable is not configured. "
            "Set it to the email address where agent reports should be sent.",
        }

    if not agent_name:
        return {
            "status": "error",
            "message": "agent_name is required. This should be auto-injected by the Agent class.",
        }

    # Derive agent email from agent name and domain
    # Sanitize agent name for email (lowercase, replace spaces/underscores with hyphens)
    safe_agent_name = agent_name.lower().replace("_", "-").replace(" ", "-")
    # Remove any characters that aren't valid in email local part
    safe_agent_name = "".join(c for c in safe_agent_name if c.isalnum() or c == "-")
    from_email = f"{safe_agent_name}@{settings.agent_email_domain}"

    logger.info(
        f"Agent '{agent_name}' sending report to {settings.admin_email_address} "
        f"from {from_email}, subject: {subject}"
    )

    # Use send_email with the agent's identity
    result = await send_email(
        to=[settings.admin_email_address],
        subject=subject,
        body=body,
        is_html=is_html,
        identity_email=from_email,
        api_token=api_token,
    )

    # Return new dict with additional context (avoid mutating send_email's return value)
    return {
        **result,
        "from_address": from_email,
        "to_address": settings.admin_email_address,
    }
