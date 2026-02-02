"""Logging utilities for Grafana Loki integration.

This module provides structured JSON logging for log aggregation with Grafana Loki,
while maintaining backward compatibility with text-based logging.

Key components:
- AgentJsonFormatter: JSON formatter compatible with Loki/Promtail
- correlation_id_var: ContextVar for request tracing across async calls
- set_correlation_id() / get_correlation_id(): Helpers for correlation ID management
"""

import contextvars
import json
import logging
from datetime import UTC, datetime
from typing import Any

# ContextVar for correlation ID - enables request tracing across async calls
correlation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def set_correlation_id(correlation_id: str) -> contextvars.Token[str | None]:
    """Set the correlation ID for the current context.

    Args:
        correlation_id: Unique identifier for tracing related log entries

    Returns:
        Token that can be used to reset the correlation ID
    """
    return correlation_id_var.set(correlation_id)


def get_correlation_id() -> str | None:
    """Get the current correlation ID.

    Returns:
        Current correlation ID or None if not set
    """
    return correlation_id_var.get()


def reset_correlation_id(token: contextvars.Token[str | None]) -> None:
    """Reset the correlation ID to its previous value.

    Args:
        token: Token returned from set_correlation_id()
    """
    correlation_id_var.reset(token)


class AgentJsonFormatter(logging.Formatter):
    """JSON formatter for Loki-compatible structured logging.

    Produces log entries in the following format:
    {
        "timestamp": "2026-02-01T10:30:00.000Z",
        "level": "INFO",
        "logger": "agent_framework",
        "message": "Tool execution completed",
        "agent_name": "chatbot",
        "correlation_id": "abc-123",
        "conversation_id": "conv-456",
        "tool_name": "fetch_web_content",
        "module": "agent",
        "function": "process_message",
        "line": 450
    }
    """

    def __init__(
        self,
        agent_name: str | None = None,
        include_extra: bool = True,
        datefmt: str | None = None,
    ):
        """Initialize the JSON formatter.

        Args:
            agent_name: Default agent name to include in all log entries
            include_extra: Whether to include extra fields from LogRecord
            datefmt: Date format (unused, timestamps are always ISO 8601)
        """
        super().__init__(datefmt=datefmt)
        self.agent_name = agent_name
        self.include_extra = include_extra

        # Standard LogRecord attributes to exclude from extra fields
        self._standard_attrs = frozenset(
            {
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "threadName",
                "taskName",
                "message",
            }
        )

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-encoded log entry
        """
        # Build the base log entry
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add agent name if configured
        if self.agent_name:
            log_entry["agent_name"] = self.agent_name

        # Add correlation ID if set
        correlation_id = get_correlation_id()
        if correlation_id:
            log_entry["correlation_id"] = correlation_id

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add stack info if present
        if record.stack_info:
            log_entry["stack_info"] = record.stack_info

        # Include extra fields from the record
        if self.include_extra:
            for key, value in record.__dict__.items():
                if key not in self._standard_attrs and not key.startswith("_"):
                    # Handle non-serializable values
                    try:
                        json.dumps(value)
                        log_entry[key] = value
                    except (TypeError, ValueError):
                        log_entry[key] = str(value)

        return json.dumps(log_entry, default=str)


class ContextualLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that automatically includes context in log entries.

    Usage:
        logger = ContextualLoggerAdapter(
            logging.getLogger(__name__),
            {"agent_name": "chatbot"}
        )
        logger.info("Processing message", extra={"tool_name": "web_search"})
    """

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Add context to log entries.

        Args:
            msg: Log message
            kwargs: Keyword arguments including extra dict

        Returns:
            Processed message and kwargs with context added
        """
        extra = kwargs.get("extra", {})
        extra.update(self.extra)

        # Add correlation ID if available
        correlation_id = get_correlation_id()
        if correlation_id and "correlation_id" not in extra:
            extra["correlation_id"] = correlation_id

        kwargs["extra"] = extra
        return msg, kwargs


def create_json_handler(
    log_file: str,
    agent_name: str | None = None,
    level: int = logging.DEBUG,
) -> logging.FileHandler:
    """Create a file handler with JSON formatting for Loki.

    Args:
        log_file: Path to the log file
        agent_name: Agent name to include in log entries
        level: Minimum log level

    Returns:
        Configured FileHandler with JSON formatting
    """
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(AgentJsonFormatter(agent_name=agent_name))
    return handler


__all__ = [
    "AgentJsonFormatter",
    "ContextualLoggerAdapter",
    "correlation_id_var",
    "set_correlation_id",
    "get_correlation_id",
    "reset_correlation_id",
    "create_json_handler",
]
