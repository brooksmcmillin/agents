"""JSONL logger for agent decision events.

Records structured decision events at key agent decision points
(tool selection, routing, decomposition, autonomy tier assignment,
error handling) to enable decision observability.

Each record contains:
    {
        "id":            UUID string,
        "timestamp":     ISO 8601 UTC,
        "agent":         agent name string,
        "decision_type": one of the DECISION_TYPE_* constants,
        "inputs":        dict summarising the inputs to the decision,
        "output":        dict summarising the decision outcome,
        "reasoning":     optional free-text explanation,
        "session_id":    optional session identifier,
    }
"""

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .constants import ALLOWED_LOG_DIRS

# ─── Decision type constants ────────────────────────────────────────────────

DECISION_TYPE_TOOL_SELECTION = "tool_selection"
DECISION_TYPE_ROUTING = "routing"
DECISION_TYPE_DECOMPOSITION = "decomposition"
DECISION_TYPE_AUTONOMY_TIER = "autonomy_tier"
DECISION_TYPE_ERROR_HANDLING = "error_handling"

_VALID_DECISION_TYPES = frozenset(
    {
        DECISION_TYPE_TOOL_SELECTION,
        DECISION_TYPE_ROUTING,
        DECISION_TYPE_DECOMPOSITION,
        DECISION_TYPE_AUTONOMY_TIER,
        DECISION_TYPE_ERROR_HANDLING,
    }
)

# ─── Module-level logger state ───────────────────────────────────────────────

_decision_logger: logging.Logger | None = None


# ─── Configuration ───────────────────────────────────────────────────────────


def configure_decision_logger(log_path: str) -> None:
    """Set up the decision event logger with a rotating file handler.

    Args:
        log_path: Path to the JSONL log file (parent dirs created
            automatically). Must resolve to within one of the allowed
            base directories.

    Raises:
        ValueError: If *log_path* resolves outside the allowed directories.
    """
    global _decision_logger

    resolved = Path(log_path).resolve()
    if not any(str(resolved).startswith(str(Path(d).resolve()) + os.sep) for d in ALLOWED_LOG_DIRS):
        raise ValueError(f"Decision log path must be within {ALLOWED_LOG_DIRS}, got: {resolved}")

    resolved.parent.mkdir(parents=True, exist_ok=True)

    _decision_logger = logging.getLogger("agent.decision_events")
    _decision_logger.setLevel(logging.INFO)
    _decision_logger.propagate = False

    # Close and remove existing handlers to avoid duplicates and resource leaks
    for h in _decision_logger.handlers[:]:
        h.close()
    _decision_logger.handlers.clear()

    handler = RotatingFileHandler(
        log_path,
        maxBytes=50 * 1024 * 1024,  # 50 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _decision_logger.addHandler(handler)


def get_decision_logger() -> logging.Logger | None:
    """Return the current decision logger, or None if not configured."""
    return _decision_logger


def reset_decision_logger() -> None:
    """Reset the decision logger to unconfigured state (useful for tests)."""
    global _decision_logger
    if _decision_logger is not None:
        for h in _decision_logger.handlers[:]:
            h.close()
        _decision_logger.handlers.clear()
    _decision_logger = None


# ─── Core logging function ───────────────────────────────────────────────────


def log_decision(
    *,
    agent: str,
    decision_type: str,
    inputs: dict[str, Any],
    output: dict[str, Any],
    reasoning: str | None = None,
    session_id: str | None = None,
) -> None:
    """Write a single JSONL record for an agent decision event.

    If the logger has not been configured via :func:`configure_decision_logger`,
    this function is a no-op so callers never need to guard against an
    unconfigured logger.

    Args:
        agent: Name of the agent making the decision.
        decision_type: One of the ``DECISION_TYPE_*`` constants.
        inputs: Dict summarising the inputs to the decision (e.g. available
            tools, user message summary). Values are logged as-is; callers
            are responsible for omitting sensitive data.
        output: Dict summarising the decision outcome (e.g. selected tool
            name, chosen route, subtask count).
        reasoning: Optional free-text explanation of why this decision was
            made (e.g. the exception type name for error-handling decisions,
            or a description synthesised from the response). Must not
            contain sensitive information such as exception messages, API
            keys, or connection strings.
        session_id: Optional session/conversation identifier for correlating
            decisions within a single turn.

    Raises:
        ValueError: If *decision_type* is not one of the recognised constants.
            This is always raised, even when the logger is unconfigured, so
            typos are caught early in development.
    """
    # Validate decision_type before the early return so callers with typos
    # get an immediate ValueError in development (unconfigured logger) rather
    # than a silent no-op that only surfaces in production.
    if decision_type not in _VALID_DECISION_TYPES:
        raise ValueError(
            f"Unknown decision_type {decision_type!r}. "
            f"Must be one of: {sorted(_VALID_DECISION_TYPES)}"
        )

    if _decision_logger is None:
        return

    record: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "agent": agent,
        "decision_type": decision_type,
        "inputs": inputs,
        "output": output,
    }
    if reasoning is not None:
        record["reasoning"] = reasoning
    if session_id is not None:
        record["session_id"] = session_id

    _decision_logger.info(json.dumps(record, separators=(",", ":")))
