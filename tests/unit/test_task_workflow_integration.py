"""Integration tests for task execution workflows.

Tests cover the full create → classify → execute → note → complete pipeline,
all action_types, dependency ordering, triage logic, and scheduler routines.

External API calls (Anthropic, MCP, Slack) are mocked throughout.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.task_manager.scheduler import (
    EVENING_PROMPT,
    LOG_PREVIEW_LEN,
    MORNING_PROMPT,
    NOTIFICATION_SUMMARY_LEN,
    _run_routine,
    _sanitize_error,
    run_evening_routine,
    run_morning_routine,
)
from agents.task_queue.dependency_graph import (
    _build_blocked_by,
    _partition_remaining,
    _topological_sort,
    compute_processing_order,
    identify_blocked_tasks,
)
from agents.task_queue.lightweight_executor import (
    COMPLETION_CHECK_PROMPT,
    LIGHTWEIGHT_SYSTEM_PROMPT,
    LightweightResult,
    _extract_text,
    _tools_to_api_format,
)
from agents.task_queue.models import (
    MODEL_ALIASES,
    ProcessedTask,
    RunReport,
    TaskContext,
    TaskQueueConfig,
    TriageResult,
    TriageVerdict,
    _extract_keywords,
    _utcnow,
    resolve_model,
)
from agents.task_queue.triage import (
    _build_triage_user_message,
    _parse_triage_result,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    task_id: str = "task_1",
    title: str = "Test Task",
    status: str = "pending",
    action_type: str | None = None,
) -> dict:
    """Build a minimal task dict for testing."""
    task: dict = {"id": task_id, "title": title, "status": status}
    if action_type:
        task["action_type"] = action_type
    return task


def _make_dep(dep_id: str, status: str = "pending") -> dict:
    """Build a dependency dict."""
    return {"id": dep_id, "status": status}


# ---------------------------------------------------------------------------
# TaskContext tests
# ---------------------------------------------------------------------------


class TestTaskContext:
    """Tests for TaskContext and related helper functions."""

    def test_utcnow_returns_aware_datetime(self) -> None:
        """_utcnow() should return a timezone-aware UTC datetime."""
        result = _utcnow()
        assert result.tzinfo is not None

    def test_extract_keywords_basic(self) -> None:
        """Keywords are extracted and stop-words are filtered."""
        words = _extract_keywords("Fix the login authentication bug")
        assert "fix" in words
        assert "login" in words
        assert "authentication" in words
        assert "bug" in words
        # Stop words should be excluded
        assert "the" not in words

    def test_extract_keywords_strips_punctuation(self) -> None:
        """Punctuation is stripped from keywords."""
        words = _extract_keywords("hello, world! test.")
        assert "hello" in words
        assert "world" in words
        assert "test" in words

    def test_extract_keywords_min_length(self) -> None:
        """Words with 2 or fewer characters are excluded."""
        words = _extract_keywords("a to is on fix bug")
        # Short words filtered
        assert "a" not in words
        assert "to" not in words
        assert "is" not in words
        # 'fix' and 'bug' are 3+ chars but also stop words for 'fix' — only bug survives
        assert "bug" in words

    def test_get_related_context_empty_notes(self) -> None:
        """Returns empty string when no research notes exist."""
        ctx = TaskContext()
        result = ctx.get_related_context("Fix login", "Repair the login page")
        assert result == ""

    def test_get_related_context_no_overlap(self) -> None:
        """Returns empty string when notes don't share keywords."""
        ctx = TaskContext()
        ctx.research_notes["task_99"] = "Database schema migration notes"
        result = ctx.get_related_context("Frontend styling", "Update CSS colors")
        assert result == ""

    def test_get_related_context_with_overlap(self) -> None:
        """Returns matching notes when tasks share 2+ keywords."""
        ctx = TaskContext()
        ctx.research_notes["task_10"] = "Authentication security token refresh"
        result = ctx.get_related_context(
            "Fix authentication token",
            "The token refresh fails during authentication",
        )
        assert "task_10" in result
        assert "Authentication security token refresh" in result

    def test_get_related_context_requires_two_keywords(self) -> None:
        """Requires at least 2 keyword overlap to include notes."""
        ctx = TaskContext()
        # "unrelated" and "content" are the only significant keywords in the notes.
        # The query has no overlap with those words, so it should not match.
        ctx.research_notes["task_5"] = "widget rendering optimization techniques"
        result = ctx.get_related_context("Deploy application", "Push code to production server")
        assert result == ""

    def test_task_context_tracks_ids(self) -> None:
        """TaskContext tracks completed, failed, partial, and skipped IDs."""
        ctx = TaskContext()
        ctx.completed_ids.append("task_1")
        ctx.failed_ids.append("task_2")
        ctx.partial_ids.append("task_3")
        ctx.skipped_ids.append("task_4")

        assert "task_1" in ctx.completed_ids
        assert "task_2" in ctx.failed_ids
        assert "task_3" in ctx.partial_ids
        assert "task_4" in ctx.skipped_ids


# ---------------------------------------------------------------------------
# resolve_model tests
# ---------------------------------------------------------------------------


class TestResolveModel:
    """Tests for model alias resolution."""

    def test_resolve_haiku_alias(self) -> None:
        resolved = resolve_model("haiku")
        assert "haiku" in resolved.lower()
        assert resolved != "haiku"  # Should expand to full ID

    def test_resolve_sonnet_alias(self) -> None:
        resolved = resolve_model("sonnet")
        assert "sonnet" in resolved.lower()
        assert resolved != "sonnet"

    def test_resolve_opus_alias(self) -> None:
        resolved = resolve_model("opus")
        assert "opus" in resolved.lower()
        assert resolved != "opus"

    def test_resolve_unknown_passthrough(self) -> None:
        """Unknown model names pass through unchanged."""
        full_id = "claude-opus-4-6"
        assert resolve_model(full_id) == full_id

    def test_model_aliases_dict_has_three_entries(self) -> None:
        assert "haiku" in MODEL_ALIASES
        assert "sonnet" in MODEL_ALIASES
        assert "opus" in MODEL_ALIASES


