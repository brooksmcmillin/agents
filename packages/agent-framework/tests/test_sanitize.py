"""Tests for the sanitize_log_input shared utility."""

from agent_framework.utils.sanitize import sanitize_log_input


class TestSanitizeLogInput:
    """Tests for sanitize_log_input."""

    def test_replaces_newlines(self) -> None:
        assert "\\n" in sanitize_log_input("line1\nline2")
        assert "\n" not in sanitize_log_input("line1\nline2")

    def test_replaces_carriage_returns(self) -> None:
        assert "\\r" in sanitize_log_input("line1\rline2")
        assert "\r" not in sanitize_log_input("line1\rline2")

    def test_removes_null_bytes(self) -> None:
        result = sanitize_log_input("before\x00after")
        assert "\x00" not in result
        assert "\\x00" in result

    def test_removes_control_chars(self) -> None:
        result = sanitize_log_input("test\x01\x02\x03value")
        assert "\x01" not in result
        assert "\x02" not in result
        assert "\x03" not in result

    def test_preserves_tabs(self) -> None:
        assert "\t" in sanitize_log_input("col1\tcol2")

    def test_preserves_unicode(self) -> None:
        assert "hello" in sanitize_log_input("hello 世界")

    def test_normal_text_unchanged(self) -> None:
        assert sanitize_log_input("hello world") == "hello world"

    def test_empty_string(self) -> None:
        assert sanitize_log_input("") == ""

    def test_combined_newline_and_control_chars(self) -> None:
        result = sanitize_log_input("line\nwith\x01control")
        assert "\n" not in result
        assert "\x01" not in result
        assert "\\n" in result
        assert "\\x01" in result
