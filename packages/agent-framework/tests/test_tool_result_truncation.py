"""Tests for centralized tool result truncation."""

from agent_framework.core.agent import MAX_TOOL_RESULT_CHARS, _truncate_tool_result


class TestTruncateToolResult:
    """Tests for _truncate_tool_result safety net."""

    def test_short_content_unchanged(self) -> None:
        """Content under the limit is returned as-is."""
        content = "hello world"
        assert _truncate_tool_result(content) == content

    def test_exact_limit_unchanged(self) -> None:
        """Content exactly at the limit is returned as-is."""
        content = "x" * MAX_TOOL_RESULT_CHARS
        assert _truncate_tool_result(content) == content

    def test_over_limit_is_truncated(self) -> None:
        """Content over the limit is truncated with a message."""
        content = "x" * (MAX_TOOL_RESULT_CHARS + 1000)
        result = _truncate_tool_result(content)
        assert len(result) < len(content)
        assert result.startswith("x" * 100)
        assert "[TRUNCATED:" in result
        assert "1,000 chars removed" in result

    def test_custom_max_chars(self) -> None:
        """Custom max_chars parameter works."""
        content = "a" * 200
        result = _truncate_tool_result(content, max_chars=100)
        assert result.startswith("a" * 100)
        assert "[TRUNCATED:" in result
        assert "100 chars removed" in result

    def test_truncation_message_includes_sizes(self) -> None:
        """Truncation message reports original and limit sizes."""
        content = "b" * 1000
        result = _truncate_tool_result(content, max_chars=500)
        assert "1,000 chars" in result
        assert "500" in result

    def test_empty_string(self) -> None:
        """Empty string is returned unchanged."""
        assert _truncate_tool_result("") == ""
