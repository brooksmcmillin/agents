"""Logging utilities for Grafana Loki integration.

This module provides structured JSON logging for log aggregation with Grafana Loki,
while maintaining backward compatibility with text-based logging.

Key components:
- AgentJsonFormatter: JSON formatter compatible with Loki/Promtail
- correlation_id_var: ContextVar for request tracing across async calls
- set_correlation_id() / get_correlation_id(): Helpers for correlation ID management
- setup_logging(): Full logging setup with file/console handlers, JSON format, Loki support
- _StderrToLogFile: Redirects stderr to log file while keeping console clean
"""

import contextlib
import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

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


class _StderrToLogFile:
    """Wrapper that redirects stderr to a log file only (not console).

    This captures stderr output (from subprocesses, exceptions, etc.) and
    writes it only to the log file, keeping the console clean. The original
    stderr is preserved for fileno() and isatty() compatibility but writes
    are not echoed to it.
    """

    def __init__(self, log_file_path: Path, original_stderr: TextIO | None) -> None:
        self.log_file_path = log_file_path
        self.original_stderr = original_stderr
        self._log_file = None

    def _ensure_file_open(self) -> None:
        """Open log file lazily."""
        if self._log_file is None:
            with contextlib.suppress(OSError):
                self._log_file = open(  # noqa: SIM115
                    self.log_file_path, "a", encoding="utf-8"
                )

    def write(self, data: str) -> None:
        """Write to log file only (not echoed to console)."""
        # Write only to log file - do NOT echo to console
        self._ensure_file_open()
        if self._log_file:
            with contextlib.suppress(OSError):
                self._log_file.write(data)
                self._log_file.flush()

    def flush(self) -> None:
        """Flush the log file stream."""
        if self._log_file:
            with contextlib.suppress(OSError):
                self._log_file.flush()

    def fileno(self) -> int:
        """Return file descriptor of original stderr."""
        if self.original_stderr:
            return self.original_stderr.fileno()
        raise OSError("No stderr available")

    def isatty(self) -> bool:
        """Check if original stderr is a tty."""
        if self.original_stderr:
            return self.original_stderr.isatty()
        return False

    @property
    def closed(self) -> bool:
        """Return True if the log file has been closed."""
        return self._log_file is None

    def close(self) -> None:
        """Close the log file (but not original stderr)."""
        if self._log_file:
            with contextlib.suppress(OSError):
                self._log_file.close()
            self._log_file = None


# Global reference to stderr wrapper for cleanup
_stderr_wrapper: _StderrToLogFile | None = None


def setup_logging(
    agent_name: str,
    console_level: int = logging.WARNING,
    file_level: int = logging.DEBUG,
    redirect_stderr: bool = True,
    json_format: bool | None = None,
) -> logging.Logger:
    """Set up logging with both file and console handlers.

    Args:
        agent_name: Name of the agent (used for log file name)
        console_level: Log level for console output (default: WARNING)
        file_level: Log level for file output (default: DEBUG)
        redirect_stderr: If True, redirect sys.stderr to also write to log file (default: True)
        json_format: If True, use JSON format for file logging (Loki-compatible).
            If None, auto-detect from LOKI_ENABLED or LOG_FORMAT environment variables.
            Console output always uses text format for readability.

    Returns:
        Configured logger instance
    """
    global _stderr_wrapper

    # Import settings here to avoid circular imports at module load time
    from ..core.config import settings

    # Auto-detect JSON format from settings if not explicitly specified
    if json_format is None:
        json_format = settings.loki_enabled or settings.log_format.lower() == "json"

    # Get log file path using settings helper
    log_file = settings.get_log_file(agent_name)

    # Get the root logger for agent_framework
    agent_logger = logging.getLogger("agent_framework")
    agent_logger.setLevel(logging.DEBUG)  # Capture all levels
    agent_logger.propagate = False  # Don't propagate to root logger (prevents duplicate output)

    # Remove existing handlers to avoid duplicates on reload (close first to avoid FD leaks)
    for handler in agent_logger.handlers[:]:
        handler.close()
    agent_logger.handlers.clear()

    # File handler - captures all debug info
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)

    if json_format:
        # Use JSON formatter for Loki compatibility
        file_handler.setFormatter(AgentJsonFormatter(agent_name=agent_name))
    else:
        # Use standard text formatter for human readability
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
    agent_logger.addHandler(file_handler)

    # Console handler - always text format for human readability
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    agent_logger.addHandler(console_handler)

    # Also configure httpx and mcp loggers to file only
    for lib_logger_name in ["httpx", "mcp", "mcp_server"]:
        lib_logger = logging.getLogger(lib_logger_name)
        lib_logger.setLevel(logging.DEBUG)
        lib_logger.handlers.clear()
        lib_logger.addHandler(file_handler)
        lib_logger.propagate = False

    # Redirect sys.stderr to also write to log file (only wrap if not already wrapped)
    if redirect_stderr and not isinstance(sys.stderr, _StderrToLogFile):
        _stderr_wrapper = _StderrToLogFile(log_file, sys.stderr)
        sys.stderr = _stderr_wrapper  # type: ignore[assignment]
        agent_logger.debug("sys.stderr redirected to log file")

    log_format_type = "JSON" if json_format else "text"
    agent_logger.info(f"Logging initialized ({log_format_type} format). Log file: {log_file}")

    return agent_logger


__all__ = [
    "AgentJsonFormatter",
    "ContextualLoggerAdapter",
    "correlation_id_var",
    "set_correlation_id",
    "get_correlation_id",
    "reset_correlation_id",
    "create_json_handler",
    "setup_logging",
]
