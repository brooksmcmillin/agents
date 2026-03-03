"""Input sanitization utilities for safe logging."""


def sanitize_log_input(value: str) -> str:
    """Sanitize user input for safe logging.

    Prevents log injection attacks by removing newlines and control characters
    that could be used to forge log entries or corrupt log analysis.

    Args:
        value: The string value to sanitize.

    Returns:
        The sanitized string safe for use in log messages.
    """
    # Replace newlines and carriage returns, then remove other control chars
    sanitized = value.replace("\n", "\\n").replace("\r", "\\r")
    # Remove other ASCII control characters (0x00-0x1F except tab)
    return "".join(c if c == "\t" or (ord(c) >= 0x20) else f"\\x{ord(c):02x}" for c in sanitized)
