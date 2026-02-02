"""Email sending operations for FastMail.

Contains send_email and send_agent_report functions.
"""

import logging
from typing import Any

from ...core.config import settings
from .client import JMAPClient, _get_client
from .helpers import (
    _handle_jmap_error,
    _is_recipient_allowed,
    _sanitize_html,
    _validate_email_list,
)

logger = logging.getLogger(__name__)


def _get_allowed_recipients() -> list[str]:
    """Get the list of allowed email recipients from settings.

    Returns:
        List of allowed recipient patterns. Always includes admin_email_address.
    """
    allowed = []

    # Admin email is always allowed
    if settings.admin_email_address:
        allowed.append(settings.admin_email_address)

    # Parse comma-separated allowlist
    if settings.allowed_email_recipients:
        patterns = [p.strip() for p in settings.allowed_email_recipients.split(",")]
        allowed.extend(p for p in patterns if p)

    return allowed


def _check_recipients_allowed(
    recipients: list[str], allowed_patterns: list[str]
) -> tuple[bool, list[str]]:
    """Check if all recipients are in the allowed list.

    Args:
        recipients: List of email addresses to check
        allowed_patterns: List of allowed patterns

    Returns:
        Tuple of (all_allowed, list_of_disallowed_emails)
    """
    disallowed = [r for r in recipients if not _is_recipient_allowed(r, allowed_patterns)]
    return len(disallowed) == 0, disallowed


def _collect_all_recipients(
    to: list[str],
    cc: list[str] | None,
    bcc: list[str] | None,
) -> list[str]:
    """Collect all recipients from to, cc, and bcc into a single list.

    Args:
        to: List of recipient email addresses
        cc: Optional CC recipients
        bcc: Optional BCC recipients

    Returns:
        Combined list of all recipient addresses.
    """
    all_recipients = list(to)
    if cc:
        all_recipients.extend(cc)
    if bcc:
        all_recipients.extend(bcc)
    return all_recipients


def _validate_send_inputs(
    to: list[str],
    subject: str,
    cc: list[str] | None,
    bcc: list[str] | None,
) -> dict[str, Any] | None:
    """Validate required fields and email formats.

    Args:
        to: List of recipient email addresses
        subject: Email subject line
        cc: Optional CC recipients
        bcc: Optional BCC recipients

    Returns:
        Error dict if validation fails, None if valid.
    """
    if not to:
        return {"status": "error", "message": "At least one recipient (to) is required"}

    if not subject:
        return {"status": "error", "message": "Subject is required"}

    # Validate email address formats
    valid, invalid_emails = _validate_email_list(_collect_all_recipients(to, cc, bcc))
    if not valid:
        return {
            "status": "error",
            "message": f"Invalid email address format: {', '.join(invalid_emails)}",
        }

    return None


def _validate_security_allowlist(
    to: list[str],
    cc: list[str] | None,
    bcc: list[str] | None,
) -> dict[str, Any] | None:
    """Validate recipients against security allowlist.

    Args:
        to: List of recipient email addresses
        cc: Optional CC recipients
        bcc: Optional BCC recipients

    Returns:
        Error dict if validation fails, None if valid.
    """
    all_recipients = _collect_all_recipients(to, cc, bcc)
    allowed_patterns = _get_allowed_recipients()
    if not allowed_patterns:
        return {
            "status": "error",
            "message": "Email sending is disabled. Configure ALLOWED_EMAIL_RECIPIENTS or "
            "ADMIN_EMAIL_ADDRESS environment variable to enable.",
        }

    allowed, disallowed = _check_recipients_allowed(all_recipients, allowed_patterns)
    if not allowed:
        logger.warning(f"Blocked email to unauthorized recipients: {disallowed}")
        return {
            "status": "error",
            "message": f"Recipients not in allowed list: {', '.join(disallowed)}. "
            "Configure ALLOWED_EMAIL_RECIPIENTS to allow additional recipients.",
        }

    return None


