"""Twilio SMS Clarification tools for two-way agent-admin conversations.

This module provides tools for agents to request clarification from the admin
via SMS and receive replies. It uses a phone pool to enable routing replies
back to the correct conversation.

Flow:
1. Agent calls send_sms_clarification with a question
2. Tool acquires a phone from the pool, sends SMS, locks phone to conversation
3. Admin receives SMS and replies
4. Webhook receives reply, looks up conversation by phone, routes reply
5. Phone is released back to pool

Requires:
- DATABASE_URL environment variable for phone pool storage
- TWILIO_PHONE_POOL environment variable with comma-separated phone numbers
- TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN for Twilio API
- ADMIN_PHONE_NUMBER for recipient
"""

import logging
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

from ..core.config import settings
from ..security import mask_phone_number
from ..storage.sms_phone_pool import SMSPhonePoolManager

logger = logging.getLogger(__name__)

# E.164 phone number format: +[country code][number]
E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")

# Twilio Account SID format: AC followed by 32 hex characters
ACCOUNT_SID_PATTERN = re.compile(r"^AC[a-f0-9]{32}$", re.IGNORECASE)

# Global phone pool manager - initialized lazily
_phone_pool: SMSPhonePoolManager | None = None


def _get_phone_pool() -> SMSPhonePoolManager | None:
    """Get or create the phone pool manager.

    Returns None if not configured (no DATABASE_URL or no TWILIO_PHONE_POOL).
    """
    global _phone_pool
    if _phone_pool is not None:
        return _phone_pool

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None

    phone_pool_config = settings.twilio_phone_pool
    if not phone_pool_config:
        return None

    # Parse comma-separated phone numbers
    phone_numbers = [p.strip() for p in phone_pool_config.split(",") if p.strip()]
    if not phone_numbers:
        return None

    _phone_pool = SMSPhonePoolManager(
        database_url=database_url,
        phone_numbers=phone_numbers,
        default_lock_timeout_minutes=settings.sms_lock_timeout_minutes,
    )
    return _phone_pool


def _validate_phone_number(phone: str, field_name: str) -> str:
    """Validate and normalize phone number to E.164 format."""
    # Strip whitespace and common separators
    normalized = re.sub(r"[\s\-\(\)\.]", "", phone)

    if not normalized.startswith("+"):
        if len(normalized) == 10 and normalized.isdigit():
            normalized = f"+1{normalized}"
        elif (
            (normalized.startswith("1") and len(normalized) == 11 and normalized.isdigit())
            or (normalized.isdigit() and len(normalized) >= 7)
        ):  # fmt: skip
            normalized = f"+{normalized}"
        else:
            raise ValueError(
                f"Invalid {field_name}: '{phone}'. Must be in E.164 format "
                "(e.g., +15551234567) or a 10-digit US number."
            )

    if not E164_PATTERN.match(normalized):
        raise ValueError(
            f"Invalid {field_name}: '{phone}'. Must be in E.164 format "
            "(e.g., +15551234567) or a 10-digit US number."
        )

    return normalized


def _sanitize_error_message(error: Exception) -> str:
    """Sanitize error message to avoid exposing sensitive data."""
    error_str = str(error)
    sanitized = re.sub(r"[a-f0-9]{32}", "[REDACTED]", error_str, flags=re.IGNORECASE)
    sanitized = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"Basic\s+\S+", "Basic [REDACTED]", sanitized, flags=re.IGNORECASE)
    return sanitized