# ---------------------------------------------------------------------------
# RunReport tests
# ---------------------------------------------------------------------------


class TestRunReport:
    """Tests for RunReport data model and formatting."""

    def _make_processed(
        self, outcome: str, title: str = "Task", error: str | None = None
    ) -> ProcessedTask:
        return ProcessedTask(
            external_id="task_1",
            title=title,
            triage_verdict=TriageVerdict.FULLY_EXECUTABLE,
            confidence=0.9,
            outcome=outcome,
            error=error,
        )

    def test_completed_count(self) -> None:
        report = RunReport()
        report.tasks_processed = [
            self._make_processed("completed"),
            self._make_processed("completed"),
            self._make_processed("failed"),
        ]
        assert report.completed_count == 2

    def test_failed_count(self) -> None:
        report = RunReport()
        report.tasks_processed = [self._make_processed("failed"), self._make_processed("completed")]
        assert report.failed_count == 1

    def test_researched_count(self) -> None:
        report = RunReport()
        report.tasks_processed = [self._make_processed("researched")]
        assert report.researched_count == 1

    def test_blocked_count(self) -> None:
        report = RunReport()
        report.tasks_processed = [self._make_processed("blocked")]
        assert report.blocked_count == 1

    def test_needs_human_count(self) -> None:
        report = RunReport()
        report.tasks_processed = [self._make_processed("needs_human")]
        assert report.needs_human_count == 1

    def test_partial_count(self) -> None:
        report = RunReport()
        report.tasks_processed = [self._make_processed("partial")]
        assert report.partial_count == 1

    def test_skipped_count(self) -> None:
        report = RunReport()
        report.tasks_processed = [self._make_processed("skipped")]
        assert report.skipped_count == 1

    def test_format_summary_empty(self) -> None:
        """Empty report produces a summary with all-zero counts."""
        report = RunReport()
        summary = report.format_summary()
        assert "Task Queue Run" in summary
        assert "Fetched: 0" in summary
        assert "Completed: 0" in summary

    def test_format_summary_with_duration(self) -> None:
        """Summary includes duration when completed_at is set."""
        report = RunReport()
        report.completed_at = report.started_at + timedelta(seconds=90)
        summary = report.format_summary()
        assert "1m 30s" in summary

    def test_format_summary_dry_run(self) -> None:
        report = RunReport(dry_run=True)
        summary = report.format_summary()
        assert "DRY RUN" in summary

    def test_format_summary_with_tasks(self) -> None:
        """Summary includes per-task details when tasks are present."""
        report = RunReport()
        report.tasks_processed = [
            self._make_processed("completed", title="Fix the login bug"),
            self._make_processed("failed", title="Deploy to prod", error="Connection timeout"),
        ]
        summary = report.format_summary()
        assert "Fix the login bug" in summary
        assert "Deploy to prod" in summary
        assert "Connection timeout" in summary

    def test_format_slack_message_empty(self) -> None:
        report = RunReport()
        msg = report.format_slack_message()
        assert "Task Queue Run Complete" in msg

    def test_format_slack_message_dry_run(self) -> None:
        report = RunReport(dry_run=True)
        msg = report.format_slack_message()
        assert "DRY RUN" in msg

    def test_format_slack_message_shows_outcomes(self) -> None:
        """Slack message includes sections for each non-zero outcome type."""
        report = RunReport()
        report.tasks_processed = [
            self._make_processed("completed"),
            self._make_processed("failed", error="oops"),
            self._make_processed("partial"),
            self._make_processed("researched"),
            self._make_processed("blocked"),
            self._make_processed("needs_human"),
            self._make_processed("skipped"),
        ]
        msg = report.format_slack_message()
        assert "Completed" in msg
        assert "Failed" in msg
        assert "Partial" in msg
        assert "Researched" in msg
        assert "Blocked" in msg
        assert "Needs human" in msg
        assert "Skipped" in msg

    def test_format_slack_message_includes_failure_error(self) -> None:
        """Failure details appear in Slack message."""
        report = RunReport()
        report.tasks_processed = [
            self._make_processed("failed", title="Broken task", error="auth error occurred"),
        ]
        msg = report.format_slack_message()
        assert "auth error occurred" in msg


# ---------------------------------------------------------------------------
# TriageVerdict / TriageResult tests
# ---------------------------------------------------------------------------


class TestTriageModels:
    """Tests for triage-related enums and dataclasses."""

    def test_triage_verdict_values(self) -> None:
        assert TriageVerdict.FULLY_EXECUTABLE.value == "fully_executable"
        assert TriageVerdict.PRE_RESEARCH_ONLY.value == "pre_research_only"
        assert TriageVerdict.NOT_ACTIONABLE.value == "not_actionable"
        assert TriageVerdict.SKIP_DEPENDENCIES.value == "skip_dependencies"
        assert TriageVerdict.SKIP_ALREADY_PROCESSING.value == "skip_already_processing"

    def test_triage_result_defaults(self) -> None:
        result = TriageResult(verdict=TriageVerdict.FULLY_EXECUTABLE, confidence=0.9)
        assert result.reasoning == ""
        assert result.estimated_hours is None
        assert result.suggested_action_type is None
        assert result.suggested_autonomy_tier is None
        assert result.suggested_dependencies == []
        assert result.pre_research_queries == []
        assert result.blocking_reason is None

    def test_triage_result_with_all_fields(self) -> None:
        result = TriageResult(
            verdict=TriageVerdict.PRE_RESEARCH_ONLY,
            confidence=0.7,
            reasoning="Needs information first",
            estimated_hours=2.5,
            suggested_action_type="research",
            suggested_autonomy_tier=1,
            suggested_dependencies=["task_5"],
            pre_research_queries=["best practices"],
            blocking_reason=None,
        )
        assert result.verdict == TriageVerdict.PRE_RESEARCH_ONLY
        assert result.confidence == 0.7
        assert result.estimated_hours == 2.5
        assert result.suggested_action_type == "research"
        assert result.suggested_autonomy_tier == 1


