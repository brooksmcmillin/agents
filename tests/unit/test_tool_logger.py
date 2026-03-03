"""Unit tests for agent_framework/telemetry/tool_logger.py."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import agent_framework.telemetry.tool_logger as tool_logger_module
import pytest
from agent_framework.telemetry.tool_logger import configure_tool_logger, log_tool_invocation


@pytest.fixture(autouse=True)
def reset_tool_logger() -> None:
    """Reset global _tool_logger state before each test to prevent interference."""
    tool_logger_module._tool_logger = None
    logger = logging.getLogger("mcp.tool_invocations")
    logger.handlers.clear()
    yield
    logger.handlers.clear()
    tool_logger_module._tool_logger = None


@pytest.fixture
def configured_logger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure tool logger pointing to a temp .data dir; return the log path."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".data").mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / ".data" / "tool.log"
    configure_tool_logger(str(log_path))
    return log_path


def flush_and_read_records(log_path: Path) -> list[dict]:
    """Flush all handlers and return all parsed JSONL records from the log file."""
    for handler in logging.getLogger("mcp.tool_invocations").handlers:
        handler.flush()
    return [json.loads(line) for line in log_path.read_text().strip().splitlines()]


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

    def test_rejects_home_directory_path(self) -> None:
        """Paths in user home directories should be rejected."""
        with pytest.raises(ValueError, match="Tool log path must be within"):
            configure_tool_logger("/home/user/tool_invocations.log")

    def test_rejects_path_traversal_attempt(self) -> None:
        """Path traversal attempts (../) that escape allowed dirs should be rejected."""
        with pytest.raises(ValueError, match="Tool log path must be within"):
            configure_tool_logger("/tmp/../etc/tool_invocations.log")

    def test_rejects_path_with_allowed_dir_as_prefix_but_outside(self) -> None:
        """A path that merely shares a string prefix with an allowed dir should be rejected.

        '/var/log_evil/' starts with '/var/log' but is NOT a child of '/var/log/'.
        This guards against the startswith() prefix-bypass vulnerability.
        """
        with pytest.raises(ValueError, match="Tool log path must be within"):
            configure_tool_logger("/var/log_evil/tool.log")

    def test_rejects_path_with_data_dir_as_prefix_but_outside(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A path sharing a prefix with .data/ but not inside it should be rejected."""
        monkeypatch.chdir(tmp_path)
        # .data_extra/ starts with .data but is not inside .data/
        evil_path = str(tmp_path / ".data_extra" / "tool.log")
        with pytest.raises(ValueError, match="Tool log path must be within"):
            configure_tool_logger(evil_path)

    def test_accepts_path_within_data_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Paths within .data/ relative to cwd should be accepted."""
        monkeypatch.chdir(tmp_path)
        log_path = str(tmp_path / ".data" / "logs" / "tool_invocations.log")
        (tmp_path / ".data" / "logs").mkdir(parents=True, exist_ok=True)
        configure_tool_logger(log_path)
        assert tool_logger_module._tool_logger is not None

    def test_accepts_path_within_var_log(self) -> None:
        """Paths within /var/log/ should be accepted if /var/log exists."""
        if not Path("/var/log").exists():
            pytest.skip("/var/log does not exist on this system")
        try:
            configure_tool_logger("/var/log/test_agent_tool_logger.log")
        except PermissionError:
            pass  # Expected on systems where we can't write to /var/log
        except ValueError:
            pytest.fail("ValueError raised for path within /var/log/")

    def test_error_message_includes_rejected_path(self, tmp_path: Path) -> None:
        """Error message should include the resolved path that was rejected."""
        outside_path = str(tmp_path / "tool_invocations.log")
        with pytest.raises(ValueError) as exc_info:
            configure_tool_logger(outside_path)
        assert str(tmp_path) in str(exc_info.value)

    def test_error_message_includes_prefix_text(self) -> None:
        """Error message should include the 'Tool log path must be within' prefix."""
        with pytest.raises(ValueError) as exc_info:
            configure_tool_logger("/tmp/tool.log")
        assert "Tool log path must be within" in str(exc_info.value)

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

    def test_writes_valid_json_line(self, configured_logger: Path) -> None:
        """log_tool_invocation should write a valid JSON line to the log file."""
        log_tool_invocation(
            tool_name="fetch_web_content",
            arguments={"url": "https://example.com", "timeout": 30},
            result={"status": "success", "content": "..."},
            duration_ms=123.45,
        )
        records = flush_and_read_records(configured_logger)
        assert len(records) == 1
        assert isinstance(records[0], dict)

    def test_json_record_has_required_fields(self, configured_logger: Path) -> None:
        """Each log record must contain all required fields."""
        log_tool_invocation(
            tool_name="search_memory",
            arguments={"query": "test"},
            result={"results": []},
            duration_ms=5.0,
        )
        record = flush_and_read_records(configured_logger)[0]
        assert "id" in record
        assert "timestamp" in record
        assert "tool_name" in record
        assert "duration_ms" in record
        assert "success" in record
        assert "error_type" in record
        assert "param_names" in record

    def test_tool_name_recorded_correctly(self, configured_logger: Path) -> None:
        """tool_name field should match the provided tool name."""
        log_tool_invocation(
            tool_name="my_custom_tool",
            arguments={},
            result={"ok": True},
            duration_ms=1.0,
        )
        record = flush_and_read_records(configured_logger)[0]
        assert record["tool_name"] == "my_custom_tool"

    def test_duration_ms_rounded_to_two_decimals(self, configured_logger: Path) -> None:
        """duration_ms should be rounded to 2 decimal places."""
        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={},
            duration_ms=123.456789,
        )
        record = flush_and_read_records(configured_logger)[0]
        assert record["duration_ms"] == 123.46

    def test_success_true_when_no_error(self, configured_logger: Path) -> None:
        """success should be True when error is None and result has no 'error' key."""
        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={"data": "ok"},
            duration_ms=1.0,
        )
        record = flush_and_read_records(configured_logger)[0]
        assert record["success"] is True
        assert record["error_type"] is None

    def test_success_false_when_exception_raised(self, configured_logger: Path) -> None:
        """success should be False when error is not None."""
        exc = ValueError("something went wrong")
        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result=None,
            duration_ms=5.0,
            error=exc,
        )
        record = flush_and_read_records(configured_logger)[0]
        assert record["success"] is False
        assert record["error_type"] == "ValueError"

    def test_error_type_uses_exception_class_name(self, configured_logger: Path) -> None:
        """error_type should be the class name of the exception."""
        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result=None,
            duration_ms=1.0,
            error=RuntimeError("boom"),
        )
        record = flush_and_read_records(configured_logger)[0]
        assert record["error_type"] == "RuntimeError"

    def test_success_false_when_result_has_error_key(self, configured_logger: Path) -> None:
        """success should be False when result dict contains an 'error' key."""
        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={"error": "Something failed"},
            duration_ms=2.0,
        )
        record = flush_and_read_records(configured_logger)[0]
        assert record["success"] is False
        assert record["error_type"] == "tool_error_response"

    def test_param_names_logged_without_values(self, configured_logger: Path) -> None:
        """Only argument keys should be logged, not their values."""
        log_tool_invocation(
            tool_name="tool",
            arguments={"secret_api_key": "my-super-secret", "url": "https://example.com"},
            result={},
            duration_ms=1.0,
        )
        for handler in logging.getLogger("mcp.tool_invocations").handlers:
            handler.flush()
        raw = configured_logger.read_text()
        record = json.loads(raw.strip())
        assert "secret_api_key" in record["param_names"]
        assert "url" in record["param_names"]
        # Argument values must NOT appear in the log
        assert "my-super-secret" not in raw

    def test_param_names_are_sorted(self, configured_logger: Path) -> None:
        """param_names should be sorted alphabetically."""
        log_tool_invocation(
            tool_name="tool",
            arguments={"zebra": 1, "apple": 2, "mango": 3},
            result={},
            duration_ms=1.0,
        )
        record = flush_and_read_records(configured_logger)[0]
        assert record["param_names"] == ["apple", "mango", "zebra"]

    def test_empty_arguments_produces_empty_param_names(self, configured_logger: Path) -> None:
        """Empty arguments dict should produce an empty param_names list."""
        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={},
            duration_ms=1.0,
        )
        record = flush_and_read_records(configured_logger)[0]
        assert record["param_names"] == []

    def test_id_is_uuid_string(self, configured_logger: Path) -> None:
        """id field should be a valid UUID string."""
        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={},
            duration_ms=1.0,
        )
        record = flush_and_read_records(configured_logger)[0]
        parsed_uuid = uuid.UUID(record["id"])
        assert str(parsed_uuid) == record["id"]

    def test_timestamp_is_iso_format_with_utc(self, configured_logger: Path) -> None:
        """timestamp field should be an ISO 8601 string with UTC timezone info."""
        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result={},
            duration_ms=1.0,
        )
        record = flush_and_read_records(configured_logger)[0]
        ts = datetime.fromisoformat(record["timestamp"])
        assert ts.tzinfo is not None

    def test_multiple_invocations_write_multiple_lines(self, configured_logger: Path) -> None:
        """Each invocation should write exactly one line; multiple calls produce multiple lines."""
        for i in range(3):
            log_tool_invocation(
                tool_name=f"tool_{i}",
                arguments={"index": i},
                result={},
                duration_ms=float(i),
            )
        records = flush_and_read_records(configured_logger)
        assert len(records) == 3
        for i, record in enumerate(records):
            assert record["tool_name"] == f"tool_{i}"

    def test_non_dict_result_with_no_error_is_success(self, configured_logger: Path) -> None:
        """Non-dict result with no error should be recorded as success."""
        log_tool_invocation(
            tool_name="tool",
            arguments={},
            result="plain string result",
            duration_ms=1.0,
        )
        record = flush_and_read_records(configured_logger)[0]
        assert record["success"] is True
        assert record["error_type"] is None

    def test_unique_ids_per_invocation(self, configured_logger: Path) -> None:
        """Each invocation should produce a unique ID."""
        for _ in range(5):
            log_tool_invocation(
                tool_name="tool",
                arguments={},
                result={},
                duration_ms=1.0,
            )
        records = flush_and_read_records(configured_logger)
        ids = [r["id"] for r in records]
        assert len(set(ids)) == 5
