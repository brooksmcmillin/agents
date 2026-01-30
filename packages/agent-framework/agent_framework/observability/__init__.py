"""Observability module for agent tracing and monitoring.

This module provides integration with Langfuse for comprehensive observability
of agent actions including:
- LLM calls (automatic via OpenTelemetry instrumentation)
- Tool executions
- Conversation traces
- Token usage and latency metrics
"""

from .langfuse_integration import (
    get_langfuse,
    init_observability,
    observe_tool_call,
    shutdown_observability,
    start_trace,
)

__all__ = [
    "init_observability",
    "shutdown_observability",
    "get_langfuse",
    "start_trace",
    "observe_tool_call",
]