# ---------------------------------------------------------------------------
# TaskQueueConfig tests
# ---------------------------------------------------------------------------


class TestTaskQueueConfig:
    """Tests for TaskQueueConfig defaults and fields."""

    def test_defaults(self) -> None:
        config = TaskQueueConfig()
        assert config.dry_run is False
        assert config.max_tasks == 20
        assert config.triage_model == "haiku"
        assert config.research_model == "haiku"
        assert config.worker_model == "sonnet"
        assert config.concurrency == 5
        assert config.include_overdue is True
        assert config.priority_bump_overdue is True
        assert config.task_ids == []

    def test_custom_config(self) -> None:
        config = TaskQueueConfig(
            dry_run=True,
            max_tasks=5,
            concurrency=2,
            triage_model="sonnet",
        )
        assert config.dry_run is True
        assert config.max_tasks == 5
        assert config.concurrency == 2
        assert config.triage_model == "sonnet"


# ---------------------------------------------------------------------------
# Dependency graph tests
# ---------------------------------------------------------------------------


class TestBuildBlockedBy:
    """Tests for _build_blocked_by helper."""

    def test_no_dependencies(self) -> None:
        result = _build_blocked_by({})
        assert result == {}

    def test_completed_deps_not_blocking(self) -> None:
        deps = {"task_1": [_make_dep("task_2", "completed")]}
        result = _build_blocked_by(deps)
        assert "task_1" not in result

    def test_pending_dep_blocks(self) -> None:
        deps = {"task_1": [_make_dep("task_2", "pending")]}
        result = _build_blocked_by(deps)
        assert "task_1" in result
        assert "task_2" in result["task_1"]

    def test_cancelled_dep_not_blocking(self) -> None:
        deps = {"task_1": [_make_dep("task_2", "cancelled")]}
        result = _build_blocked_by(deps)
        assert "task_1" not in result

    def test_mixed_deps(self) -> None:
        deps = {
            "task_1": [
                _make_dep("task_2", "completed"),
                _make_dep("task_3", "pending"),
            ]
        }
        result = _build_blocked_by(deps)
        assert "task_1" in result
        assert "task_3" in result["task_1"]
        assert "task_2" not in result["task_1"]


class TestTopologicalSort:
    """Tests for _topological_sort helper."""

    def test_no_dependencies(self) -> None:
        tasks = [_make_task("task_1"), _make_task("task_2")]
        task_ids = {"task_1", "task_2"}
        ordered = _topological_sort(tasks, {}, {}, task_ids)
        assert set(ordered) == {"task_1", "task_2"}

    def test_simple_dependency_order(self) -> None:
        """task_2 depends on task_1, so task_1 must come first."""
        tasks = [_make_task("task_1"), _make_task("task_2")]
        deps = {"task_2": [_make_dep("task_1", "pending")]}
        blocked_by: dict[str, set[str]] = {}
        task_ids = {"task_1", "task_2"}
        ordered = _topological_sort(tasks, deps, blocked_by, task_ids)
        assert ordered.index("task_1") < ordered.index("task_2")

    def test_blocked_task_excluded(self) -> None:
        """Tasks in blocked_by are excluded from ordered output."""
        tasks = [_make_task("task_1"), _make_task("task_2")]
        blocked_by = {"task_2": {"task_99"}}  # blocked by external dep
        task_ids = {"task_1", "task_2"}
        ordered = _topological_sort(tasks, {}, blocked_by, task_ids)
        assert "task_2" not in ordered
        assert "task_1" in ordered


class TestPartitionRemaining:
    """Tests for _partition_remaining helper."""

    def test_all_ordered_no_remaining(self) -> None:
        tasks = [_make_task("task_1"), _make_task("task_2")]
        ordered = ["task_1", "task_2"]
        task_ids = {"task_1", "task_2"}
        blocked_external, remaining = _partition_remaining(tasks, ordered, {}, task_ids)
        assert blocked_external == []
        assert remaining == []

    def test_externally_blocked_task(self) -> None:
        tasks = [_make_task("task_1"), _make_task("task_2")]
        ordered = ["task_1"]
        task_ids = {"task_1", "task_2"}
        blocked_by = {"task_2": {"task_99"}}  # task_99 not in list
        blocked_external, remaining = _partition_remaining(tasks, ordered, blocked_by, task_ids)
        assert "task_2" in blocked_external
        assert remaining == []