async def send_sms_clarification(
    question: str,
    conversation_id: str,
    agent_name: str | None = None,
    timeout_minutes: int | None = None,
) -> dict[str, Any]:
    """
    Send an SMS to the admin requesting clarification, with reply tracking.

    This tool acquires a phone number from the pool and sends an SMS to the admin.
    The phone is locked to the conversation until the admin replies or the timeout
    expires. When the admin replies, the webhook routes the response back to this
    conversation.

    If no phone is available in the pool, falls back to sending an email instead.

    IMPORTANT: This tool requires:
    1. DATABASE_URL for phone pool storage
    2. TWILIO_PHONE_POOL with comma-separated Twilio phone numbers
    3. ADMIN_PHONE_NUMBER for the recipient
    4. TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN for Twilio API

    The conversation_id is required to enable reply routing.

    Args:
        question: The clarification question to ask the admin (max 1400 chars
            to leave room for agent prefix and formatting)
        conversation_id: The conversation ID to associate with this request
            (required for routing admin replies)
        agent_name: Agent name (auto-injected by Agent class)
        timeout_minutes: How long to wait for a reply before releasing the phone
            (defaults to SMS_LOCK_TIMEOUT_MINUTES, typically 30 minutes)

    Returns:
        Dictionary containing:
            - success: Boolean indicating if clarification request was sent
            - method: "sms" or "email" (fallback)
            - phone_number: The Twilio phone number used (if SMS)
            - message_sid: Twilio message SID for tracking (if SMS)
            - expires_at: When the phone lock expires (if SMS)
            - fallback_reason: Why email was used instead (if email)
            - error: Error message if failed completely
    """
    # Validate inputs
    if not question:
        return {
            "success": False,
            "error": "question is required - cannot send empty clarification request",
        }

    if not conversation_id:
        return {
            "success": False,
            "error": "conversation_id is required for reply routing",
        }

    if len(question) > 1400:
        return {
            "success": False,
            "error": f"Question too long ({len(question)} characters). Maximum is 1400 "
            "characters to leave room for formatting.",
        }

    # Get phone pool
    phone_pool = _get_phone_pool()
    if phone_pool is None:
        return await _fallback_to_email(
            question=question,
            agent_name=agent_name,
            fallback_reason="SMS phone pool not configured (missing DATABASE_URL or TWILIO_PHONE_POOL)",
        )

    # Validate Twilio credentials
    account_sid = settings.twilio_account_sid
    auth_token = settings.twilio_auth_token

    if not account_sid or not auth_token:
        return await _fallback_to_email(
            question=question,
            agent_name=agent_name,
            fallback_reason="Twilio credentials not configured",
        )

    if not settings.admin_phone_number:
        return await _fallback_to_email(
            question=question,
            agent_name=agent_name,
            fallback_reason="ADMIN_PHONE_NUMBER not configured",
        )

    # Validate phone number
    try:
        to_normalized = _validate_phone_number(settings.admin_phone_number, "ADMIN_PHONE_NUMBER")
    except ValueError as e:
        return await _fallback_to_email(
            question=question,
            agent_name=agent_name,
            fallback_reason=str(e),
        )

    # Try to acquire a phone from the pool
    try:
        await phone_pool.initialize()
        phone_entry = await phone_pool.acquire(
            conversation_id=conversation_id,
            agent_name=agent_name or "unknown",
            question_text=question,
            timeout_minutes=timeout_minutes,
        )
    except Exception as e:
        logger.exception("Failed to acquire phone from pool")
        return await _fallback_to_email(
            question=question,
            agent_name=agent_name,
            fallback_reason=f"Phone pool error: {_sanitize_error_message(e)}",
        )

    if phone_entry is None:
        return await _fallback_to_email(
            question=question,
            agent_name=agent_name,
            fallback_reason="All SMS phone numbers are in use (pool exhausted)",
        )

    # Validate the acquired phone number
    try:
        from_normalized = _validate_phone_number(phone_entry.phone_number, "pool phone number")
    except ValueError as e:
        await phone_pool.release(phone_entry.phone_number)
        return await _fallback_to_email(
            question=question,
            agent_name=agent_name,
            fallback_reason=str(e),
        )

    # Build message
    if agent_name:
        safe_agent_name = agent_name.replace("_", "-").title()
        message_body = f"[{safe_agent_name}] {question}\n\n(Reply to this message to respond)"
    else:
        message_body = f"{question}\n\n(Reply to this message to respond)"

    # Send SMS via Twilio
    payload = {
        "To": to_normalized,
        "From": from_normalized,
        "Body": message_body,
    }

    url = f"https://api.twilio.com/2010-04-01/Accounts/{quote(account_sid, safe='')}/Messages.json"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                data=payload,
                auth=(account_sid, auth_token),
            )

            try:
                result = response.json()
            except ValueError:
                await phone_pool.release(phone_entry.phone_number)
                logger.error("Invalid JSON response from Twilio API")
                return await _fallback_to_email(
                    question=question,
                    agent_name=agent_name,
                    fallback_reason=f"Invalid Twilio response (status {response.status_code})",
                )

            if response.status_code == 201:
                message_sid = result.get("sid")

                # Update phone entry with message SID
                await phone_pool.update_message_sid(phone_entry.phone_number, message_sid)

                logger.info(
                    "SMS clarification sent from %s for conversation %s (agent: %s)",
                    mask_phone_number(from_normalized),
                    conversation_id,
                    agent_name or "unknown",
                )

                return {
                    "success": True,
                    "method": "sms",
                    "phone_number": from_normalized,
                    "message_sid": message_sid,
                    "to": to_normalized,
                    "status": result.get("status"),
                    "expires_at": phone_entry.lock_expires_at.isoformat()
                    if phone_entry.lock_expires_at
                    else None,
                    "conversation_id": conversation_id,
                    "message": "Clarification request sent. The conversation will resume when "
                    "the admin replies via SMS.",
                }
            else:
                await phone_pool.release(phone_entry.phone_number)
                error_code = result.get("code")
                error_message = result.get("message", "Unknown error")
                logger.error(f"Twilio API error: {error_code} - {error_message}")

                return await _fallback_to_email(
                    question=question,
                    agent_name=agent_name,
                    fallback_reason=f"Twilio error {error_code}: {error_message}",
                )

    except httpx.HTTPError as e:
        await phone_pool.release(phone_entry.phone_number)
        sanitized_error = _sanitize_error_message(e)
        logger.error(f"HTTP error sending SMS: {sanitized_error}")
        return await _fallback_to_email(
            question=question,
            agent_name=agent_name,
            fallback_reason=f"Network error: {sanitized_error}",
        )

    except Exception as e:
        await phone_pool.release(phone_entry.phone_number)
        sanitized_error = _sanitize_error_message(e)
        logger.error(f"Error sending SMS clarification: {sanitized_error}")
        return await _fallback_to_email(
            question=question,
            agent_name=agent_name,
            fallback_reason=f"Unexpected error: {sanitized_error}",
        )


