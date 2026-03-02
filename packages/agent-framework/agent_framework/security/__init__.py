"""Security module for agent framework.

This module provides security checks and guardrails for LLM interactions,
including prompt injection detection via Lakera Guard, SSRF protection,
secure LLM-to-LLM output handling, context-aware trimming, and
cryptographic capability-token authorization via Tenuo.
"""

from .capabilities import (
    TenuoToolGuard,
    attenuate_for_worker,
    capabilities_from_permissions,
    check_tool_authorized,
    configure_tenuo,
    is_tenuo_configured,
    mint_agent_warrant,
    mint_agent_warrant_sync,
)
from .context_trimming import (
    PINNED_EVENT_KEY,
    SECURITY_EVENT_KEY,
    ClassifiedMessage,
    SecurityClassification,
    classify_message,
    trim_with_security_awareness,
)
from .lakera_guard import LakeraGuard, LakeraSecurityResult, SecurityCheckError
from .llm_output_sanitizer import (
    InputValidationResult,
    LLMOutputSanitizer,
    SanitizationAction,
    SanitizationResult,
    sanitize_llm_to_llm_output,
)
from .pii import mask_phone_in_text, mask_phone_number
from .ssrf import SSRFTransport, SSRFValidator

__all__ = [
    # Capability-token authorization (Tenuo)
    "TenuoToolGuard",
    "attenuate_for_worker",
    "capabilities_from_permissions",
    "check_tool_authorized",
    "configure_tenuo",
    "is_tenuo_configured",
    "mint_agent_warrant",
    "mint_agent_warrant_sync",
    # Context trimming
    "PINNED_EVENT_KEY",
    "SECURITY_EVENT_KEY",
    "ClassifiedMessage",
    "InputValidationResult",
    # Lakera Guard
    "LakeraGuard",
    "LakeraSecurityResult",
    "LLMOutputSanitizer",
    # PII
    "mask_phone_in_text",
    "mask_phone_number",
    # LLM output sanitization
    "SanitizationAction",
    "SanitizationResult",
    "SecurityCheckError",
    "SecurityClassification",
    "classify_message",
    "sanitize_llm_to_llm_output",
    # SSRF
    "SSRFTransport",
    "SSRFValidator",
    "trim_with_security_awareness",
]
