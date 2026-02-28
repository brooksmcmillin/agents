"""Log Analysis agent with automatic message pinning.

This agent reads and analyzes log files, automatically pinning tool results
that contain critical findings (errors, exceptions, stack traces, security
events, etc.) so they survive context trimming during long investigations.
"""

import logging
import re
from typing import Any

from anthropic.types import ToolUseBlock

from agent_framework import Agent
from agent_framework.security.context_trimming import PINNED_EVENT_KEY

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

logger = logging.getLogger(__name__)

# Tools this agent is allowed to use
_ALLOWED_TOOLS = [
    # Filesystem (read-only) for log file access
    "read_file",
    "list_directory",
    "glob_files",
    "grep_files",
    # Web research for error code lookups
    "fetch_web_content",
    # Memory for cross-session continuity
    "get_memories",
    "save_memory",
    "search_memories",
    # Communication
    "send_slack_message",
]

# Log-reading tools whose results should be scanned for pin-worthy content.
_LOG_TOOLS = frozenset({"read_file", "grep_files"})

# Patterns that indicate a tool result contains critical log findings.
# When any of these match, the tool result is pinned so it survives trimming.
_CRITICAL_PATTERNS = [
    # Error levels
    re.compile(r"\bERROR\b"),
    re.compile(r"\bFATAL\b"),
    re.compile(r"\bCRITICAL\b"),
    re.compile(r"\bSEVERE\b"),
    re.compile(r"\bEMERG(?:ENCY)?\b"),
    re.compile(r"\bALERT\b"),
    # Exceptions and stack traces
    re.compile(r"\bException\b"),
    re.compile(r"\bTraceback\b"),
    re.compile(r"\bpanic:\b"),
    re.compile(r"\bSegmentation fault\b", re.IGNORECASE),
    re.compile(r"\bstack trace\b", re.IGNORECASE),
    re.compile(r"at \S+\.\S+\(.*:\d+\)"),  # Java-style stack frame
    re.compile(r'File ".*", line \d+'),  # Python stack frame
    # Resource exhaustion
    re.compile(r"\bOOM\b|Out ?of ?[Mm]emory", re.IGNORECASE),
    re.compile(r"\bOOM[-_]?[Kk]ill", re.IGNORECASE),
    re.compile(r"No space left on device", re.IGNORECASE),
    re.compile(r"Too many open files", re.IGNORECASE),
    re.compile(r"Cannot allocate memory", re.IGNORECASE),
    # Timeouts and connectivity
    re.compile(r"\btimeout\b", re.IGNORECASE),
    re.compile(r"\bconnection refused\b", re.IGNORECASE),
    re.compile(r"\bconnection reset\b", re.IGNORECASE),
    re.compile(r"\bECONNREFUSED\b"),
    re.compile(r"\bETIMEDOUT\b"),
    # HTTP errors
    re.compile(r"\b5\d{2}\b.*(?:error|fail|status)", re.IGNORECASE),
    re.compile(r"HTTP[/ ]+\d\.\d[\"' ]+5\d{2}"),
    # Security events
    re.compile(r"\bUnauthorized\b"),
    re.compile(r"\bForbidden\b"),
    re.compile(r"authentication fail", re.IGNORECASE),
    re.compile(r"permission denied", re.IGNORECASE),
    re.compile(r"invalid token", re.IGNORECASE),
    re.compile(r"brute.?force", re.IGNORECASE),
    # Process/service crashes
    re.compile(r"\bkilled\b", re.IGNORECASE),
    re.compile(r"\bcore dump", re.IGNORECASE),
    re.compile(r"(?:service|process|worker) (?:crash|died|exited)", re.IGNORECASE),
]

# Minimum content length to scan — very short results are unlikely to contain
# meaningful log data worth pinning.
_MIN_CONTENT_LENGTH = 50