async def _resolve_sender_identity(
    client: JMAPClient,
    identity_email: str | None,
) -> dict[str, Any] | tuple[str, str, str]:
    """Resolve the sender identity from FastMail.

    Args:
        client: FastMail client with active session
        identity_email: Optional specific identity email to use

    Returns:
        Error dict if resolution fails, or tuple of (identity_id, from_address, from_name).
    """
    identity_response = await client._call(
        [["Identity/get", {"accountId": client.account_id}, "identity-get"]]
    )

    identity_result = identity_response.get("methodResponses", [[]])[0]
    if identity_result[0] == "error":
        return {
            "status": "error",
            "message": f"Failed to get identity: {identity_result[1].get('description')}",
        }

    identities = identity_result[1].get("list", [])
    if not identities:
        return {"status": "error", "message": "No email identity found. Cannot send email."}

    identity = None
    use_custom_from = False

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
                if ident_email.startswith("*@"):
                    catch_all_domain = ident_email[2:]
                    if catch_all_domain == requested_domain:
                        identity = ident
                        use_custom_from = True
                        break

        if not identity:
            available = [i.get("email") for i in identities]
            return {
                "status": "error",
                "message": f"Identity '{identity_email}' not found. Available identities: {available}",
            }
    else:
        identity = identities[0]

    identity_id = identity.get("id")
    if not identity_id:
        return {"status": "error", "message": "Identity has no ID configured."}
    from_name: str = identity.get("name", "")
    from_address: str

    # Determine sender address: use requested email for catch-all, otherwise identity's email
    if use_custom_from and identity_email:
        from_address = identity_email
    else:
        ident_email = identity.get("email")
        if not ident_email:
            return {"status": "error", "message": "Identity has no email address configured."}
        from_address = ident_email

    return (identity_id, from_address, from_name)


def _build_email_object(
    to: list[str],
    subject: str,
    body: str,
    is_html: bool,
    from_address: str,
    from_name: str,
    cc: list[str] | None,
    bcc: list[str] | None,
) -> dict[str, Any]:
    """Build the JMAP email object.

    Args:
        to: List of recipient email addresses
        subject: Email subject line
        body: Email body content
        is_html: Whether body is HTML
        from_address: Sender email address
        from_name: Sender display name
        cc: Optional CC recipients
        bcc: Optional BCC recipients

    Returns:
        JMAP email create object.
    """
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

    # Set body based on content type
    if is_html:
        email_create["htmlBody"] = [{"partId": "body", "type": "text/html"}]
    else:
        email_create["textBody"] = [{"partId": "body", "type": "text/plain"}]
    email_create["bodyValues"] = {"body": {"value": body, "isEncodingProblem": False}}

    return email_create


async def _add_reply_threading(
    client: JMAPClient,
    email_create: dict[str, Any],
    reply_to_email_id: str,
) -> None:
    """Add reply threading headers to the email object.

    Modifies email_create in place to add inReplyTo and references headers.

    Args:
        client: FastMail client with active session
        email_create: Email object to modify
        reply_to_email_id: ID of email being replied to
    """
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

    if orig_result[0] == "error":
        logger.warning(
            f"Failed to get reply email {reply_to_email_id} for threading: "
            f"{orig_result[1].get('description', 'Unknown error')}. Sending without threading."
        )
        return

    if orig_result[0] != "Email/get":
        logger.warning(
            f"Unexpected response getting reply email {reply_to_email_id}. Sending without threading."
        )
        return

    orig_emails = orig_result[1].get("list", [])
    if not orig_emails:
        logger.warning(f"Reply email {reply_to_email_id} not found. Sending without threading.")
        return

    orig = orig_emails[0]
    message_ids = orig.get("messageId", [])
    if not message_ids:
        logger.warning(
            f"Reply email {reply_to_email_id} has no messageId. Sending without threading."
        )
        return

    email_create["inReplyTo"] = message_ids[0]
    refs = list(orig.get("references", []))
    refs.extend(message_ids)
    email_create["references"] = refs