async def _fallback_to_email(
    question: str,
    agent_name: str | None,
    fallback_reason: str,
) -> dict[str, Any]:
    """
    Fall back to sending clarification request via email.

    Args:
        question: The clarification question
        agent_name: Agent name for the email
        fallback_reason: Why SMS failed

    Returns:
        Result dictionary
    """
    try:
        from .fastmail import send_agent_report

        subject = "Clarification Needed (SMS unavailable)"
        body = f"""A clarification is needed but SMS was unavailable.

Reason: {fallback_reason}

Question:
{question}

Please reply to this email or contact the system directly."""

        result = await send_agent_report(
            subject=subject,
            body=body,
            agent_name=agent_name,
        )

        if result.get("status") == "success":
            logger.info(f"Clarification sent via email fallback: {fallback_reason}")
            return {
                "success": True,
                "method": "email",
                "fallback_reason": fallback_reason,
                "email_id": result.get("email_id"),
                "message": "SMS unavailable, clarification request sent via email instead.",
            }
        else:
            logger.error(f"Email fallback also failed: {result.get('error')}")
            return {
                "success": False,
                "method": "email",
                "fallback_reason": fallback_reason,
                "error": f"SMS failed ({fallback_reason}) and email fallback also failed: {result.get('error')}",
            }

    except Exception as e:
        logger.exception("Email fallback failed")
        return {
            "success": False,
            "method": "none",
            "fallback_reason": fallback_reason,
            "error": f"SMS failed ({fallback_reason}) and email fallback also failed: {_sanitize_error_message(e)}",
        }


