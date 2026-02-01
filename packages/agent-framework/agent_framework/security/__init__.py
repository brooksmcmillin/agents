"""Security module for agent framework.

This module provides security checks and guardrails for LLM interactions,
including prompt injection detection via Lakera Guard, SSRF protection,
and secure LLM-to-LLM output handling.
"""

from .lakera_guard import LakeraGuard, LakeraSecurityResult, SecurityCheckError
from .llm_output_sanitizer import (
    InputValidationResult,
    LLMOutputSanitizer,
    SanitizationAction,
    SanitizationResult,
    sanitize_llm_to_llm_output,
)
from .ssrf import SSRFValidator

__all__ = [
    "InputValidationResult",
    "LakeraGuard",
    "LakeraSecurityResult",
    "LLMOutputSanitizer",
    "SanitizationAction",
    "SanitizationResult",
    "SecurityCheckError",
    "sanitize_llm_to_llm_output",
    "SSRFValidator",
]
