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

    def test_preserves_benign_unicode(self) -> None:
        # General Unicode (e.g. CJK characters) should pass through unchanged.
        result = sanitize_log_input("hello 世界")
        assert "hello" in result
        assert "世界" in result

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

    def test_escapes_nel_c1_control(self) -> None:
        # U+0085 NEXT LINE (NEL) is a C1 control character treated as a line
        # terminator by some parsers (ISO 6429, certain SIEM tools).
        result = sanitize_log_input("before\u0085after")
        assert "\u0085" not in result
        assert "\\u0085" in result

    def test_escapes_unicode_line_separator(self) -> None:
        # U+2028 LINE SEPARATOR is treated as a line terminator by some parsers.
        result = sanitize_log_input("before\u2028after")
        assert "\u2028" not in result
        assert "\\u2028" in result

    def test_escapes_unicode_paragraph_separator(self) -> None:
        # U+2029 PARAGRAPH SEPARATOR is treated as a line terminator by some parsers.
        result = sanitize_log_input("before\u2029after")
        assert "\u2029" not in result
        assert "\\u2029" in result

    def test_escapes_bidi_override_characters(self) -> None:
        # BIDI override characters can disguise log entry content.
        bidi_chars = [
            "\u202a",  # LEFT-TO-RIGHT EMBEDDING
            "\u202b",  # RIGHT-TO-LEFT EMBEDDING
            "\u202c",  # POP DIRECTIONAL FORMATTING
            "\u202d",  # LEFT-TO-RIGHT OVERRIDE
            "\u202e",  # RIGHT-TO-LEFT OVERRIDE
            "\u2066",  # LEFT-TO-RIGHT ISOLATE
            "\u2069",  # POP DIRECTIONAL ISOLATE
        ]
        for bidi_char in bidi_chars:
            result = sanitize_log_input(f"before{bidi_char}after")
            assert bidi_char not in result
            assert f"\\u{ord(bidi_char):04x}" in result
