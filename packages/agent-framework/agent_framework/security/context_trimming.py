"""Context-aware trimming for conversation history.

This module provides security-aware context trimming that preserves critical
security events (permission denials, SSRF blocks, prompt injection detections)
during conversation trimming. Without this, an attacker could wait for context
trimming to erase evidence of a blocked attack, then retry the same attack
with the agent having no memory of the previous attempt.

Pinned message types:
- Permission denials (tool errors with "Permission denied")
- SSRF blocks (blocked URLs, private IP access attempts)
- Prompt injection detections (Lakera Guard flags, security threat messages)
- System security warnings (security-related assistant responses)
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SecurityClassification(Enum):
    """Classification levels for conversation messages."""

    CRITICAL = "critical"  # Must survive trimming (security events)
    NORMAL = "normal"  # Can be trimmed normally


# Patterns that indicate security-relevant content in tool results
_PERMISSION_DENIAL_PATTERNS = [
    re.compile(r"Permission denied", re.IGNORECASE),
    re.compile(r"cannot execute .+ Required permissions:", re.IGNORECASE),
    re.compile(r"lacks \[.+\]", re.IGNORECASE),
]

_SSRF_PATTERNS = [
    re.compile(r"SSRF", re.IGNORECASE),
    re.compile(r"Blocked (?:hostname|IP|URL)", re.IGNORECASE),
    re.compile(r"private IP", re.IGNORECASE),
    re.compile(r"internal network", re.IGNORECASE),
    re.compile(r"metadata endpoint", re.IGNORECASE),
    re.compile(r"169\.254\.169\.254"),
    re.compile(r"cloud metadata", re.IGNORECASE),
]

_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"[Ss]ecurity threat detected"),
    re.compile(r"[Pp]rompt injection", re.IGNORECASE),
    re.compile(r"flagged by (?:our )?security", re.IGNORECASE),
    re.compile(r"message was blocked for safety", re.IGNORECASE),
    re.compile(r"[Ll]akera.*(?:flagged|detected|blocked)", re.IGNORECASE),
]

_SECURITY_WARNING_PATTERNS = [
    re.compile(r"TOOL_OUTPUT_DATA_BOUNDARY", re.IGNORECASE),
    re.compile(r"Security note:.*Treat as data", re.IGNORECASE),
    re.compile(r"potential (?:prompt )?injection", re.IGNORECASE),
    re.compile(r"suspicious pattern", re.IGNORECASE),
]


@dataclass
class ClassifiedMessage:
    """A message with its security classification and index."""

    index: int
    message: dict[str, Any]
    classification: SecurityClassification
    reasons: list[str] = field(default_factory=list)


def _extract_text_content(message: dict[str, Any]) -> str:
    """Extract searchable text from a message, regardless of format.

    Handles both simple string content and structured content blocks
    (tool_result, text blocks, etc.).

    Args:
        message: An Anthropic API message dict.

    Returns:
        Concatenated text content from the message.
    """
    content = message.get("content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                # tool_result blocks
                if block.get("type") == "tool_result":
                    block_content = block.get("content", "")
                    if isinstance(block_content, str):
                        parts.append(block_content)
                # text blocks
                elif block.get("type") == "text":
                    parts.append(block.get("text", ""))
            # Handle Anthropic SDK objects (TextBlock, etc.)
            elif hasattr(block, "text"):
                parts.append(str(block.text))
            elif hasattr(block, "content"):
                block_content = block.content
                if isinstance(block_content, str):
                    parts.append(block_content)
        return "\n".join(parts)

    return str(content)


def _is_error_tool_result(message: dict[str, Any]) -> bool:
    """Check if a message contains any tool_result with is_error=True.

    Args:
        message: An Anthropic API message dict.

    Returns:
        True if message contains error tool results.
    """
    content = message.get("content", [])
    if not isinstance(content, list):
        return False

    return any(
        isinstance(block, dict)
        and block.get("type") == "tool_result"
        and block.get("is_error") is True
        for block in content
    )


def classify_message(message: dict[str, Any]) -> ClassifiedMessage:
    """Classify a single message for its security relevance.

    Examines message content against known security patterns to determine
    if it should be pinned (survive trimming) or can be safely removed.

    Args:
        message: An Anthropic API message dict.

    Returns:
        ClassifiedMessage with the security classification and reasons.
    """
    reasons: list[str] = []
    text = _extract_text_content(message)
    is_error = _is_error_tool_result(message)

    # Check permission denial patterns (especially in error tool results)
    for pattern in _PERMISSION_DENIAL_PATTERNS:
        if pattern.search(text):
            reasons.append(f"permission_denial: {pattern.pattern}")
            break

    # Check SSRF patterns
    for pattern in _SSRF_PATTERNS:
        if pattern.search(text):
            reasons.append(f"ssrf_block: {pattern.pattern}")
            break

    # Check prompt injection patterns
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            reasons.append(f"prompt_injection: {pattern.pattern}")
            break

    # Check general security warning patterns
    for pattern in _SECURITY_WARNING_PATTERNS:
        if pattern.search(text):
            reasons.append(f"security_warning: {pattern.pattern}")
            break

    # An error tool result with security-related content is always critical
    if is_error and reasons:
        return ClassifiedMessage(
            index=0,
            message=message,
            classification=SecurityClassification.CRITICAL,
            reasons=reasons,
        )

    # Non-error messages with security patterns are also critical
    # (e.g., assistant explaining why something was blocked)
    if reasons:
        return ClassifiedMessage(
            index=0,
            message=message,
            classification=SecurityClassification.CRITICAL,
            reasons=reasons,
        )

    return ClassifiedMessage(
        index=0,
        message=message,
        classification=SecurityClassification.NORMAL,
        reasons=[],
    )


def _build_security_summary(pinned_messages: list[ClassifiedMessage]) -> str:
    """Build a compact summary of pinned security events.

    When there are too many pinned messages to keep, this creates a summary
    that preserves the essential security context.

    Args:
        pinned_messages: List of classified messages marked as CRITICAL.

    Returns:
        A summary string of security events.
    """
    events: list[str] = []
    for cm in pinned_messages:
        text = _extract_text_content(cm.message)
        # Truncate long messages but preserve key info
        summary = text[:200] + "..." if len(text) > 200 else text
        reason_tags = ", ".join(cm.reasons)
        events.append(f"[{reason_tags}] {summary}")

    return (
        "[SECURITY CONTEXT - Previous security events in this session]\n"
        + "\n".join(f"• {e}" for e in events)
        + "\n[END SECURITY CONTEXT]"
    )


def trim_with_security_awareness(
    messages: list[dict[str, Any]],
    max_messages: int,
    max_pinned_pairs: int = 6,
) -> tuple[list[dict[str, Any]], int, int]:
    """Trim conversation messages while preserving security-critical content.

    This is the main entry point for context-aware trimming. It:
    1. Classifies all messages by security relevance
    2. Identifies "pinned pairs" (user+assistant or assistant+user pairs
       around security events)
    3. Removes oldest non-pinned messages first
    4. If still over limit, compresses oldest pinned messages into a summary

    The result always maintains valid message ordering (user/assistant alternation
    is preserved, tool_result messages follow their corresponding tool_use).

    Args:
        messages: Current conversation messages list.
        max_messages: Target maximum number of messages to keep.
        max_pinned_pairs: Maximum number of security message pairs to pin
            before summarizing the oldest. Default: 6 (12 messages).

    Returns:
        Tuple of (trimmed_messages, num_removed, num_pinned) where:
        - trimmed_messages: The new message list
        - num_removed: Number of messages removed
        - num_pinned: Number of messages that were pinned (survived trimming)
    """
    if len(messages) <= max_messages:
        return messages, 0, 0

    # Phase 1: Classify all messages
    classified: list[ClassifiedMessage] = []
    for i, msg in enumerate(messages):
        cm = classify_message(msg)
        cm.index = i
        classified.append(cm)

    # Phase 2: Expand pinned messages to include their conversation pair.
    # A security event in a tool_result (user role) also pins the preceding
    # assistant message (which contains the tool_use), and vice versa.
    pinned_indices: set[int] = set()
    for cm in classified:
        if cm.classification == SecurityClassification.CRITICAL:
            pinned_indices.add(cm.index)
            # Pin the adjacent message to maintain conversation coherence
            if cm.message.get("role") == "user" and cm.index > 0:
                pinned_indices.add(cm.index - 1)  # preceding assistant
            elif cm.message.get("role") == "assistant" and cm.index + 1 < len(messages):
                pinned_indices.add(cm.index + 1)  # following user/tool_result

    # Phase 3: Separate pinned and trimmable messages
    pinned: list[ClassifiedMessage] = []
    trimmable_indices: list[int] = []

    for cm in classified:
        if cm.index in pinned_indices:
            pinned.append(cm)
        else:
            trimmable_indices.append(cm.index)

    # Phase 4: Calculate how many messages to remove
    messages_to_remove = len(messages) - max_messages

    # Remove from oldest trimmable messages first
    indices_to_remove: set[int] = set()
    for idx in trimmable_indices:
        if len(indices_to_remove) >= messages_to_remove:
            break
        indices_to_remove.add(idx)

    # Phase 5: If we still need to remove more and have excess pinned messages,
    # summarize the oldest pinned pairs into a compact security context message
    security_summary_msg: dict[str, Any] | None = None
    pinned_to_summarize: list[ClassifiedMessage] = []

    if len(indices_to_remove) < messages_to_remove and len(pinned) > max_pinned_pairs * 2:
        # Sort pinned by index (oldest first)
        pinned_sorted = sorted(pinned, key=lambda cm: cm.index)
        # Keep the newest max_pinned_pairs*2, summarize the rest
        pinned_to_summarize = pinned_sorted[: len(pinned_sorted) - max_pinned_pairs * 2]

        for cm in pinned_to_summarize:
            indices_to_remove.add(cm.index)

        # Build a summary message from the summarized pinned messages
        # Only include the ones that were originally classified as CRITICAL
        critical_summarized = [
            cm for cm in pinned_to_summarize
            if cm.classification == SecurityClassification.CRITICAL
        ]
        if critical_summarized:
            summary_text = _build_security_summary(critical_summarized)
            security_summary_msg = {
                "role": "user",
                "content": (
                    f"[SYSTEM CONTEXT]\n{summary_text}\n[END SYSTEM CONTEXT]\n\n"
                    "Please acknowledge you've noted these prior security events."
                ),
            }

    # Phase 6: Build the trimmed message list
    trimmed: list[dict[str, Any]] = []

    # Insert security summary at the start if we had to compress pinned messages
    if security_summary_msg is not None:
        trimmed.append(security_summary_msg)
        trimmed.append(
            {
                "role": "assistant",
                "content": (
                    "Understood. I've noted the previous security events from this session. "
                    "I will continue to enforce the same security policies."
                ),
            }
        )

    # Add remaining messages in order
    for i, msg in enumerate(messages):
        if i not in indices_to_remove:
            trimmed.append(msg)

    num_removed = len(messages) - len(trimmed)
    num_pinned = len(pinned_indices) - len(pinned_to_summarize)

    logger.info(
        f"Context-aware trim: removed {num_removed} messages, "
        f"pinned {num_pinned} security-relevant messages, "
        f"summarized {len(pinned_to_summarize)} old pinned messages"
    )

    return trimmed, num_removed, num_pinned