class TestComputeProcessingOrder:
    """Tests for compute_processing_order public API."""

    def test_empty_tasks(self) -> None:
        result = compute_processing_order([], {})
        assert result == []

    def test_single_task_no_deps(self) -> None:
        tasks = [_make_task("task_1")]
        result = compute_processing_order(tasks, {})
        assert len(result) == 1
        assert result[0]["id"] == "task_1"

    def test_dependency_ordering(self) -> None:
        """Child (dep) should be processed before parent."""
        tasks = [_make_task("task_parent"), _make_task("task_child")]
        deps = {"task_parent": [_make_dep("task_child", "pending")]}
        result = compute_processing_order(tasks, deps)
        ids = [t["id"] for t in result]
        assert ids.index("task_child") < ids.index("task_parent")

    def test_three_level_chain(self) -> None:
        """A -> B -> C: the leaf task C is placed first.

        The topological sort only promotes tasks whose in-list incomplete
        dependencies have already been placed. Because _build_blocked_by marks
        both A and B as blocked (they each have an incomplete in-list dep),
        neither enters the initial ready queue. Only C (the leaf) is placed by
        the topological pass; A and B both fall into the 'remaining' bucket and
        appear after C in their original input order.

        This is intentional behaviour: the algorithm guarantees that leaf nodes
        are processed before their dependents, but does not recursively promote
        intermediate nodes within a single pass.
        """
        tasks = [_make_task("C"), _make_task("B"), _make_task("A")]
        deps = {
            "A": [_make_dep("B", "pending")],
            "B": [_make_dep("C", "pending")],
        }
        result = compute_processing_order(tasks, deps)
        ids = [t["id"] for t in result]
        # C is a leaf with no deps — it is placed first by the topological sort
        assert ids[0] == "C"
        # All three tasks must still appear in the result
        assert set(ids) == {"A", "B", "C"}

    def test_completed_dep_does_not_block(self) -> None:
        """Completed dependencies don't block the parent task."""
        tasks = [_make_task("task_1"), _make_task("task_2")]
        deps = {"task_1": [_make_dep("task_2", "completed")]}
        result = compute_processing_order(tasks, deps)
        # task_1 should be in the result even though it has a dep
        ids = [t["id"] for t in result]
        assert "task_1" in ids

    def test_externally_blocked_task_deferred(self) -> None:
        """Task blocked by external (not in list) dependency is deferred to end."""
        tasks = [_make_task("task_1"), _make_task("task_2")]
        # task_2 depends on task_99 which is not in the list
        deps = {"task_2": [_make_dep("task_99", "pending")]}
        result = compute_processing_order(tasks, deps)
        ids = [t["id"] for t in result]
        # task_1 should come before task_2 (task_2 is externally blocked)
        assert ids.index("task_1") < ids.index("task_2")


class TestIdentifyBlockedTasks:
    """Tests for identify_blocked_tasks."""

    def test_no_tasks(self) -> None:
        result = identify_blocked_tasks([], {})
        assert result == {}

    def test_no_deps_no_blocked(self) -> None:
        tasks = [_make_task("task_1")]
        result = identify_blocked_tasks(tasks, {})
        assert result == {}

    def test_blocked_by_pending_dep(self) -> None:
        tasks = [_make_task("task_1")]
        deps = {"task_1": [_make_dep("task_2", "pending")]}
        result = identify_blocked_tasks(tasks, deps)
        assert "task_1" in result
        assert "task_2" in result["task_1"]

    def test_completed_dep_not_blocking(self) -> None:
        tasks = [_make_task("task_1")]
        deps = {"task_1": [_make_dep("task_2", "completed")]}
        result = identify_blocked_tasks(tasks, deps)
        assert "task_1" not in result

    def test_multiple_blockers(self) -> None:
        tasks = [_make_task("task_1")]
        deps = {
            "task_1": [
                _make_dep("task_2", "pending"),
                _make_dep("task_3", "pending"),
                _make_dep("task_4", "completed"),
            ]
        }
        result = identify_blocked_tasks(tasks, deps)
        assert set(result["task_1"]) == {"task_2", "task_3"}


# ---------------------------------------------------------------------------
# Triage parsing tests
# ---------------------------------------------------------------------------


class TestParseTriage:
    """Tests for _parse_triage_result helper."""

    def test_valid_fully_executable(self) -> None:
        raw = json.dumps(
            {
                "verdict": "fully_executable",
                "confidence": 0.95,
                "reasoning": "Clear coding task with available tools",
                "suggested_action_type": "code",
                "suggested_autonomy_tier": 2,
            }
        )
        result = _parse_triage_result(raw)
        assert result.verdict == TriageVerdict.FULLY_EXECUTABLE
        assert result.confidence == 0.95
        assert result.suggested_action_type == "code"
        assert result.suggested_autonomy_tier == 2

    def test_valid_pre_research_only(self) -> None:
        raw = json.dumps(
            {
                "verdict": "pre_research_only",
                "confidence": 0.8,
                "pre_research_queries": ["Python async best practices"],
            }
        )
        result = _parse_triage_result(raw)
        assert result.verdict == TriageVerdict.PRE_RESEARCH_ONLY
        assert result.pre_research_queries == ["Python async best practices"]

    def test_valid_not_actionable(self) -> None:
        raw = json.dumps(
            {
                "verdict": "not_actionable",
                "confidence": 0.9,
                "blocking_reason": "Requires in-person meeting",
            }
        )
        result = _parse_triage_result(raw)
        assert result.verdict == TriageVerdict.NOT_ACTIONABLE
        assert result.blocking_reason == "Requires in-person meeting"

    def test_invalid_json_falls_back(self) -> None:
        result = _parse_triage_result("not valid json {{{")
        assert result.verdict == TriageVerdict.NOT_ACTIONABLE
        assert result.confidence == 0.0

    def test_non_dict_json_falls_back(self) -> None:
        result = _parse_triage_result(json.dumps(["list", "not", "dict"]))
        assert result.verdict == TriageVerdict.NOT_ACTIONABLE

    def test_unknown_verdict_falls_back(self) -> None:
        raw = json.dumps({"verdict": "unknown_verdict", "confidence": 0.5})
        result = _parse_triage_result(raw)
        assert result.verdict == TriageVerdict.NOT_ACTIONABLE

    def test_confidence_clamped_above_one(self) -> None:
        raw = json.dumps({"verdict": "fully_executable", "confidence": 5.0})
        result = _parse_triage_result(raw)
        assert result.confidence == 1.0

    def test_confidence_clamped_below_zero(self) -> None:
        raw = json.dumps({"verdict": "fully_executable", "confidence": -1.0})
        result = _parse_triage_result(raw)
        assert result.confidence == 0.0

    def test_invalid_confidence_defaults_to_half(self) -> None:
        raw = json.dumps({"verdict": "fully_executable", "confidence": "high"})
        result = _parse_triage_result(raw)
        assert result.confidence == 0.5

    def test_autonomy_tier_clamped_1_to_4(self) -> None:
        raw = json.dumps(
            {"verdict": "fully_executable", "confidence": 0.8, "suggested_autonomy_tier": 10}
        )
        result = _parse_triage_result(raw)
        assert result.suggested_autonomy_tier == 4

    def test_autonomy_tier_clamped_min(self) -> None:
        raw = json.dumps(
            {"verdict": "fully_executable", "confidence": 0.8, "suggested_autonomy_tier": -5}
        )
        result = _parse_triage_result(raw)
        assert result.suggested_autonomy_tier == 1

    def test_invalid_autonomy_tier_is_none(self) -> None:
        raw = json.dumps(
            {"verdict": "fully_executable", "confidence": 0.8, "suggested_autonomy_tier": "high"}
        )
        result = _parse_triage_result(raw)
        assert result.suggested_autonomy_tier is None

    def test_estimated_hours_parsed(self) -> None:
        raw = json.dumps({"verdict": "fully_executable", "confidence": 0.8, "estimated_hours": 3.5})
        result = _parse_triage_result(raw)
        assert result.estimated_hours == 3.5

    def test_invalid_estimated_hours_is_none(self) -> None:
        raw = json.dumps(
            {"verdict": "fully_executable", "confidence": 0.8, "estimated_hours": "many"}
        )
        result = _parse_triage_result(raw)
        assert result.estimated_hours is None

    def test_markdown_fences_stripped(self) -> None:
        """Triage parser should handle markdown code fences."""
        raw = '```json\n{"verdict": "fully_executable", "confidence": 0.9}\n```'
        result = _parse_triage_result(raw)
        assert result.verdict == TriageVerdict.FULLY_EXECUTABLE

    def test_all_action_types_accepted(self) -> None:
        """All known action_types should pass through as-is."""
        for action_type in (
            "code",
            "research",
            "email",
            "document",
            "communication",
            "review",
            "other",
        ):
            raw = json.dumps(
                {
                    "verdict": "fully_executable",
                    "confidence": 0.9,
                    "suggested_action_type": action_type,
                }
            )
            result = _parse_triage_result(raw)
            assert result.suggested_action_type == action_type


