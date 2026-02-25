"""Security module for agent framework.

This module provides security checks and guardrails for LLM interactions,
including prompt injection detection via Lakera Guard, SSRF protection,
secure LLM-to-LLM output handling, and context-aware trimming.
"""

from .context_trimming import (
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
from .ssrf import SSRFValidator

__all__ = [
    "ClassifiedMessage",
    "InputValidationResult",
    "LakeraGuard",
    "LakeraSecurityResult",
    "LLMOutputSanitizer",
    "mask_phone_in_text",
    "mask_phone_number",
    "SanitizationAction",
    "SanitizationResult",
    "SecurityCheckError",
    "SecurityClassification",
    "classify_message",
    "sanitize_llm_to_llm_output",
    "SSRFValidator",
    "trim_with_security_awareness",
]
