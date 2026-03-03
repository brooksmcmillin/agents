"""Input sanitization utilities for safe logging."""

# Unicode characters that can confuse log parsers or viewers.
# U+0085 NEXT LINE (NEL) is a C1 control character treated as a line
# terminator by some parsers (ISO 6429, certain SIEM tools).
# U+2028 LINE SEPARATOR and U+2029 PARAGRAPH SEPARATOR are treated as line
# terminators by some log parsers and SIEM tools.
# BIDI override characters (U+202A-U+202E, U+2066-U+2069) can make log
# entries appear to contain different content in Unicode-aware terminals.
_UNICODE_LINE_SEPS = frozenset({"\u0085", "\u2028", "\u2029"})
_BIDI_OVERRIDES = frozenset(
    chr(cp) for cp in list(range(0x202A, 0x202F)) + list(range(0x2066, 0x206A))
)
_DANGEROUS_UNICODE = _UNICODE_LINE_SEPS | _BIDI_OVERRIDES


def sanitize_log_input(value: str) -> str:
    """Sanitize user input for safe logging.

    Prevents log injection attacks by removing newlines, control characters,
    and Unicode characters that could be used to forge log entries, corrupt
    log analysis, or confuse SIEM tools.

    Specifically escapes:
    - ASCII newlines (\\n, \\r)
    - ASCII control characters (0x00-0x1F, except tab which is preserved)
    - C1 control character U+0085 NEXT LINE (NEL)
    - Unicode line/paragraph separators (U+2028, U+2029)
    - Unicode BIDI override characters (U+202A-U+202E, U+2066-U+2069)

    Args:
        value: The string value to sanitize.

    Returns:
        The sanitized string safe for use in log messages.
    """
    # Replace newlines and carriage returns
    sanitized = value.replace("\n", "\\n").replace("\r", "\\r")
    # Escape ASCII control characters (0x00-0x1F except tab), C1 control chars,
    # Unicode line separators, and BIDI override characters
    return "".join(
        f"\\u{ord(c):04x}"
        if c in _DANGEROUS_UNICODE
        else (c if c == "\t" or (ord(c) >= 0x20) else f"\\x{ord(c):02x}")
        for c in sanitized
    )
