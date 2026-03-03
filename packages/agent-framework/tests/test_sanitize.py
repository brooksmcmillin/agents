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

    def test_escapes_c1_control_characters(self) -> None:
        # C1 control characters (U+0080-U+009F) satisfy ord(c) >= 0x20 but
        # are non-printing controls that can confuse log parsers and terminals.
        # U+0085 NEL: treated as line terminator by some parsers.
        result_nel = sanitize_log_input("before\u0085after")
        assert "\u0085" not in result_nel
        assert "\\u0085" in result_nel
        # U+009B CSI: can introduce ANSI escape sequences in terminal viewers.
        result_csi = sanitize_log_input("before\u009bafter")
        assert "\u009b" not in result_csi
        assert "\\u009b" in result_csi
        # Other C1 chars should also be escaped.
        for cp in range(0x80, 0xA0):
            c = chr(cp)
            result = sanitize_log_input(f"x{c}y")
            assert c not in result
            assert f"\\u{cp:04x}" in result

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
