"""Unit tests for agent_framework/telemetry/tool_logger.py."""

import json
import logging
from pathlib import Path

import agent_framework.telemetry.tool_logger as tool_logger_module
import pytest
from agent_framework.telemetry.tool_logger import configure_tool_logger, log_tool_invocation


@pytest.fixture(autouse=True)
def reset_tool_logger():
    """Reset global _tool_logger state before each test to prevent interference."""
    tool_logger_module._tool_logger = None
    # Clear any existing handlers on the logger to avoid cross-test pollution
    logger = logging.getLogger("mcp.tool_invocations")
    logger.handlers.clear()
    yield
    # Cleanup after test
    logger.handlers.clear()
    tool_logger_module._tool_logger = None


class TestConfigureToolLoggerPathValidation:
    """Tests for configure_tool_logger() path validation against _ALLOWED_LOG_DIRS."""

    def test_rejects_path_outside_allowed_dirs(self, tmp_path: Path) -> None:
        """Paths outside allowed directories should raise ValueError."""
        outside_path = str(tmp_path / "tool_invocations.log")
        with pytest.raises(ValueError, match="Tool log path must be within"):
            configure_tool_logger(outside_path)

    def test_rejects_slash_etc(self) -> None:
        """Path in /etc should be rejected."""
        with pytest.raises(ValueError, match="Tool log path must be within"):
            configure_tool_logger("/etc/tool_invocations.log")

    def test_rejects_slash_tmp(self) -> None:
        """Path in /tmp should be rejected."""
        with pytest.raises(ValueError, match="Tool log path must be within"):
            configure_tool_logger("/tmp/tool_invocations.log")

    def test_rejects_home_directory_path(self, tmp_path: Path) -> None:
        """Paths in user home directories should be rejected."""
        with pytest.raises(ValueError, match="Tool log path must be within"):
            configure_tool_logger("/home/user/tool_invocations.log")

    def test_rejects_path_traversal_attempt(self, tmp_path: Path) -> None:
        """Path traversal attempts (../) that escape allowed dirs should be rejected."""
        # Construct a path that looks like it's in .data/ but uses traversal to escape
        # Resolved path will be outside allowed dirs
        with pytest.raises(ValueError, match="Tool log path must be within"):
            configure_tool_logger("/tmp/../etc/tool_invocations.log")

    def test_accepts_path_within_data_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Paths within .data/ relative to cwd should be accepted."""
        # Monkeypatch cwd to tmp_path so .data/ resolves inside tmp_path
        monkeypatch.chdir(tmp_path)
        log_path = str(tmp_path / ".data" / "logs" / "tool_invocations.log")
        # The .data/ allowed dir is checked as Path(".data/").resolve() from cwd
        # So we need to create a path that starts with tmp_path / ".data"
        (tmp_path / ".data" / "logs").mkdir(parents=True, exist_ok=True)
        configure_tool_logger(log_path)
        assert tool_logger_module._tool_logger is not None

    def test_accepts_path_within_var_log(self, tmp_path: Path) -> None:
        """Paths within /var/log/ should be accepted if /var/log exists."""
        var_log = Path("/var/log")
        if not var_log.exists():
            pytest.skip("/var/log does not exist on this system")
        # We won't actually write here but the path validation should pass
        # Use a non-existent subdirectory so we don't accidentally create real files
        log_path = "/var/log/test_agent_tools.log"
        # This may raise PermissionError when creating the file, but not ValueError
        try:
            configure_tool_logger(log_path)
        except PermissionError:
            pass  # Expected on systems where we can't write to /var/log
        except ValueError:
            pytest.fail("ValueError raised for path within /var/log/")

    def test_error_message_includes_rejected_path(self, tmp_path: Path) -> None:
        """Error message should include the resolved path that was rejected."""
        outside_path = str(tmp_path / "tool_invocations.log")
        with pytest.raises(ValueError) as exc_info:
            configure_tool_logger(outside_path)
        # The error message should include the resolved path
        assert str(tmp_path) in str(exc_info.value)

    def test_error_message_includes_allowed_dirs(self) -> None:
        """Error message should reference the allowed directories."""
        with pytest.raises(ValueError) as exc_info:
            configure_tool_logger("/tmp/tool.log")
        assert "_ALLOWED_LOG_DIRS" in str(exc_info.value) or "Tool log path must be within" in str(
            exc_info.value
        )

    def test_sets_global_tool_logger_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful configuration should set the global _tool_logger."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data" / "logs").mkdir(parents=True, exist_ok=True)
        log_path = str(tmp_path / ".data" / "logs" / "tool_invocations.log")
        assert tool_logger_module._tool_logger is None
        configure_tool_logger(log_path)
        assert tool_logger_module._tool_logger is not None

    def test_creates_parent_directories_on_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Parent directories should be created if they don't exist."""
        monkeypatch.chdir(tmp_path)
        nested_log_path = str(tmp_path / ".data" / "deep" / "nested" / "tool.log")
        configure_tool_logger(nested_log_path)
        assert (tmp_path / ".data" / "deep" / "nested").exists()

    def test_repeated_calls_clear_handlers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Calling configure_tool_logger multiple times should not accumulate handlers."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = str(tmp_path / ".data" / "tool.log")
        configure_tool_logger(log_path)
        configure_tool_logger(log_path)
        configure_tool_logger(log_path)
        logger = logging.getLogger("mcp.tool_invocations")
        assert len(logger.handlers) == 1