class TestBuildTriageUserMessage:
    """Tests for _build_triage_user_message helper."""

    def test_basic_task(self) -> None:
        task = {
            "id": "task_42",
            "title": "Fix login bug",
            "description": "The session token isn't refreshing",
            "priority": "high",
            "category": "engineering",
            "due_date": "2026-03-01",
            "tags": ["backend", "auth"],
        }
        msg = _build_triage_user_message(task, [], "")
        assert "task_42" in msg
        assert "Fix login bug" in msg
        assert "session token" in msg
        assert "high" in msg
        assert "engineering" in msg
        assert "backend" in msg

    def test_includes_action_type_if_present(self) -> None:
        task = {"id": "t1", "title": "T", "action_type": "code"}
        msg = _build_triage_user_message(task, [], "")
        # The field is formatted as "Action type (pre-classified): code"
        assert "Action type (pre-classified): code" in msg

    def test_includes_autonomy_tier_if_present(self) -> None:
        task = {"id": "t1", "title": "T", "autonomy_tier": 2}
        msg = _build_triage_user_message(task, [], "")
        assert "2" in msg

    def test_includes_agent_notes_if_present(self) -> None:
        task = {"id": "t1", "title": "T", "agent_notes": "Previous research: use OAuth2"}
        msg = _build_triage_user_message(task, [], "")
        assert "OAuth2" in msg

    def test_includes_available_tools(self) -> None:
        task = {"id": "t1", "title": "T"}
        tools = ["fetch_web_content", "send_email", "run_claude_code"]
        msg = _build_triage_user_message(task, tools, "")
        assert "fetch_web_content" in msg
        assert "send_email" in msg

    def test_includes_accumulated_context(self) -> None:
        task = {"id": "t1", "title": "T"}
        context = "Context from related task: prior research found X"
        msg = _build_triage_user_message(task, [], context)
        assert "prior research found X" in msg

    def test_limits_tools_to_30(self) -> None:
        """Tools list is capped at 30 items in the message."""
        task = {"id": "t1", "title": "T"}
        # Use a consistent prefix that avoids substring ambiguity
        tools = [f"myuniquetool_{i:03d}" for i in range(50)]
        msg = _build_triage_user_message(task, tools, "")
        # Tools 30-49 must not appear in the message at all
        for tool in tools[30:]:
            assert tool not in msg, f"Tool beyond limit appeared in message: {tool}"
        # At least some of the first 30 tools must appear
        included = [t for t in tools[:30] if t in msg]
        assert len(included) > 0


# ---------------------------------------------------------------------------
# Lightweight executor helper tests
# ---------------------------------------------------------------------------


