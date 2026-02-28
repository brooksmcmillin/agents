"""Log Analysis agent with automatic message pinning.

This agent reads and analyzes log files, automatically pinning tool results
that contain critical findings (errors, exceptions, stack traces, security
events, etc.) so they survive context trimming during long investigations.
"""

import logging
import re
from typing import Any

from agent_framework import Agent
from agent_framework.security.context_trimming import PINNED_EVENT_KEY
from anthropic.types import ToolUseBlock

from .prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT

logger = logging.getLogger(__name__)

# Tools this agent is allowed to use.
# Log analysis is a read-only diagnostic task — no communication tools
# to avoid exfiltration of log content via prompt injection.
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
]

# Log-reading tools whose results should be scanned for pin-worthy content.
_LOG_TOOLS = frozenset({"read_file", "grep_files"})

# Maximum number of tool results to pin per session to prevent excessive
# pinning from noisy logs filling the context with attacker-controlled content.
_MAX_PINS_PER_SESSION = 5

# Patterns that indicate a tool result contains critical log findings.
# Each entry is (compiled_regex, category_name) so classification is explicit
# and not inferred from the pattern string.
_CRITICAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Error levels
    (re.compile(r"\bERROR\b"), "error_level"),
    (re.compile(r"\bFATAL\b"), "error_level"),
    (re.compile(r"\bCRITICAL\b"), "error_level"),
    (re.compile(r"\bSEVERE\b"), "error_level"),
    (re.compile(r"\bEMERG(?:ENCY)?\b"), "error_level"),
    (re.compile(r"\bALERT\b"), "error_level"),
    # Exceptions and stack traces
    (re.compile(r"\bException\b"), "exception"),
    (re.compile(r"\bTraceback\b"), "exception"),
    (re.compile(r"\bpanic:\b"), "exception"),
    (re.compile(r"\bSegmentation fault\b", re.IGNORECASE), "exception"),
    (re.compile(r"\bstack trace\b", re.IGNORECASE), "exception"),
    (re.compile(r"at \S+\.\S+\(.*:\d+\)"), "exception"),  # Java stack frame
    (re.compile(r'File ".*", line \d+'), "exception"),  # Python stack frame
    # Resource exhaustion
    (re.compile(r"\bOOM\b|Out ?of ?[Mm]emory", re.IGNORECASE), "resource_exhaustion"),
    (re.compile(r"\bOOM[-_]?[Kk]ill", re.IGNORECASE), "resource_exhaustion"),
    (re.compile(r"No space left on device", re.IGNORECASE), "resource_exhaustion"),
    (re.compile(r"Too many open files", re.IGNORECASE), "resource_exhaustion"),
    (re.compile(r"Cannot allocate memory", re.IGNORECASE), "resource_exhaustion"),
    # Timeouts and connectivity — require contextual phrases to reduce false positives
    (re.compile(r"\b(?:connection|read|write|request) timeout\b", re.IGNORECASE), "connectivity"),
    (re.compile(r"\btimed? ?out\b", re.IGNORECASE), "connectivity"),
    (re.compile(r"\bconnection refused\b", re.IGNORECASE), "connectivity"),
    (re.compile(r"\bconnection reset\b", re.IGNORECASE), "connectivity"),
    (re.compile(r"\bECONNREFUSED\b"), "connectivity"),
    (re.compile(r"\bETIMEDOUT\b"), "connectivity"),
    # HTTP errors — bounded match to avoid ReDoS on long lines
    (re.compile(r"\b5\d{2}\b[^\n]{0,80}(?:error|fail|status)", re.IGNORECASE), "http_error"),
    (re.compile(r"HTTP[/ ]+\d\.\d[\"' ]+5\d{2}"), "http_error"),
    # Security events — require contextual phrases to reduce false positives
    (re.compile(r"authentication fail", re.IGNORECASE), "security_event"),
    (re.compile(r"permission denied", re.IGNORECASE), "security_event"),
    (re.compile(r"invalid token", re.IGNORECASE), "security_event"),
    (re.compile(r"brute.?force", re.IGNORECASE), "security_event"),
    # Process/service crashes — require contextual phrases
    (re.compile(r"\bOOM[-_]?kill", re.IGNORECASE), "process_crash"),
    (re.compile(r"\bcore dump", re.IGNORECASE), "process_crash"),
    (
        re.compile(r"(?:service|process|worker) (?:crash|died|exited)", re.IGNORECASE),
        "process_crash",
    ),
    (re.compile(r"\bSIGKILL\b|\bSIGSEGV\b|\bSIGABRT\b"), "process_crash"),
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
        A comma-separated category string (e.g. "error_level,exception") or None.
    """
    if len(content) < _MIN_CONTENT_LENGTH:
        return None

    matched_categories: set[str] = set()

    for pattern, category in _CRITICAL_PATTERNS:
        if pattern.search(content):
            matched_categories.add(category)
            # Stop early once we have enough evidence
            if len(matched_categories) >= 3:
                break

    if not matched_categories:
        return None

    return ",".join(sorted(matched_categories))


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
        self._pinned_count = 0

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
            # Stop pinning once we've hit the per-session cap
            if self._pinned_count >= _MAX_PINS_PER_SESSION:
                break

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
                self._pinned_count += 1
                logger.info(
                    f"Pinned tool result from {tool_name} "
                    f"({self._pinned_count}/{_MAX_PINS_PER_SESSION}, "
                    f"reason: {pin_reason}, length: {len(content)})"
                )

        return results


if __name__ == "__main__":
    import sys

    print("Direct execution is not supported. Use bin/run-agent instead:")
    print("  uv run bin/run-agent log-analysis")
    sys.exit(1)