async def _get_send_mailboxes(
    client: JMAPClient,
) -> dict[str, Any] | tuple[str, str]:
    """Get the drafts and sent mailbox IDs.

    Args:
        client: FastMail client with active session

    Returns:
        Error dict if mailboxes not found, or tuple of (drafts_id, sent_id).
    """
    mailbox_response = await client._call(
        [
            [
                "Mailbox/query",
                {"accountId": client.account_id, "filter": {"role": "drafts"}},
                "drafts-query",
            ],
            [
                "Mailbox/query",
                {"accountId": client.account_id, "filter": {"role": "sent"}},
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
        return {"status": "error", "message": "Could not find drafts mailbox"}
    if not sent_mailbox_id:
        return {"status": "error", "message": "Could not find sent mailbox"}

    return (drafts_mailbox_id, sent_mailbox_id)


async def _submit_email(
    client: JMAPClient,
    email_create: dict[str, Any],
    identity_id: str,
    drafts_mailbox_id: str,
    sent_mailbox_id: str,
    to: list[str],
) -> dict[str, Any]:
    """Create and submit the email via JMAP.

    Args:
        client: FastMail client with active session
        email_create: Email object to send
        identity_id: Identity ID to send from
        drafts_mailbox_id: Drafts mailbox ID
        sent_mailbox_id: Sent mailbox ID
        to: List of recipients (for success message)

    Returns:
        Result dict with status, email_id, and message.
    """
    # Set mailbox and draft keyword
    email_create["mailboxIds"] = {drafts_mailbox_id: True}
    email_create["keywords"] = {"$draft": True}

    response = await client._call(
        [
            [
                "Email/set",
                {"accountId": client.account_id, "create": {"draft": email_create}},
                "email-create",
            ],
            [
                "EmailSubmission/set",
                {
                    "accountId": client.account_id,
                    "create": {"send": {"identityId": identity_id, "emailId": "#draft"}},
                    "onSuccessUpdateEmail": {
                        "#send": {
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

    return _process_send_response(response, to)


def _process_send_response(response: dict[str, Any], to: list[str]) -> dict[str, Any]:
    """Process the JMAP response from email submission.

    Args:
        response: JMAP response dict
        to: List of recipients (for success message)

    Returns:
        Result dict with status, email_id, and message.
    """
    for resp in response.get("methodResponses", []):
        if resp[0] == "error":
            return {
                "status": "error",
                "message": f"JMAP error: {resp[1].get('description', 'Unknown error')}",
            }

        if resp[0] == "Email/set":
            not_created = resp[1].get("notCreated") or {}
            if "draft" in not_created:
                error = not_created["draft"]
                return {
                    "status": "error",
                    "message": f"Failed to create email: {error.get('description', error.get('type'))}",
                }

        if resp[0] == "EmailSubmission/set":
            submission_result = resp[1]
            not_created = submission_result.get("notCreated") or {}
            if "send" in not_created:
                error = not_created["send"]
                return {
                    "status": "error",
                    "message": f"Failed to send email: {error.get('description', error.get('type'))}",
                }
            created_send = (submission_result.get("created") or {}).get("send")
            if created_send:
                email_id = created_send.get("emailId")
                logger.info(f"Email sent successfully: {email_id}")
                return {
                    "status": "success",
                    "email_id": email_id,
                    "message": f"Email sent successfully to {', '.join(to)}",
                }

    return {"status": "error", "message": "Unexpected response from server"}


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

    SECURITY: Recipients are validated against ALLOWED_EMAIL_RECIPIENTS environment
    variable. If not configured, only ADMIN_EMAIL_ADDRESS can receive emails.

    Args:
        to: List of recipient email addresses
        subject: Email subject line
        body: Email body content (plain text or HTML)
        cc: Optional list of CC recipients
        bcc: Optional list of BCC recipients
        reply_to_email_id: Optional email ID to reply to (sets In-Reply-To header)
        is_html: If True, body is treated as HTML (default: False for plain text).
            HTML content is sanitized to prevent XSS.
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

    # Validate inputs
    if error := _validate_send_inputs(to, subject, cc, bcc):
        return error

    # Check security allowlist
    if error := _validate_security_allowlist(to, cc, bcc):
        return error

    # Sanitize HTML content if needed
    if is_html:
        body = _sanitize_html(body)

    try:
        client = _get_client(api_token)
        await client._ensure_session()

        # Resolve sender identity
        identity_result = await _resolve_sender_identity(client, identity_email)
        if isinstance(identity_result, dict):
            return identity_result
        identity_id, from_address, from_name = identity_result

        # Build email object
        email_create = _build_email_object(
            to, subject, body, is_html, from_address, from_name, cc, bcc
        )

        # Add reply threading if replying
        if reply_to_email_id:
            await _add_reply_threading(client, email_create, reply_to_email_id)

        # Get mailbox IDs
        mailbox_result = await _get_send_mailboxes(client)
        if isinstance(mailbox_result, dict):
            return mailbox_result
        drafts_mailbox_id, sent_mailbox_id = mailbox_result

        # Submit the email
        return await _submit_email(
            client, email_create, identity_id, drafts_mailbox_id, sent_mailbox_id, to
        )

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