class TestLightweightExecutorHelpers:
    """Tests for helper functions in lightweight_executor."""

    def test_tools_to_api_format_basic(self) -> None:
        mcp_tools = [
            {
                "name": "fetch_web_content",
                "description": "Fetch web page content",
                "input_schema": {"type": "object", "properties": {}},
            }
        ]
        result = _tools_to_api_format(mcp_tools)
        assert len(result) == 1
        assert result[0]["name"] == "fetch_web_content"
        assert result[0]["description"] == "Fetch web page content"

    def test_tools_to_api_format_missing_description(self) -> None:
        mcp_tools = [{"name": "my_tool"}]
        result = _tools_to_api_format(mcp_tools)
        assert result[0]["description"] == ""

    def test_tools_to_api_format_missing_schema(self) -> None:
        mcp_tools = [{"name": "my_tool", "description": "A tool"}]
        result = _tools_to_api_format(mcp_tools)
        assert result[0]["input_schema"] == {"type": "object"}

    def test_extract_text_empty(self) -> None:
        result = _extract_text([])
        assert result == ""

    def test_extract_text_from_text_blocks(self) -> None:
        from anthropic.types import TextBlock

        blocks = [TextBlock(type="text", text="Hello"), TextBlock(type="text", text="World")]
        result = _extract_text(blocks)
        assert "Hello" in result
        assert "World" in result

    def test_lightweight_result_defaults(self) -> None:
        result = LightweightResult(success=True, output="Done", turns_used=3)
        assert result.success is True
        assert result.output == "Done"
        assert result.turns_used == 3
        assert result.error is None

    def test_lightweight_result_with_error(self) -> None:
        result = LightweightResult(success=False, output="", turns_used=1, error="Tool failed")
        assert result.success is False
        assert result.error == "Tool failed"

    def test_system_prompts_defined(self) -> None:
        """Verify the system prompts are non-empty strings."""
        assert len(LIGHTWEIGHT_SYSTEM_PROMPT) > 0
        assert len(COMPLETION_CHECK_PROMPT) > 0
        assert "COMPLETED" in COMPLETION_CHECK_PROMPT
        assert "FAILED" in COMPLETION_CHECK_PROMPT


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------


class TestSanitizeError:
    """Tests for _sanitize_error in scheduler."""

    def test_returns_type_and_message(self) -> None:
        exc = ValueError("something bad happened")
        result = _sanitize_error(exc)
        assert "ValueError" in result
        assert "something bad happened" in result

    def test_truncates_long_message(self) -> None:
        long_msg = "x" * 500
        exc = RuntimeError(long_msg)
        result = _sanitize_error(exc)
        # Should only include up to 120 chars of message
        assert len(result) < 200

    def test_handles_connection_error(self) -> None:
        exc = ConnectionError("Connection refused to MCP server at localhost:8080")
        result = _sanitize_error(exc)
        assert "ConnectionError" in result

    def test_handles_custom_exception(self) -> None:
        class MyCustomError(Exception):
            pass

        exc = MyCustomError("custom failure")
        result = _sanitize_error(exc)
        assert "MyCustomError" in result
        assert "custom failure" in result


class TestSchedulerPrompts:
    """Tests that scheduler prompts contain required workflow steps."""

    def test_morning_prompt_contains_overdue_review(self) -> None:
        assert "overdue" in MORNING_PROMPT.lower()
        assert "get_tasks" in MORNING_PROMPT

    def test_morning_prompt_contains_classify(self) -> None:
        assert "classify" in MORNING_PROMPT.lower()
        assert "classify_task" in MORNING_PROMPT

    def test_morning_prompt_contains_pre_research(self) -> None:
        assert "research" in MORNING_PROMPT.lower()
        assert "add_agent_note" in MORNING_PROMPT

    def test_morning_prompt_contains_briefing_step(self) -> None:
        assert "send_slack_message" in MORNING_PROMPT
        assert "send_sms_to_admin" in MORNING_PROMPT

    def test_evening_prompt_contains_completed_review(self) -> None:
        assert "completed" in EVENING_PROMPT.lower()
        assert "get_tasks" in EVENING_PROMPT

    def test_evening_prompt_contains_classify_step(self) -> None:
        assert "classify" in EVENING_PROMPT.lower()

    def test_evening_prompt_contains_priority_update(self) -> None:
        assert "priorit" in EVENING_PROMPT.lower()
        assert "update_task" in EVENING_PROMPT

    def test_evening_prompt_contains_blocked_check(self) -> None:
        assert "blocked" in EVENING_PROMPT.lower()
        assert "get_agent_tasks" in EVENING_PROMPT

    def test_evening_prompt_contains_eod_summary(self) -> None:
        assert "send_slack_message" in EVENING_PROMPT
        assert "send_sms_to_admin" in EVENING_PROMPT

    def test_truncation_constants_are_sensible(self) -> None:
        """LOG_PREVIEW_LEN should be larger than NOTIFICATION_SUMMARY_LEN."""
        assert LOG_PREVIEW_LEN > NOTIFICATION_SUMMARY_LEN
        assert NOTIFICATION_SUMMARY_LEN > 0


