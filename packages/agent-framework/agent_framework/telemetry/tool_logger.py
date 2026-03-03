"""JSONL logger for MCP tool invocations.

Records tool name, timing, success/failure, and parameter names (no values)
to enable usage-rate analysis. Writes one JSON line per invocation to a
rotating log file.
"""

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_tool_logger: logging.Logger | None = None


_ALLOWED_LOG_DIRS = ("/var/log/", ".data/")


def configure_tool_logger(log_path: str) -> None:
    """Set up the tool invocation logger with a rotating file handler.

    Args:
        log_path: Path to the JSONL log file (parent dirs created automatically).
              Must resolve to within one of the allowed base directories.
    """
    global _tool_logger

    resolved = Path(log_path).resolve()
    if not any(
        str(resolved).startswith(str(Path(d).resolve()) + os.sep) for d in _ALLOWED_LOG_DIRS
    ):
        raise ValueError(f"Tool log path must be within {_ALLOWED_LOG_DIRS}, got: {resolved}")

    resolved.parent.mkdir(parents=True, exist_ok=True)

    _tool_logger = logging.getLogger("mcp.tool_invocations")
    _tool_logger.setLevel(logging.INFO)
    _tool_logger.propagate = False

    # Avoid duplicate handlers on repeated calls
    _tool_logger.handlers.clear()

    handler = RotatingFileHandler(
        log_path,
        maxBytes=50 * 1024 * 1024,  # 50 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _tool_logger.addHandler(handler)


def log_tool_invocation(
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    duration_ms: float,
    error: BaseException | None = None,
) -> None:
    """Write a single JSONL record for a tool invocation.

    Args:
        tool_name: Name of the invoked tool.
        arguments: Tool arguments (only keys are logged, not values).
        result: Return value from the handler (used to detect error responses).
        duration_ms: Wall-clock duration in milliseconds.
        error: Exception if the call raised, None otherwise.
    """
    if _tool_logger is None:
        return

    success = error is None
    error_type: str | None = None

    if error is not None:
        error_type = type(error).__name__
    elif isinstance(result, dict) and "error" in result:
        success = False
        error_type = "tool_error_response"

    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "tool_name": tool_name,
        "duration_ms": round(duration_ms, 2),
        "success": success,
        "error_type": error_type,
        "param_names": sorted(arguments.keys()) if arguments else [],
    }

    _tool_logger.info(json.dumps(record, separators=(",", ":")))
