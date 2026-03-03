"""CI log failure pattern extraction.

Regex-based extraction of structured failure codes from CI log output.
Supports ruff/flake8, pytest, mypy, and generic build errors.
"""

from __future__ import annotations

import re

# Ruff / flake8 rule codes: E501, F841, etc.
_RUFF_RE = re.compile(r"\b([A-Z]{1,3}\d{3,4})\b")

# Pytest failures: FAILED tests/test_foo.py::test_bar
_PYTEST_RE = re.compile(r"FAILED\s+([\w/.]+::\w+)")

# Mypy errors: error: <message> [<code>]
_MYPY_RE = re.compile(r"error:\s+(.+?)\s+\[(\w+)\]")

# Generic import/syntax errors (bounded to 200 chars to avoid backtracking on long lines)
_GENERIC_RE = re.compile(r"(ModuleNotFoundError|ImportError|SyntaxError):\s*(.{1,200})")

# Build tool errors (bounded match length)
_BUILD_RE = re.compile(r"(npm ERR!|cargo error|go build)\s*(.{1,200})")


def extract_failure_patterns(logs: str) -> list[str]:
    """Extract structured failure patterns from CI log output.

    Returns deduplicated list of pattern strings like:
    - "ruff:E501"
    - "pytest:tests/test_auth.py::test_login"
    - "mypy:incompatible-type"
    - "import:ModuleNotFoundError: no module named 'foo'"

    Args:
        logs: Raw CI log text.

    Returns:
        List of extracted pattern identifiers.
    """
    patterns: list[str] = []
    seen: set[str] = set()

    def _add(pattern: str) -> None:
        if pattern not in seen:
            seen.add(pattern)
            patterns.append(pattern)

    # Ruff/flake8 codes
    for match in _RUFF_RE.finditer(logs):
        code = match.group(1)
        # Filter out things that look like codes but aren't (e.g., SHA prefixes)
        if _is_lint_code(code):
            _add(f"ruff:{code}")

    # Pytest failures
    for match in _PYTEST_RE.finditer(logs):
        _add(f"pytest:{match.group(1)}")

    # Mypy errors
    for match in _MYPY_RE.finditer(logs):
        _add(f"mypy:{match.group(2)}")

    # Generic import/syntax errors
    for match in _GENERIC_RE.finditer(logs):
        error_type = match.group(1)
        message = match.group(2).strip()[:100]
        _add(f"import:{error_type}: {message}")

    # Build tool errors
    for match in _BUILD_RE.finditer(logs):
        tool = match.group(1).strip().rstrip("!")
        message = match.group(2).strip()[:80]
        _add(f"build:{tool}: {message}")

    return patterns


# Known lint rule prefixes from ruff/flake8/pylint
_LINT_PREFIXES = frozenset(
    {
        "E",
        "W",
        "F",
        "C",
        "N",
        "D",
        "S",
        "B",
        "A",
        "T",
        "I",
        "UP",
        "YTT",
        "ANN",
        "BLE",
        "FBT",
        "COM",
        "DTZ",
        "EM",
        "EXE",
        "FA",
        "ISC",
        "ICN",
        "G",
        "INP",
        "PIE",
        "PT",
        "Q",
        "RSE",
        "RET",
        "SLF",
        "SIM",
        "TID",
        "TCH",
        "INT",
        "ARG",
        "ERA",
        "PD",
        "PGH",
        "PL",
        "TRY",
        "FLY",
        "NPY",
        "AIR",
        "PERF",
        "RUF",
        "FURB",
        "LOG",
    }
)


def _is_lint_code(code: str) -> bool:
    """Check if a code looks like a valid lint rule (not a random alphanumeric)."""
    # Extract alpha prefix
    prefix = ""
    for ch in code:
        if ch.isalpha():
            prefix += ch
        else:
            break
    return prefix in _LINT_PREFIXES