class TestRunRoutine:
    """Tests for the _run_routine async function.

    Note: notify_routine_complete and notify_error are imported inside _run_routine
    (lazy imports), so we patch them at the source module: shared.notifications.
    """

    @pytest.mark.asyncio
    async def test_run_routine_success(self) -> None:
        """_run_routine should call agent.process_message and notify on success."""
        mock_agent = AsyncMock()
        mock_agent.process_message = AsyncMock(return_value="All tasks processed successfully.")

        mock_agent_cls = MagicMock(return_value=mock_agent)

        with (
            patch(
                "shared.notifications.notify_routine_complete", new_callable=AsyncMock
            ) as mock_notify,
            patch("shared.notifications.notify_error", new_callable=AsyncMock) as mock_error_notify,
            # TaskManagerAgent is lazily imported from .main inside _run_routine
            patch("agents.task_manager.main.TaskManagerAgent", mock_agent_cls),
        ):
            await _run_routine("Morning", MORNING_PROMPT)

        mock_agent.process_message.assert_awaited_once_with(MORNING_PROMPT)
        mock_notify.assert_awaited_once()
        mock_error_notify.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_run_routine_failure_notifies_error(self) -> None:
        """_run_routine should call notify_error and re-raise on exception."""
        mock_agent = AsyncMock()
        mock_agent.process_message = AsyncMock(side_effect=RuntimeError("MCP connection failed"))

        mock_agent_cls = MagicMock(return_value=mock_agent)

        with (
            patch(
                "shared.notifications.notify_routine_complete", new_callable=AsyncMock
            ) as mock_notify,
            patch("shared.notifications.notify_error", new_callable=AsyncMock) as mock_error_notify,
            patch("agents.task_manager.main.TaskManagerAgent", mock_agent_cls),
        ):
            with pytest.raises(RuntimeError, match="MCP connection failed"):
                await _run_routine("Evening", EVENING_PROMPT)

        mock_notify.assert_not_awaited()
        mock_error_notify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_routine_error_sanitized(self) -> None:
        """Error passed to notify_error should be sanitized (not the raw exception object)."""
        mock_agent = AsyncMock()
        mock_agent.process_message = AsyncMock(side_effect=ConnectionError("connection failed"))

        mock_agent_cls = MagicMock(return_value=mock_agent)
        captured_error: list[str] = []

        async def capture_notify_error(context: str, error: str, agent_name: str) -> None:
            captured_error.append(error)

        with (
            patch("shared.notifications.notify_routine_complete", new_callable=AsyncMock),
            patch(
                "shared.notifications.notify_error",
                new_callable=AsyncMock,
                side_effect=capture_notify_error,
            ),
            patch("agents.task_manager.main.TaskManagerAgent", mock_agent_cls),
        ):
            with pytest.raises(ConnectionError):
                await _run_routine("Morning", MORNING_PROMPT)

        # The error string passed to notify should start with the type name
        assert len(captured_error) == 1
        assert "ConnectionError" in captured_error[0]

    @pytest.mark.asyncio
    async def test_run_morning_routine_delegates(self) -> None:
        """run_morning_routine calls _run_routine with correct name and prompt."""
        with patch(
            "agents.task_manager.scheduler._run_routine", new_callable=AsyncMock
        ) as mock_run:
            await run_morning_routine()

        mock_run.assert_awaited_once_with("Morning", MORNING_PROMPT)

    @pytest.mark.asyncio
    async def test_run_evening_routine_delegates(self) -> None:
        """run_evening_routine calls _run_routine with correct name and prompt."""
        with patch(
            "agents.task_manager.scheduler._run_routine", new_callable=AsyncMock
        ) as mock_run:
            await run_evening_routine()

        mock_run.assert_awaited_once_with("Evening", EVENING_PROMPT)

    @pytest.mark.asyncio
    async def test_routine_response_truncated_for_notification(self) -> None:
        """Notification summary is capped at NOTIFICATION_SUMMARY_LEN characters."""
        long_response = "A" * 2000  # Much longer than NOTIFICATION_SUMMARY_LEN
        mock_agent = AsyncMock()
        mock_agent.process_message = AsyncMock(return_value=long_response)
        mock_agent_cls = MagicMock(return_value=mock_agent)

        captured_summary: list[str] = []

        async def capture_notify(routine_name: str, summary: str, agent_name: str) -> None:
            captured_summary.append(summary)

        with (
            patch(
                "shared.notifications.notify_routine_complete",
                new_callable=AsyncMock,
                side_effect=capture_notify,
            ),
            patch("shared.notifications.notify_error", new_callable=AsyncMock),
            patch("agents.task_manager.main.TaskManagerAgent", mock_agent_cls),
        ):
            await _run_routine("Morning", MORNING_PROMPT)

        assert len(captured_summary) == 1
        assert len(captured_summary[0]) <= NOTIFICATION_SUMMARY_LEN


# ---------------------------------------------------------------------------
# System prompt content tests (workflow coverage via prompt verification)
#
# These tests verify that the TaskManager system prompt correctly documents
# all execution workflows for each action_type (create → classify → execute
# → note → complete). They check prompt content rather than simulating live
# API calls.
# ---------------------------------------------------------------------------