async def get_sms_clarification_status(
    conversation_id: str,
) -> dict[str, Any]:
    """
    Check the status of a pending SMS clarification request.

    Use this to check if an SMS clarification is still pending or has expired.

    Args:
        conversation_id: The conversation ID to check

    Returns:
        Dictionary containing:
            - has_pending: Boolean indicating if there's a pending request
            - phone_number: The locked phone number (if pending)
            - question: The original question asked (if pending)
            - expires_at: When the lock expires (if pending)
            - message_sid: The Twilio message SID (if pending)
            - status: "pending", "expired", or "none"
    """
    phone_pool = _get_phone_pool()
    if phone_pool is None:
        return {
            "has_pending": False,
            "status": "none",
            "message": "SMS phone pool not configured",
        }

    try:
        await phone_pool.initialize()
        entry = await phone_pool.get_by_conversation_id(conversation_id)

        if entry is None:
            return {
                "has_pending": False,
                "status": "none",
                "message": "No pending SMS clarification for this conversation",
            }

        # Check if expired
        # Note: entry.lock_expires_at is timezone-aware UTC from the database
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        if entry.lock_expires_at and entry.lock_expires_at < now:
            return {
                "has_pending": False,
                "status": "expired",
                "phone_number": entry.phone_number,
                "question": entry.question_text,
                "expired_at": entry.lock_expires_at.isoformat() if entry.lock_expires_at else None,
                "message": "SMS clarification request has expired without a reply",
            }

        return {
            "has_pending": True,
            "status": "pending",
            "phone_number": entry.phone_number,
            "question": entry.question_text,
            "message_sid": entry.message_sid,
            "sent_at": entry.locked_at.isoformat() if entry.locked_at else None,
            "expires_at": entry.lock_expires_at.isoformat() if entry.lock_expires_at else None,
            "message": "Waiting for admin SMS reply",
        }

    except Exception as e:
        logger.exception("Error checking SMS clarification status")
        return {
            "has_pending": False,
            "status": "error",
            "error": _sanitize_error_message(e),
        }


async def get_sms_phone_pool_status() -> dict[str, Any]:
    """
    Get the current status of the SMS phone pool.

    Use this to check pool capacity and availability.

    Returns:
        Dictionary containing:
            - configured: Boolean indicating if pool is configured
            - total_phones: Total number of phones in pool
            - available: Number of available phones
            - locked: Number of locked phones
            - expired_locks: Number of expired locks (will be released)
            - phones: List of phone details
    """
    phone_pool = _get_phone_pool()
    if phone_pool is None:
        return {
            "configured": False,
            "message": "SMS phone pool not configured. Set DATABASE_URL and TWILIO_PHONE_POOL.",
        }

    try:
        await phone_pool.initialize()
        stats = await phone_pool.get_stats()
        phones = await phone_pool.list_all()

        return {
            "configured": True,
            "total_phones": stats["total_phones"],
            "available": stats["available"],
            "locked": stats["locked"],
            "expired_locks": stats["expired_locks"],
            "phones": [
                {
                    "phone_number": p.phone_number,
                    "status": p.status,
                    "locked_to_conversation": p.locked_to_conversation_id,
                    "locked_to_agent": p.locked_to_agent,
                    "expires_at": p.lock_expires_at.isoformat() if p.lock_expires_at else None,
                }
                for p in phones
            ],
        }

    except Exception as e:
        logger.exception("Error getting phone pool status")
        return {
            "configured": True,
            "error": _sanitize_error_message(e),
        }


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "send_sms_clarification",
        "description": (
            "Send an SMS to the admin requesting clarification, with automatic reply routing. "
            "This acquires a phone from the pool, sends the SMS, and tracks the conversation "
            "so when the admin replies, it routes back to this conversation. "
            "If no phone is available, falls back to email. "
            "Requires conversation_id for reply routing. "
            "The admin's reply will be added to the conversation automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "The clarification question to ask the admin. Max 1400 characters. "
                        "Be concise as SMS has length limits."
                    ),
                },
                "conversation_id": {
                    "type": "string",
                    "description": (
                        "The conversation ID to associate with this request. "
                        "Required for routing the admin's reply back to this conversation."
                    ),
                },
                "timeout_minutes": {
                    "type": "integer",
                    "description": (
                        "How long to wait for a reply before releasing the phone. "
                        "Defaults to 30 minutes."
                    ),
                },
            },
            "required": ["question", "conversation_id"],
        },
        "handler": send_sms_clarification,
    },
    {
        "name": "get_sms_clarification_status",
        "description": (
            "Check the status of a pending SMS clarification request for a conversation. "
            "Use this to see if a clarification is still pending or has expired."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "conversation_id": {
                    "type": "string",
                    "description": "The conversation ID to check for pending clarification",
                },
            },
            "required": ["conversation_id"],
        },
        "handler": get_sms_clarification_status,
    },
    {
        "name": "get_sms_phone_pool_status",
        "description": (
            "Get the current status of the SMS phone pool including availability. "
            "Use this to check if phones are available before requesting clarification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": get_sms_phone_pool_status,
    },
]
