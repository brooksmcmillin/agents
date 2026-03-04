"""Telemetry module for MCP tool invocation and agent decision logging."""

from .decision_logger import (
    DECISION_TYPE_AUTONOMY_TIER,
    DECISION_TYPE_DECOMPOSITION,
    DECISION_TYPE_ERROR_HANDLING,
    DECISION_TYPE_ROUTING,
    DECISION_TYPE_TOOL_SELECTION,
    configure_decision_logger,
    get_decision_logger,
    log_decision,
    reset_decision_logger,
)
from .tool_logger import configure_tool_logger, log_tool_invocation

__all__ = [
    # Tool invocation logger
    "configure_tool_logger",
    "log_tool_invocation",
    # Decision logger
    "configure_decision_logger",
    "get_decision_logger",
    "log_decision",
    "reset_decision_logger",
    "DECISION_TYPE_TOOL_SELECTION",
    "DECISION_TYPE_ROUTING",
    "DECISION_TYPE_DECOMPOSITION",
    "DECISION_TYPE_AUTONOMY_TIER",
    "DECISION_TYPE_ERROR_HANDLING",
]