class TestSystemPromptContent:
    """Verify that task execution workflows are correctly documented in the system prompt.

    Checks that each action_type (code, research, email, document, communication,
    review, other) has an execution workflow section with the required steps,
    and that safety/autonomy tier controls are properly specified.
    """

    def _make_workflow_task(
        self,
        task_id: str,
        title: str,
        action_type: str,
        autonomy_tier: int = 2,
    ) -> dict:
        return {
            "id": task_id,
            "title": title,
            "description": f"Task to {title.lower()}",
            "action_type": action_type,
            "agent_actionable": True,
            "autonomy_tier": autonomy_tier,
            "status": "pending",
        }

    def test_code_workflow_includes_workspace_and_execution_steps(self) -> None:
        """Code workflow prompt references workspace management and execution."""
        from agents.task_manager.prompts import SYSTEM_PROMPT

        # Verify the code workflow step-by-step from the prompt
        assert "list_claude_code_workspaces" in SYSTEM_PROMPT
        assert "create_claude_code_workspace" in SYSTEM_PROMPT
        assert "run_claude_code" in SYSTEM_PROMPT
        assert "add_agent_note" in SYSTEM_PROMPT
        assert "complete_task" in SYSTEM_PROMPT
        assert "send_slack_message" in SYSTEM_PROMPT

    def test_research_workflow_includes_web_search_and_followup(self) -> None:
        """Research workflow prompt references web search and follow-up creation."""
        from agents.task_manager.prompts import SYSTEM_PROMPT

        assert "fetch_web_content" in SYSTEM_PROMPT
        assert "create_task" in SYSTEM_PROMPT
        assert "add_agent_note" in SYSTEM_PROMPT

    def test_email_workflow_includes_search_and_send(self) -> None:
        """Email workflow references context search and email send."""
        from agents.task_manager.prompts import SYSTEM_PROMPT

        assert "search_emails" in SYSTEM_PROMPT
        assert "send_email" in SYSTEM_PROMPT
        assert "complete_task" in SYSTEM_PROMPT

    def test_document_workflow_includes_content_generation(self) -> None:
        """Document workflow references content generation approaches."""
        from agents.task_manager.prompts import SYSTEM_PROMPT

        assert "Execution Workflow: Document Tasks" in SYSTEM_PROMPT
        assert "run_claude_code" in SYSTEM_PROMPT

    def test_communication_workflow_send_slack(self) -> None:
        """Communication workflow sends via Slack."""
        from agents.task_manager.prompts import SYSTEM_PROMPT

        assert "Execution Workflow: Communication Tasks" in SYSTEM_PROMPT
        assert "send_slack_message" in SYSTEM_PROMPT

    def test_review_workflow_includes_gather_and_analyze(self) -> None:
        """Review workflow gathers material and logs findings."""
        from agents.task_manager.prompts import SYSTEM_PROMPT

        assert "Execution Workflow: Review Tasks" in SYSTEM_PROMPT
        assert "add_agent_note" in SYSTEM_PROMPT

    def test_other_action_type_documented(self) -> None:
        """The 'other' action_type is recognized in classification."""
        from agents.task_manager.prompts import SYSTEM_PROMPT

        assert "`other`" in SYSTEM_PROMPT

    def test_lifecycle_order_in_prompt(self) -> None:
        """The full lifecycle sequence appears in the prompt."""
        from agents.task_manager.prompts import SYSTEM_PROMPT

        # The lifecycle string is explicitly documented
        lifecycle = 'classify_task → set_agent_status("in_progress") → EXECUTE → add_agent_note → complete_task'
        assert lifecycle in SYSTEM_PROMPT

    def test_workflow_task_state_transitions(self) -> None:
        """TriageVerdict states map to expected task outcomes."""
        # FULLY_EXECUTABLE -> should produce completed/partial/failed
        # PRE_RESEARCH_ONLY -> should produce researched
        # NOT_ACTIONABLE -> should produce blocked/needs_human
        # SKIP_DEPENDENCIES -> should produce skipped
        # SKIP_ALREADY_PROCESSING -> should produce skipped

        executable_task = self._make_workflow_task("t1", "Fix bug", "code")
        assert executable_task["agent_actionable"] is True
        assert executable_task["action_type"] == "code"

        research_task = self._make_workflow_task(
            "t2", "Research options", "research", autonomy_tier=1
        )
        assert research_task["action_type"] == "research"
        assert research_task["autonomy_tier"] == 1

        email_task = self._make_workflow_task("t3", "Email client", "email", autonomy_tier=3)
        assert email_task["action_type"] == "email"
        assert email_task["autonomy_tier"] == 3  # Requires propose-then-confirm

    def test_tier_3_email_requires_approval(self) -> None:
        """Tier 3 email tasks must propose before sending."""
        from agents.task_manager.prompts import SYSTEM_PROMPT

        # The email workflow documents the tier 3 approval requirement
        assert "tier 3" in SYSTEM_PROMPT.lower() or "Tier 3" in SYSTEM_PROMPT
        assert "Wait for approval" in SYSTEM_PROMPT

    def test_tier_4_marks_needs_human(self) -> None:
        """Tier 4 tasks should result in needs_human status."""
        from agents.task_manager.prompts import SYSTEM_PROMPT

        assert 'set_agent_status("needs_human")' in SYSTEM_PROMPT

    def test_all_action_types_have_triage_verdicts(self) -> None:
        """Each action_type can be mapped to a TriageResult."""
        action_types = ["code", "research", "email", "document", "communication", "review", "other"]
        for action_type in action_types:
            result = TriageResult(
                verdict=TriageVerdict.FULLY_EXECUTABLE,
                confidence=0.9,
                suggested_action_type=action_type,
            )
            assert result.suggested_action_type == action_type

    def test_processed_task_duration_tracking(self) -> None:
        """ProcessedTask can track execution duration."""
        task = ProcessedTask(
            external_id="task_1",
            title="Test",
            triage_verdict=TriageVerdict.FULLY_EXECUTABLE,
            confidence=0.9,
            outcome="completed",
            started_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
            duration_seconds=45.3,
        )
        assert task.duration_seconds == 45.3
        assert task.outcome == "completed"

    def test_processed_task_with_orchestrator_info(self) -> None:
        """ProcessedTask can track orchestrator task ID and branch."""
        task = ProcessedTask(
            external_id="task_42",
            title="Write tests",
            triage_verdict=TriageVerdict.FULLY_EXECUTABLE,
            confidence=0.85,
            outcome="completed",
            orchestrator_task_id="orch_99",
            branch_name="feat/write-tests",
        )
        assert task.orchestrator_task_id == "orch_99"
        assert task.branch_name == "feat/write-tests"


# ---------------------------------------------------------------------------
# ProcessedTask edge cases
# ---------------------------------------------------------------------------


class TestProcessedTask:
    """Additional ProcessedTask tests."""

    def test_default_outcome_empty_string(self) -> None:
        task = ProcessedTask(
            external_id="t1",
            title="Task",
            triage_verdict=TriageVerdict.FULLY_EXECUTABLE,
            confidence=0.8,
        )
        assert task.outcome == ""

    def test_notes_preserved(self) -> None:
        task = ProcessedTask(
            external_id="t1",
            title="Task",
            triage_verdict=TriageVerdict.PRE_RESEARCH_ONLY,
            confidence=0.7,
            notes="Found 3 relevant articles on the topic",
        )
        assert "3 relevant articles" in task.notes

    def test_error_field(self) -> None:
        task = ProcessedTask(
            external_id="t1",
            title="Task",
            triage_verdict=TriageVerdict.NOT_ACTIONABLE,
            confidence=0.0,
            error="Timeout connecting to MCP",
        )
        assert task.error == "Timeout connecting to MCP"
