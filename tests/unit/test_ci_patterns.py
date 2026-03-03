"""Tests for agents/outcome_collector/ci_patterns.py.

Covers regex extraction of failure patterns from sample CI log output.
"""

from agents.outcome_collector.ci_patterns import extract_failure_patterns


class TestRuffPatterns:
    def test_extracts_ruff_codes(self) -> None:
        logs = """
        src/main.py:42:80: E501 Line too long (120 > 88)
        src/main.py:50:1: F841 Local variable 'x' is assigned to but never used
        """
        patterns = extract_failure_patterns(logs)
        assert "ruff:E501" in patterns
        assert "ruff:F841" in patterns

    def test_deduplicates_ruff_codes(self) -> None:
        logs = """
        src/a.py:1:1: E501 Line too long
        src/b.py:2:1: E501 Line too long
        """
        patterns = extract_failure_patterns(logs)
        assert patterns.count("ruff:E501") == 1

    def test_filters_non_lint_codes(self) -> None:
        """SHA-like strings should not match as lint codes."""
        logs = "commit ABC123 merged into main"
        patterns = extract_failure_patterns(logs)
        # ABC123 should not be treated as a lint code
        lint_patterns = [p for p in patterns if p.startswith("ruff:")]
        assert len(lint_patterns) == 0


class TestPytestPatterns:
    def test_extracts_pytest_failures(self) -> None:
        logs = """
        FAILED tests/test_auth.py::test_login - AssertionError
        FAILED tests/test_api.py::test_create_user - KeyError
        """
        patterns = extract_failure_patterns(logs)
        assert "pytest:tests/test_auth.py::test_login" in patterns
        assert "pytest:tests/test_api.py::test_create_user" in patterns


class TestMypyPatterns:
    def test_extracts_mypy_errors(self) -> None:
        logs = """
        src/main.py:10: error: Incompatible types in assignment [assignment]
        src/utils.py:20: error: Missing return statement [return]
        """
        patterns = extract_failure_patterns(logs)
        assert "mypy:assignment" in patterns
        assert "mypy:return" in patterns


class TestImportPatterns:
    def test_extracts_module_not_found(self) -> None:
        logs = "ModuleNotFoundError: No module named 'requests'"
        patterns = extract_failure_patterns(logs)
        assert any("ModuleNotFoundError" in p for p in patterns)

    def test_extracts_import_error(self) -> None:
        logs = "ImportError: cannot import name 'foo' from 'bar'"
        patterns = extract_failure_patterns(logs)
        assert any("ImportError" in p for p in patterns)

    def test_extracts_syntax_error(self) -> None:
        logs = "SyntaxError: unexpected EOF while parsing"
        patterns = extract_failure_patterns(logs)
        assert any("SyntaxError" in p for p in patterns)


class TestMixedLogs:
    def test_extracts_multiple_types(self) -> None:
        logs = """
        src/main.py:42:80: E501 Line too long (120 > 88)
        FAILED tests/test_auth.py::test_login - AssertionError
        src/utils.py:20: error: Missing return statement [return]
        ModuleNotFoundError: No module named 'requests'
        """
        patterns = extract_failure_patterns(logs)
        assert any(p.startswith("ruff:") for p in patterns)
        assert any(p.startswith("pytest:") for p in patterns)
        assert any(p.startswith("mypy:") for p in patterns)
        assert any(p.startswith("import:") for p in patterns)

    def test_empty_logs(self) -> None:
        patterns = extract_failure_patterns("")
        assert patterns == []

    def test_clean_logs_no_patterns(self) -> None:
        logs = "Build succeeded. All tests passed."
        patterns = extract_failure_patterns(logs)
        # Should not find any lint or test patterns
        assert not any(p.startswith("pytest:") for p in patterns)
        assert not any(p.startswith("mypy:") for p in patterns)
