"""Tests for the structured decision logger."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import agent_framework.telemetry.decision_logger as dl

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_decision_logger():
    """Reset the global decision logger state before and after each test."""
    from agent_framework.telemetry.decision_logger import reset_decision_logger

    reset_decision_logger()
    yield
    reset_decision_logger()


# ─── configure_decision_logger ───────────────────────────────────────────────


class TestConfigureDecisionLogger:
    def test_rejects_path_outside_allowed_dirs(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import configure_decision_logger

        with pytest.raises(ValueError, match="must be within"):
            configure_decision_logger(str(tmp_path / "decisions.jsonl"))

    def test_accepts_allowed_path(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import configure_decision_logger

        log_path = tmp_path / "decisions.jsonl"
        with patch.object(dl, "ALLOWED_LOG_DIRS", (str(tmp_path),)):
            configure_decision_logger(str(log_path))

        assert dl._decision_logger is not None

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import configure_decision_logger

        log_path = tmp_path / "subdir" / "nested" / "decisions.jsonl"
        with patch.object(dl, "ALLOWED_LOG_DIRS", (str(tmp_path),)):
            configure_decision_logger(str(log_path))

        assert log_path.parent.exists()

    def test_repeated_calls_replace_handler(self, tmp_path: Path) -> None:
        """Calling configure_decision_logger twice should not add duplicate handlers."""
        from agent_framework.telemetry.decision_logger import configure_decision_logger

        log_path = tmp_path / "decisions.jsonl"
        with patch.object(dl, "ALLOWED_LOG_DIRS", (str(tmp_path),)):
            configure_decision_logger(str(log_path))
            configure_decision_logger(str(log_path))

        assert dl._decision_logger is not None
        assert len(dl._decision_logger.handlers) == 1


# ─── log_decision ────────────────────────────────────────────────────────────


class TestLogDecision:
    def _configure(self, tmp_path: Path) -> Path:
        """Set up the logger and return the log file path."""
        from agent_framework.telemetry.decision_logger import configure_decision_logger

        log_path = tmp_path / "decisions.jsonl"
        with patch.object(dl, "ALLOWED_LOG_DIRS", (str(tmp_path),)):
            configure_decision_logger(str(log_path))
        return log_path

    def _read_records(self, log_path: Path) -> list[dict]:
        """Parse all JSONL records from the log file."""
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def test_noop_when_not_configured(self) -> None:
        """log_decision should be a no-op when logger is not configured."""
        from agent_framework.telemetry.decision_logger import log_decision

        # Must not raise even without configuration
        log_decision(
            agent="TestAgent",
            decision_type="tool_selection",
            inputs={"available_tools": ["tool_a"]},
            output={"selected_tools": ["tool_a"]},
        )

    def test_invalid_decision_type_raises_even_when_unconfigured(self) -> None:
        """ValueError must be raised for invalid decision_type even with no logger."""
        from agent_framework.telemetry.decision_logger import log_decision

        # Logger is not configured (autouse fixture cleared it), but the
        # validation should still run so typos are caught in development.
        with pytest.raises(ValueError, match="Unknown decision_type"):
            log_decision(
                agent="TestAgent",
                decision_type="tool_seleciton",  # typo
                inputs={},
                output={},
            )

    def test_writes_jsonl_record(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import log_decision

        log_path = self._configure(tmp_path)

        log_decision(
            agent="MyAgent",
            decision_type="tool_selection",
            inputs={"available_tool_count": 5},
            output={"selected_tools": ["web_search"], "tool_count": 1},
        )

        records = self._read_records(log_path)
        assert len(records) == 1
        r = records[0]
        assert r["agent"] == "MyAgent"
        assert r["decision_type"] == "tool_selection"
        assert r["inputs"] == {"available_tool_count": 5}
        assert r["output"] == {"selected_tools": ["web_search"], "tool_count": 1}

    def test_record_has_required_fields(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import log_decision

        log_path = self._configure(tmp_path)

        log_decision(
            agent="MyAgent",
            decision_type="routing",
            inputs={"message": "route me"},
            output={"route": "pr_agent"},
        )

        records = self._read_records(log_path)
        r = records[0]
        assert "id" in r
        assert "timestamp" in r
        assert "agent" in r
        assert "decision_type" in r
        assert "inputs" in r
        assert "output" in r

    def test_optional_reasoning_included(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import log_decision

        log_path = self._configure(tmp_path)

        log_decision(
            agent="MyAgent",
            decision_type="decomposition",
            inputs={"task": "big task"},
            output={"subtask_count": 3},
            reasoning="Task is too large for one step.",
        )

        records = self._read_records(log_path)
        assert records[0]["reasoning"] == "Task is too large for one step."

    def test_reasoning_omitted_when_none(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import log_decision

        log_path = self._configure(tmp_path)

        log_decision(
            agent="MyAgent",
            decision_type="tool_selection",
            inputs={},
            output={},
        )

        records = self._read_records(log_path)
        assert "reasoning" not in records[0]

    def test_optional_session_id_included(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import log_decision

        log_path = self._configure(tmp_path)

        log_decision(
            agent="MyAgent",
            decision_type="tool_selection",
            inputs={},
            output={},
            session_id="sess-abc123",
        )

        records = self._read_records(log_path)
        assert records[0]["session_id"] == "sess-abc123"

    def test_session_id_omitted_when_none(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import log_decision

        log_path = self._configure(tmp_path)

        log_decision(
            agent="MyAgent",
            decision_type="tool_selection",
            inputs={},
            output={},
        )

        records = self._read_records(log_path)
        assert "session_id" not in records[0]

    def test_invalid_decision_type_raises(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import log_decision

        self._configure(tmp_path)

        with pytest.raises(ValueError, match="Unknown decision_type"):
            log_decision(
                agent="MyAgent",
                decision_type="nonexistent_type",
                inputs={},
                output={},
            )

    def test_multiple_records_written(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import log_decision

        log_path = self._configure(tmp_path)

        for i in range(5):
            log_decision(
                agent="MyAgent",
                decision_type="tool_selection",
                inputs={"iteration": i},
                output={"selected_tools": []},
            )

        records = self._read_records(log_path)
        assert len(records) == 5

    def test_each_record_has_unique_id(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import log_decision

        log_path = self._configure(tmp_path)

        for _ in range(3):
            log_decision(
                agent="MyAgent",
                decision_type="tool_selection",
                inputs={},
                output={},
            )

        records = self._read_records(log_path)
        ids = [r["id"] for r in records]
        assert len(set(ids)) == 3

    def test_all_decision_types_accepted(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import (
            DECISION_TYPE_AUTONOMY_TIER,
            DECISION_TYPE_DECOMPOSITION,
            DECISION_TYPE_ERROR_HANDLING,
            DECISION_TYPE_ROUTING,
            DECISION_TYPE_TOOL_SELECTION,
            log_decision,
        )

        log_path = self._configure(tmp_path)

        for dt in [
            DECISION_TYPE_TOOL_SELECTION,
            DECISION_TYPE_ROUTING,
            DECISION_TYPE_DECOMPOSITION,
            DECISION_TYPE_AUTONOMY_TIER,
            DECISION_TYPE_ERROR_HANDLING,
        ]:
            log_decision(agent="MyAgent", decision_type=dt, inputs={}, output={})

        records = self._read_records(log_path)
        assert len(records) == 5


# ─── Constants exported from telemetry package ──────────────────────────────


class TestDecisionTypeConstants:
    def test_constants_exported_from_telemetry(self) -> None:
        from agent_framework.telemetry import (
            DECISION_TYPE_AUTONOMY_TIER,
            DECISION_TYPE_DECOMPOSITION,
            DECISION_TYPE_ERROR_HANDLING,
            DECISION_TYPE_ROUTING,
            DECISION_TYPE_TOOL_SELECTION,
        )

        assert DECISION_TYPE_TOOL_SELECTION == "tool_selection"
        assert DECISION_TYPE_ROUTING == "routing"
        assert DECISION_TYPE_DECOMPOSITION == "decomposition"
        assert DECISION_TYPE_AUTONOMY_TIER == "autonomy_tier"
        assert DECISION_TYPE_ERROR_HANDLING == "error_handling"

    def test_constants_exported_from_top_level_package(self) -> None:
        from agent_framework import (
            DECISION_TYPE_AUTONOMY_TIER,
            DECISION_TYPE_DECOMPOSITION,
            DECISION_TYPE_ERROR_HANDLING,
            DECISION_TYPE_ROUTING,
            DECISION_TYPE_TOOL_SELECTION,
            configure_decision_logger,
            get_decision_logger,
            log_decision,
            reset_decision_logger,
        )

        assert callable(configure_decision_logger)
        assert callable(log_decision)
        assert callable(get_decision_logger)
        assert callable(reset_decision_logger)
        assert DECISION_TYPE_TOOL_SELECTION == "tool_selection"
        assert DECISION_TYPE_ROUTING == "routing"
        assert DECISION_TYPE_DECOMPOSITION == "decomposition"
        assert DECISION_TYPE_AUTONOMY_TIER == "autonomy_tier"
        assert DECISION_TYPE_ERROR_HANDLING == "error_handling"


# ─── get_decision_logger / reset_decision_logger ────────────────────────────


class TestGetAndResetDecisionLogger:
    def test_get_returns_none_before_configure(self) -> None:
        from agent_framework.telemetry.decision_logger import get_decision_logger

        assert get_decision_logger() is None

    def test_get_returns_logger_after_configure(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import (
            configure_decision_logger,
            get_decision_logger,
        )

        log_path = tmp_path / "decisions.jsonl"
        with patch.object(dl, "ALLOWED_LOG_DIRS", (str(tmp_path),)):
            configure_decision_logger(str(log_path))

        assert get_decision_logger() is not None

    def test_reset_clears_logger(self, tmp_path: Path) -> None:
        from agent_framework.telemetry.decision_logger import (
            configure_decision_logger,
            get_decision_logger,
            reset_decision_logger,
        )

        log_path = tmp_path / "decisions.jsonl"
        with patch.object(dl, "ALLOWED_LOG_DIRS", (str(tmp_path),)):
            configure_decision_logger(str(log_path))

        assert get_decision_logger() is not None
        reset_decision_logger()
        assert get_decision_logger() is None