def _classify_log_content(content: str) -> str | None:
    """Determine if tool result content contains pin-worthy log data.

    Scans the content against critical patterns and returns a short reason
    string if the content should be pinned, or None if it's unremarkable.

    Args:
        content: The tool result text to scan.

    Returns:
        A reason string (e.g. "critical_error_pattern") or None.
    """
    if len(content) < _MIN_CONTENT_LENGTH:
        return None

    matched_categories: list[str] = []

    for pattern in _CRITICAL_PATTERNS:
        if pattern.search(content):
            # Map pattern to a human-readable category
            pat_str = pattern.pattern.lower()
            if any(k in pat_str for k in ("error", "fatal", "critical", "severe", "emerg", "alert")):
                if "error_level" not in matched_categories:
                    matched_categories.append("error_level")
            elif any(k in pat_str for k in ("exception", "traceback", "panic", "stack")):
                if "exception" not in matched_categories:
                    matched_categories.append("exception")
            elif any(k in pat_str for k in ("oom", "memory", "space", "open files", "allocat")):
                if "resource_exhaustion" not in matched_categories:
                    matched_categories.append("resource_exhaustion")
            elif any(k in pat_str for k in ("timeout", "connection", "econnrefused", "etimedout")):
                if "connectivity" not in matched_categories:
                    matched_categories.append("connectivity")
            elif any(k in pat_str for k in ("5\\d", "http")):
                if "http_error" not in matched_categories:
                    matched_categories.append("http_error")
            elif any(
                k in pat_str
                for k in ("unauthorized", "forbidden", "authentication", "permission", "token", "brute")
            ):
                if "security_event" not in matched_categories:
                    matched_categories.append("security_event")
            elif any(k in pat_str for k in ("killed", "core dump", "crash", "died", "exited")):
                if "process_crash" not in matched_categories:
                    matched_categories.append("process_crash")

            # Stop early once we have enough evidence
            if len(matched_categories) >= 3:
                break

    if not matched_categories:
        return None

    return ",".join(matched_categories)


class LogAnalysisAgent(Agent):
    """Log analysis agent with automatic message pinning.

    Extends the base Agent to automatically scan tool results from log-reading
    tools (read_file, grep_files) for critical patterns.  When critical content
    is detected, the tool result is tagged with ``_pinned`` metadata so it
    survives context trimming during long investigation sessions.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("allowed_tools", _ALLOWED_TOOLS)
        kwargs.setdefault("mcp_server_path", "mcp_server/server.py")
        super().__init__(**kwargs)

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def get_greeting(self) -> str:
        return USER_GREETING_PROMPT

    def get_agent_name(self) -> str:
        return "LogAnalysisAgent"

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolUseBlock],
        trace_ctx: Any,
        on_tool_start: Any = None,
    ) -> list[dict[str, Any]]:
        """Execute tool calls, auto-pinning results with critical log content.

        Delegates to the parent implementation, then scans results from
        log-reading tools for critical patterns.  Matching results are tagged
        with ``_pinned`` metadata so the context trimmer preserves them.
        """
        results = await super()._execute_tool_calls(tool_calls, trace_ctx, on_tool_start)

        # Build a lookup from tool_use_id → tool_name for the current batch
        tool_name_by_id: dict[str, str] = {tc.id: tc.name for tc in tool_calls}

        for result in results:
            tool_use_id = result.get("tool_use_id", "")
            tool_name = tool_name_by_id.get(tool_use_id, "")

            # Only scan log-reading tools
            if tool_name not in _LOG_TOOLS:
                continue

            # Skip error results (already handled by security pinning)
            if result.get("is_error"):
                continue

            content = result.get("content", "")
            if not isinstance(content, str):
                continue

            pin_reason = _classify_log_content(content)
            if pin_reason:
                result[PINNED_EVENT_KEY] = pin_reason
                logger.info(
                    f"Pinned tool result from {tool_name} "
                    f"(reason: {pin_reason}, length: {len(content)})"
                )

        return results


if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent log-analysis")
    sys.exit(1)