class TestLogToolInvocation:
    """Tests for log_tool_invocation() JSONL output format."""

    def test_does_nothing_when_logger_not_configured(self) -> None:
        """log_tool_invocation should silently return when _tool_logger is None."""
        assert tool_logger_module._tool_logger is None
        # Should not raise
        log_tool_invocation(
            tool_name="some_tool",
            arguments={"key": "value"},
            result={"status": "ok"},
            duration_ms=10.0,
        )

    def test_writes_valid_json_line(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """log_tool_invocation should write a valid JSON line to the log file."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="fetch_web_content",
            arguments={"url": "https://example.com", "timeout": 30},
            result={"status": "success", "content": "..."},
            duration_ms=123.45,
        )

        # Flush handlers
        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert isinstance(record, dict)

    def test_json_record_has_required_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each log record must contain all required fields."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="search_memory",
            arguments={"query": "test"},
            result={"results": []},
            duration_ms=5.0,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        assert "id" in record
        assert "timestamp" in record
        assert "tool_name" in record
        assert "duration_ms" in record
        assert "success" in record
        assert "error_type" in record
        assert "param_names" in record

    def test_tool_name_recorded_correctly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """tool_name field should match the provided tool name."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="my_custom_tool",
            arguments={},
            result={"ok": True},
            duration_ms=1.0,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        assert record["tool_name"] == "my_custom_tool"

    def test_duration_ms_rounded_to_two_decimals(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """duration_ms should be rounded to 2 decimal places."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={},
            duration_ms=123.456789,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        assert record["duration_ms"] == 123.46

    def test_success_true_when_no_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """success should be True when error is None and result has no 'error' key."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={"data": "ok"},
            duration_ms=1.0,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        assert record["success"] is True
        assert record["error_type"] is None

    def test_success_false_when_exception_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """success should be False when error is not None."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        exc = ValueError("something went wrong")
        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result=None,
            duration_ms=5.0,
            error=exc,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        assert record["success"] is False
        assert record["error_type"] == "ValueError"

    def test_error_type_uses_exception_class_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """error_type should be the class name of the exception."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result=None,
            duration_ms=1.0,
            error=RuntimeError("boom"),
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        assert record["error_type"] == "RuntimeError"

    def test_success_false_when_result_has_error_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """success should be False when result dict contains an 'error' key."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={"error": "Something failed"},
            duration_ms=2.0,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        assert record["success"] is False
        assert record["error_type"] == "tool_error_response"

    def test_param_names_logged_without_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only argument keys should be logged, not their values."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="tool",
            arguments={"secret_api_key": "my-super-secret", "url": "https://example.com"},
            result={},
            duration_ms=1.0,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        raw = log_path.read_text()
        record = json.loads(raw.strip())
        # Keys should be present
        assert "secret_api_key" in record["param_names"]
        assert "url" in record["param_names"]
        # Values must NOT appear in the log
        assert "my-super-secret" not in raw

    def test_param_names_are_sorted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """param_names should be sorted alphabetically."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="tool",
            arguments={"zebra": 1, "apple": 2, "mango": 3},
            result={},
            duration_ms=1.0,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        assert record["param_names"] == ["apple", "mango", "zebra"]

    def test_empty_arguments_produces_empty_param_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty arguments dict should produce an empty param_names list."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={},
            duration_ms=1.0,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        assert record["param_names"] == []

    def test_id_is_uuid_string(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """id field should be a valid UUID string."""
        import uuid

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={},
            duration_ms=1.0,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        # Should parse without raising
        parsed_uuid = uuid.UUID(record["id"])
        assert str(parsed_uuid) == record["id"]

    def test_timestamp_is_iso_format_with_utc(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """timestamp field should be an ISO 8601 string with UTC timezone info."""
        from datetime import datetime

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={},
            duration_ms=1.0,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        # Should parse as a datetime with timezone info
        ts = datetime.fromisoformat(record["timestamp"])
        assert ts.tzinfo is not None

    def test_multiple_invocations_write_multiple_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each invocation should write exactly one line; multiple calls produce multiple lines."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        for i in range(3):
            log_tool_invocation(
                tool_name=f"tool_{i}",
                arguments={"index": i},
                result={},
                duration_ms=float(i),
            )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 3
        for i, line in enumerate(lines):
            record = json.loads(line)
            assert record["tool_name"] == f"tool_{i}"

    def test_non_dict_result_with_no_error_is_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-dict result with no error should be recorded as success."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result="plain string result",
            duration_ms=1.0,
        )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        record = json.loads(log_path.read_text().strip())
        assert record["success"] is True
        assert record["error_type"] is None

    def test_unique_ids_per_invocation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each invocation should produce a unique ID."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / ".data" / "tool.log"
        configure_tool_logger(str(log_path))

        for _ in range(5):
            log_tool_invocation(
                tool_name="tool",
                arguments={},
                result={},
                duration_ms=1.0,
            )

        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()

        ids = [json.loads(line)["id"] for line in log_path.read_text().strip().splitlines()]
        assert len(set(ids)) == 5
