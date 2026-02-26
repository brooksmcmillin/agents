"""Tests for the orchestrator state machine.

Covers:
- All FSM phase transitions (INGEST -> PLAN -> EXECUTE -> PUBLISH -> COMPLETE)
- TaskLimitExceeded exception
- asyncio lock behavior (re-entrancy guard)
- Notification callbacks (sync and async)
- Task approval/rejection flows
- Parent/subtask finalization
- Run loop behavior (max_tasks, consecutive error bail-out)
- Edge cases (empty queue, missing task, get_status_summary)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.orchestrator.models import (
    AutonomyTier,
    OrchestratorConfig,
    Phase,
    Task,
    TaskStatus,
)
from agents.orchestrator.state_machine import Orchestrator, TaskLimitExceeded

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(**overrides) -> OrchestratorConfig:
    """Create an OrchestratorConfig with decomposition disabled by default."""
    defaults = {"skip_decomposition": True, "max_total_tasks": 50}
    defaults.update(overrides)
    return OrchestratorConfig(**defaults)


def _task(**overrides) -> Task:
    """Create a Task with sensible defaults for testing."""
    defaults = {
        "title": "Test task",
        "description": "A short description",
        "autonomy_tier": AutonomyTier.AUTO_MERGE,
    }
    defaults.update(overrides)
    return Task(**defaults)


def _mock_worker_result(success: bool = True, output: str = "done", turns: int = 3) -> MagicMock:
    """Create a mock WorkerResult object."""
    result = MagicMock()
    result.success = success
    result.output = output
    result.turns_used = turns
    result.exit_code = 0 if success else 1
    result.error = None if success else "worker error"
    return result


# ---------------------------------------------------------------------------
# TaskLimitExceeded
# ---------------------------------------------------------------------------


class TestTaskLimitExceeded:
    """TaskLimitExceeded exception is raised when the task registry is full."""

    def test_add_task_at_limit_raises(self) -> None:
        orch = Orchestrator(config=_config(max_total_tasks=2))
        orch.add_task(_task(title="task-1"))
        orch.add_task(_task(title="task-2"))
        with pytest.raises(TaskLimitExceeded, match="Global task limit reached"):
            orch.add_task(_task(title="task-3"))

    def test_add_task_below_limit_succeeds(self) -> None:
        orch = Orchestrator(config=_config(max_total_tasks=5))
        for i in range(5):
            t = orch.add_task(_task(title=f"task-{i}"))
            assert t.title == f"task-{i}"

    def test_exception_message_includes_task_title(self) -> None:
        orch = Orchestrator(config=_config(max_total_tasks=1))
        orch.add_task(_task(title="first"))
        with pytest.raises(TaskLimitExceeded, match="Cannot add task: 'overflow'"):
            orch.add_task(_task(title="overflow"))


# ---------------------------------------------------------------------------
# add_task / get_task / get_subtasks
# ---------------------------------------------------------------------------


class TestTaskRegistry:
    """Basic task registration and lookup."""

    def test_add_task_registers_and_queues(self) -> None:
        orch = Orchestrator(config=_config())
        task = _task()
        returned = orch.add_task(task)
        assert returned is task
        assert task.id in orch.tasks
        assert task.id in orch.queue

    def test_add_non_pending_task_not_queued(self) -> None:
        orch = Orchestrator(config=_config())
        task = _task(status=TaskStatus.COMPLETED)
        orch.add_task(task)
        assert task.id in orch.tasks
        assert task.id not in orch.queue

    def test_get_task_returns_task(self) -> None:
        orch = Orchestrator(config=_config())
        task = _task()
        orch.add_task(task)
        assert orch.get_task(task.id) is task

    def test_get_task_returns_none_for_missing(self) -> None:
        orch = Orchestrator(config=_config())
        assert orch.get_task("nonexistent") is None

    def test_get_subtasks(self) -> None:
        orch = Orchestrator(config=_config())
        parent = _task(title="parent")
        orch.add_task(parent)
        child1 = _task(title="child-1", parent_id=parent.id)
        child2 = _task(title="child-2", parent_id=parent.id)
        orch.add_task(child1)
        orch.add_task(child2)
        subtasks = orch.get_subtasks(parent.id)
        assert len(subtasks) == 2
        assert {s.title for s in subtasks} == {"child-1", "child-2"}


# ---------------------------------------------------------------------------
# State transitions (full pipeline, mocking external I/O)
# ---------------------------------------------------------------------------


class TestStateTransitions:
    """Test the FSM phases through _process_task with mocked I/O."""

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_full_pipeline_auto_merge(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """AUTO_MERGE tier: INGEST -> PLAN -> EXECUTE -> COMPLETE (no publish)."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result(success=True)

        orch = Orchestrator(config=_config())
        task = _task(autonomy_tier=AutonomyTier.AUTO_MERGE)
        orch.add_task(task)

        result = await orch.step()
        assert result is task
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None
        assert orch.state.tasks_completed == 1
        assert orch.state.phase == Phase.COMPLETE

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_full_pipeline_propose_execute(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """PROPOSE_EXECUTE tier: completes and notifies human."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result(success=True)

        completed_tasks: list[Task] = []
        orch = Orchestrator(config=_config())
        orch.on_task_complete(lambda t: completed_tasks.append(t))

        task = _task(autonomy_tier=AutonomyTier.PROPOSE_EXECUTE)
        orch.add_task(task)

        result = await orch.step()
        assert result is task
        assert task.status == TaskStatus.COMPLETED
        assert orch.state.phase == Phase.COMPLETE
        assert len(completed_tasks) == 1

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_full_pipeline_propose_wait(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """PROPOSE_WAIT tier: enters HUMAN_GATE instead of completing."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result(success=True)

        human_tasks: list[Task] = []
        orch = Orchestrator(config=_config())
        orch.on_human_approval_needed(lambda t: human_tasks.append(t))

        task = _task(autonomy_tier=AutonomyTier.PROPOSE_WAIT)
        orch.add_task(task)

        result = await orch.step()
        assert result is task
        assert task.status == TaskStatus.AWAITING_HUMAN
        assert orch.state.phase == Phase.HUMAN_GATE
        assert len(human_tasks) == 1

    async def test_manual_only_skips_execution(self) -> None:
        """MANUAL_ONLY tier: goes straight from INGEST to HUMAN_GATE."""
        human_tasks: list[Task] = []
        orch = Orchestrator(config=_config())
        orch.on_human_approval_needed(lambda t: human_tasks.append(t))

        task = _task(autonomy_tier=AutonomyTier.MANUAL_ONLY)
        orch.add_task(task)

        result = await orch.step()
        assert result is task
        assert task.status == TaskStatus.AWAITING_HUMAN
        assert orch.state.phase == Phase.HUMAN_GATE
        assert len(human_tasks) == 1

    @patch("agents.orchestrator.state_machine.push_and_create_pr")
    @patch("agents.orchestrator.state_machine.get_workspace_diff")
    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_publish_phase_when_branch_and_workspace(
        self,
        mock_workspace: AsyncMock,
        mock_worker: AsyncMock,
        mock_diff: AsyncMock,
        mock_pr: AsyncMock,
    ) -> None:
        """PUBLISH phase triggers when task has both branch_name and workspace_name."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result(success=True)
        mock_diff.return_value = "+added line\n-removed line"
        mock_pr.return_value = "https://github.com/org/repo/pull/42"

        orch = Orchestrator(config=_config())
        task = _task(autonomy_tier=AutonomyTier.AUTO_MERGE)
        task.branch_name = "feat/test"
        orch.add_task(task)

        result = await orch.step()
        assert result is task
        assert task.pr_url == "https://github.com/org/repo/pull/42"
        assert task.status == TaskStatus.COMPLETED
        mock_diff.assert_called_once()
        mock_pr.assert_called_once()

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_worker_failure_sets_failed_state(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """Worker failure: task and orchestrator state go to FAILED."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result(success=False)

        failed_tasks: list[Task] = []
        orch = Orchestrator(config=_config())
        orch.on_task_failed(lambda t: failed_tasks.append(t))

        task = _task()
        orch.add_task(task)

        result = await orch.step()
        assert result is task
        assert task.status == TaskStatus.FAILED
        assert orch.state.tasks_failed == 1
        assert orch.state.phase == Phase.FAILED
        assert len(failed_tasks) == 1

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_execution_exception_sets_failed(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """Unhandled exception during execution still transitions to FAILED."""
        mock_workspace.side_effect = RuntimeError("workspace boom")

        orch = Orchestrator(config=_config())
        task = _task()
        orch.add_task(task)

        result = await orch.step()
        assert result is task
        assert task.status == TaskStatus.FAILED
        assert "workspace boom" in (task.error or "")
        assert orch.state.tasks_failed == 1


# ---------------------------------------------------------------------------
# step() edge cases
# ---------------------------------------------------------------------------


class TestStepEdgeCases:
    """Edge cases for the step() method."""

    async def test_step_empty_queue_returns_none(self) -> None:
        orch = Orchestrator(config=_config())
        result = await orch.step()
        assert result is None
        assert orch.state.phase == Phase.IDLE

    async def test_step_missing_task_returns_none(self) -> None:
        """If the queued task ID is no longer in the registry, step returns None."""
        orch = Orchestrator(config=_config())
        orch.queue.append("ghost-id")
        result = await orch.step()
        assert result is None

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_step_sets_started_at_once(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """started_at is set on first step and not overwritten."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result()

        orch = Orchestrator(config=_config())
        assert orch.state.started_at is None

        orch.add_task(_task(title="t1"))
        orch.add_task(_task(title="t2"))

        await orch.step()
        first_started = orch.state.started_at
        assert first_started is not None

        await orch.step()
        assert orch.state.started_at == first_started  # Not overwritten

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_step_clears_current_task_id(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """current_task_id is cleared after step completes."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result()

        orch = Orchestrator(config=_config())
        task = _task()
        orch.add_task(task)

        await orch.step()
        assert orch.state.current_task_id is None


# ---------------------------------------------------------------------------
# run() loop behavior
# ---------------------------------------------------------------------------


class TestRunLoop:
    """Test the run() method's loop control."""

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_run_processes_all_tasks(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result()

        orch = Orchestrator(config=_config())
        for i in range(3):
            orch.add_task(_task(title=f"task-{i}"))

        processed = await orch.run()
        assert len(processed) == 3
        assert orch.state.tasks_completed == 3

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_run_respects_max_tasks(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result()

        orch = Orchestrator(config=_config())
        for i in range(5):
            orch.add_task(_task(title=f"task-{i}"))

        processed = await orch.run(max_tasks=2)
        assert len(processed) == 2
        assert len(orch.queue) == 3  # Remaining tasks still queued

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_run_stops_on_consecutive_identical_errors(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """Run bails out after 2 consecutive identical worker errors."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result(success=False)

        orch = Orchestrator(config=_config())
        for i in range(5):
            orch.add_task(_task(title=f"task-{i}"))

        processed = await orch.run()
        # Should stop after 2 consecutive identical failures
        assert len(processed) == 2
        assert orch.state.consecutive_identical_errors >= 2
        assert len(orch.queue) == 0  # Queue is cleared on bail-out


# ---------------------------------------------------------------------------
# _should_decompose
# ---------------------------------------------------------------------------


class TestShouldDecompose:
    """Test the decomposition decision logic."""

    def test_skip_decomposition_config(self) -> None:
        orch = Orchestrator(config=_config(skip_decomposition=True))
        task = _task(description="A" * 200)
        assert orch._should_decompose(task) is False

    def test_subtask_not_decomposed(self) -> None:
        orch = Orchestrator(config=_config(skip_decomposition=False))
        task = _task(parent_id="parent-123", description="A" * 200)
        assert orch._should_decompose(task) is False

    def test_max_depth_not_decomposed(self) -> None:
        orch = Orchestrator(config=_config(skip_decomposition=False, max_subtask_depth=1))
        task = _task(depth=1, description="A" * 200)
        assert orch._should_decompose(task) is False

    def test_already_has_subtasks_not_decomposed(self) -> None:
        orch = Orchestrator(config=_config(skip_decomposition=False))
        task = _task(description="A" * 200)
        task.subtask_ids = ["sub-1"]
        assert orch._should_decompose(task) is False

    def test_short_description_not_decomposed(self) -> None:
        orch = Orchestrator(config=_config(skip_decomposition=False))
        task = _task(description="Short")
        assert orch._should_decompose(task) is False

    def test_small_estimate_not_decomposed(self) -> None:
        orch = Orchestrator(config=_config(skip_decomposition=False, decompose_threshold_hours=4.0))
        task = _task(description="A" * 200, estimated_hours=2.0)
        assert orch._should_decompose(task) is False

    def test_eligible_task_is_decomposed(self) -> None:
        orch = Orchestrator(config=_config(skip_decomposition=False, decompose_threshold_hours=4.0))
        task = _task(description="A" * 200, estimated_hours=8.0)
        assert orch._should_decompose(task) is True

    def test_no_estimate_is_decomposed(self) -> None:
        """Tasks without an estimate are eligible (estimated_hours is None)."""
        orch = Orchestrator(config=_config(skip_decomposition=False))
        task = _task(description="A" * 200)
        assert orch._should_decompose(task) is True


# ---------------------------------------------------------------------------
# Decomposition into subtasks (PLAN phase)
# ---------------------------------------------------------------------------


class TestDecomposition:
    """Test that the PLAN phase can decompose tasks into subtasks."""

    @patch("agents.orchestrator.state_machine.plan_task")
    async def test_plan_creates_subtasks(self, mock_plan: AsyncMock) -> None:
        """When planner returns subtasks, they are registered and queued."""
        sub1 = _task(title="sub-1", parent_id="will-be-set")
        sub2 = _task(title="sub-2", parent_id="will-be-set")
        mock_plan.return_value = [sub1, sub2]

        orch = Orchestrator(
            config=_config(
                skip_decomposition=False,
                max_total_tasks=50,
                max_subtasks_per_task=6,
            )
        )
        parent = _task(title="big task", description="A" * 200, estimated_hours=10.0)
        orch.add_task(parent)

        result = await orch.step()
        assert result is parent
        assert parent.status == TaskStatus.IN_PROGRESS
        assert len(parent.subtask_ids) == 2
        # Subtasks should be in the registry and queue
        assert sub1.id in orch.tasks
        assert sub2.id in orch.tasks

    @patch("agents.orchestrator.state_machine.plan_task")
    async def test_plan_failure_falls_through_to_execute(self, mock_plan: AsyncMock) -> None:
        """If planning fails, the task is executed as-is (not decomposed)."""
        from agents.orchestrator.planner import PlanningError

        mock_plan.side_effect = PlanningError("LLM refused")

        orch = Orchestrator(config=_config(skip_decomposition=False, max_total_tasks=50))
        task = _task(description="A" * 200, estimated_hours=10.0)
        orch.add_task(task)

        # Mock the execute path
        with (
            patch("agents.orchestrator.state_machine.ensure_workspace", return_value="ws-1"),
            patch(
                "agents.orchestrator.state_machine.dispatch_worker",
                return_value=_mock_worker_result(),
            ),
        ):
            result = await orch.step()

        assert result is task
        assert task.status == TaskStatus.COMPLETED

    @patch("agents.orchestrator.state_machine.plan_task")
    async def test_insufficient_headroom_skips_decomposition(self, mock_plan: AsyncMock) -> None:
        """When not enough task slots remain, decomposition is skipped."""
        orch = Orchestrator(
            config=_config(
                skip_decomposition=False,
                max_total_tasks=5,
                max_subtasks_per_task=6,
            )
        )
        # Fill up most of the registry
        for i in range(4):
            orch.add_task(_task(title=f"filler-{i}", status=TaskStatus.COMPLETED))

        task = _task(description="A" * 200, estimated_hours=10.0)
        orch.add_task(task)

        # mock_plan should NOT be called since headroom (5-5=0) < max_subtasks (6)
        with (
            patch("agents.orchestrator.state_machine.ensure_workspace", return_value="ws-1"),
            patch(
                "agents.orchestrator.state_machine.dispatch_worker",
                return_value=_mock_worker_result(),
            ),
        ):
            result = await orch.step()

        mock_plan.assert_not_called()
        assert result is task
        assert task.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Publish phase
# ---------------------------------------------------------------------------


class TestPublishPhase:
    """Test the PUBLISH phase (push branch, create PR)."""

    @patch("agents.orchestrator.state_machine.push_and_create_pr")
    @patch("agents.orchestrator.state_machine.get_workspace_diff")
    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_publish_failure_is_non_fatal(
        self,
        mock_workspace: AsyncMock,
        mock_worker: AsyncMock,
        mock_diff: AsyncMock,
        mock_pr: AsyncMock,
    ) -> None:
        """Publish failure does not fail the task; it proceeds to finalization."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result()
        mock_diff.side_effect = RuntimeError("git push failed")

        orch = Orchestrator(config=_config())
        task = _task(autonomy_tier=AutonomyTier.AUTO_MERGE)
        task.branch_name = "feat/test"
        orch.add_task(task)

        result = await orch.step()
        assert result is task
        assert task.status == TaskStatus.COMPLETED  # Still completes
        assert task.pr_url is None

    @patch("agents.orchestrator.state_machine.push_and_create_pr")
    @patch("agents.orchestrator.state_machine.get_workspace_diff")
    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_no_publish_without_branch(
        self,
        mock_workspace: AsyncMock,
        mock_worker: AsyncMock,
        mock_diff: AsyncMock,
        mock_pr: AsyncMock,
    ) -> None:
        """Tasks without branch_name skip the PUBLISH phase entirely."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result()

        orch = Orchestrator(config=_config())
        task = _task(autonomy_tier=AutonomyTier.AUTO_MERGE)
        # No branch_name set
        orch.add_task(task)

        result = await orch.step()
        assert result is task
        assert task.status == TaskStatus.COMPLETED
        mock_diff.assert_not_called()
        mock_pr.assert_not_called()


# ---------------------------------------------------------------------------
# Approve / Reject
# ---------------------------------------------------------------------------


class TestApproveReject:
    """Test human approval and rejection flows."""

    async def test_approve_awaiting_task(self) -> None:
        orch = Orchestrator(config=_config())
        task = _task(status=TaskStatus.AWAITING_HUMAN)
        orch.tasks[task.id] = task  # Direct registration (not queued)

        result = await orch.approve_task(task.id)
        assert result is True
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None
        assert orch.state.tasks_completed == 1

    async def test_approve_non_awaiting_returns_false(self) -> None:
        orch = Orchestrator(config=_config())
        task = _task(status=TaskStatus.IN_PROGRESS)
        orch.tasks[task.id] = task

        result = await orch.approve_task(task.id)
        assert result is False
        assert task.status == TaskStatus.IN_PROGRESS

    async def test_approve_missing_task_returns_false(self) -> None:
        orch = Orchestrator(config=_config())
        result = await orch.approve_task("nonexistent")
        assert result is False

    async def test_reject_awaiting_task(self) -> None:
        orch = Orchestrator(config=_config())
        task = _task(status=TaskStatus.AWAITING_HUMAN)
        orch.tasks[task.id] = task

        result = await orch.reject_task(task.id, reason="bad code")
        assert result is True
        assert task.status == TaskStatus.FAILED
        assert "bad code" in (task.error or "")
        assert orch.state.tasks_failed == 1

    async def test_reject_without_reason(self) -> None:
        orch = Orchestrator(config=_config())
        task = _task(status=TaskStatus.AWAITING_HUMAN)
        orch.tasks[task.id] = task

        result = await orch.reject_task(task.id)
        assert result is True
        assert task.error == "Rejected by human"

    async def test_reject_non_awaiting_returns_false(self) -> None:
        orch = Orchestrator(config=_config())
        task = _task(status=TaskStatus.COMPLETED)
        orch.tasks[task.id] = task

        result = await orch.reject_task(task.id)
        assert result is False


# ---------------------------------------------------------------------------
# Parent finalization
# ---------------------------------------------------------------------------


class TestParentFinalization:
    """Test _try_finalize_parent behavior."""

    async def test_parent_completes_when_all_subtasks_complete(self) -> None:
        orch = Orchestrator(config=_config())

        parent = _task(title="parent", status=TaskStatus.IN_PROGRESS)
        child1 = _task(title="child-1", parent_id=parent.id, status=TaskStatus.COMPLETED)
        child2 = _task(title="child-2", parent_id=parent.id, status=TaskStatus.COMPLETED)
        child1.completed_at = child2.completed_at = parent.started_at

        orch.tasks[parent.id] = parent
        orch.tasks[child1.id] = child1
        orch.tasks[child2.id] = child2

        await orch._try_finalize_parent(parent.id)
        assert parent.status == TaskStatus.COMPLETED

    async def test_parent_fails_when_subtask_fails(self) -> None:
        orch = Orchestrator(config=_config())

        parent = _task(title="parent", status=TaskStatus.IN_PROGRESS)
        child1 = _task(title="child-ok", parent_id=parent.id, status=TaskStatus.COMPLETED)
        child2 = _task(title="child-fail", parent_id=parent.id, status=TaskStatus.FAILED)
        child1.completed_at = child2.completed_at = parent.started_at

        orch.tasks[parent.id] = parent
        orch.tasks[child1.id] = child1
        orch.tasks[child2.id] = child2

        await orch._try_finalize_parent(parent.id)
        assert parent.status == TaskStatus.FAILED
        assert "child-fail" in (parent.error or "")
        assert orch.state.tasks_failed == 1

    async def test_parent_not_finalized_with_pending_subtask(self) -> None:
        orch = Orchestrator(config=_config())

        parent = _task(title="parent", status=TaskStatus.IN_PROGRESS)
        child1 = _task(title="child-done", parent_id=parent.id, status=TaskStatus.COMPLETED)
        child2 = _task(title="child-wip", parent_id=parent.id, status=TaskStatus.IN_PROGRESS)

        orch.tasks[parent.id] = parent
        orch.tasks[child1.id] = child1
        orch.tasks[child2.id] = child2

        await orch._try_finalize_parent(parent.id)
        assert parent.status == TaskStatus.IN_PROGRESS  # Unchanged

    async def test_parent_not_finalized_if_already_completed(self) -> None:
        orch = Orchestrator(config=_config())

        parent = _task(title="parent", status=TaskStatus.COMPLETED)
        child = _task(title="child", parent_id=parent.id, status=TaskStatus.COMPLETED)

        orch.tasks[parent.id] = parent
        orch.tasks[child.id] = child

        await orch._try_finalize_parent(parent.id)
        # Should be a no-op; parent stays COMPLETED and no counter increments
        assert parent.status == TaskStatus.COMPLETED
        assert orch.state.tasks_completed == 0  # Not double-counted

    async def test_approve_subtask_finalizes_parent(self) -> None:
        """Approving the last awaiting subtask should finalize its parent."""
        orch = Orchestrator(config=_config())

        parent = _task(title="parent", status=TaskStatus.IN_PROGRESS)
        child1 = _task(title="child-1", parent_id=parent.id, status=TaskStatus.COMPLETED)
        child2 = _task(title="child-2", parent_id=parent.id, status=TaskStatus.AWAITING_HUMAN)

        orch.tasks[parent.id] = parent
        orch.tasks[child1.id] = child1
        orch.tasks[child2.id] = child2

        result = await orch.approve_task(child2.id)
        assert result is True
        assert child2.status == TaskStatus.COMPLETED
        assert parent.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Notification callbacks
# ---------------------------------------------------------------------------


class TestNotificationCallbacks:
    """Test that callbacks fire correctly (both sync and async)."""

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_progress_callback_fires(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result()

        progress_events: list[tuple[str, str, str]] = []
        orch = Orchestrator(config=_config())
        orch.on_progress(
            lambda phase, title, detail: progress_events.append((phase, title, detail))
        )

        task = _task(title="test-task")
        orch.add_task(task)
        await orch.step()

        phases = [p[0] for p in progress_events]
        assert "ingest" in phases
        assert "execute" in phases

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_async_callback_is_awaited(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """Async callbacks are properly awaited."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result()

        completed: list[str] = []

        async def on_complete(task: Task) -> None:
            completed.append(task.title)

        orch = Orchestrator(config=_config())
        orch.on_task_complete(on_complete)

        task = _task(title="async-cb-task")
        orch.add_task(task)
        await orch.step()

        assert "async-cb-task" in completed

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_callback_exception_is_swallowed(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """Callback exceptions do not crash the orchestrator."""
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result()

        def bad_callback(task: Task) -> None:
            raise ValueError("callback exploded")

        orch = Orchestrator(config=_config())
        orch.on_task_complete(bad_callback)

        task = _task()
        orch.add_task(task)

        # Should not raise
        result = await orch.step()
        assert result is task
        assert task.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# asyncio lock behavior
# ---------------------------------------------------------------------------


class TestAsyncioLock:
    """Test that the asyncio.Lock prevents concurrent state mutation."""

    async def test_lock_exists_and_is_asyncio_lock(self) -> None:
        orch = Orchestrator(config=_config())
        assert isinstance(orch._lock, asyncio.Lock)

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_concurrent_steps_serialized(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        """Two concurrent step() calls should not corrupt state.

        We verify this by running two steps concurrently and checking
        that exactly two tasks are processed with correct counters.
        """
        call_order: list[str] = []

        async def slow_workspace(task, config, **kwargs):
            call_order.append(f"workspace-{task.title}")
            await asyncio.sleep(0.01)
            return f"ws-{task.title}"

        async def slow_worker(task, config):
            call_order.append(f"worker-{task.title}")
            await asyncio.sleep(0.01)
            return _mock_worker_result()

        mock_workspace.side_effect = slow_workspace
        mock_worker.side_effect = slow_worker

        orch = Orchestrator(config=_config())
        orch.add_task(_task(title="task-a"))
        orch.add_task(_task(title="task-b"))

        results = await asyncio.gather(orch.step(), orch.step())
        non_none = [r for r in results if r is not None]
        assert len(non_none) == 2
        assert orch.state.tasks_completed == 2

    async def test_lock_not_held_after_step(self) -> None:
        """After step() returns, the lock should be released."""
        orch = Orchestrator(config=_config())
        await orch.step()  # Empty queue, quick return
        assert not orch._lock.locked()


# ---------------------------------------------------------------------------
# Worker error tracking
# ---------------------------------------------------------------------------


class TestWorkerErrorTracking:
    """Test consecutive identical error tracking in state."""

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_identical_errors_increment_counter(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        mock_workspace.return_value = "ws-1"
        mock_worker.return_value = _mock_worker_result(success=False)

        orch = Orchestrator(config=_config())
        orch.add_task(_task(title="t1"))
        orch.add_task(_task(title="t2"))

        await orch.step()
        assert orch.state.consecutive_identical_errors == 1
        assert orch.state.last_worker_error == "worker error"

        await orch.step()
        assert orch.state.consecutive_identical_errors == 2

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_different_error_resets_counter(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        mock_workspace.return_value = "ws-1"

        result1 = _mock_worker_result(success=False)
        result1.error = "error A"
        result2 = _mock_worker_result(success=False)
        result2.error = "error B"
        mock_worker.side_effect = [result1, result2]

        orch = Orchestrator(config=_config())
        orch.add_task(_task(title="t1"))
        orch.add_task(_task(title="t2"))

        await orch.step()
        assert orch.state.consecutive_identical_errors == 1
        assert orch.state.last_worker_error == "error A"

        await orch.step()
        assert orch.state.consecutive_identical_errors == 1
        assert orch.state.last_worker_error == "error B"

    @patch("agents.orchestrator.state_machine.dispatch_worker")
    @patch("agents.orchestrator.state_machine.ensure_workspace")
    async def test_success_resets_error_counter(
        self, mock_workspace: AsyncMock, mock_worker: AsyncMock
    ) -> None:
        mock_workspace.return_value = "ws-1"
        fail_result = _mock_worker_result(success=False)
        success_result = _mock_worker_result(success=True)
        mock_worker.side_effect = [fail_result, success_result]

        orch = Orchestrator(config=_config())
        orch.add_task(_task(title="t1"))
        orch.add_task(_task(title="t2"))

        await orch.step()
        assert orch.state.consecutive_identical_errors == 1

        await orch.step()
        assert orch.state.consecutive_identical_errors == 0
        assert orch.state.last_worker_error is None


# ---------------------------------------------------------------------------
# get_status_summary
# ---------------------------------------------------------------------------


class TestStatusSummary:
    """Test the status summary snapshot."""

    def test_summary_structure(self) -> None:
        orch = Orchestrator(config=_config())
        t1 = _task(status=TaskStatus.PENDING)
        t2 = _task(status=TaskStatus.COMPLETED)
        orch.tasks[t1.id] = t1
        orch.tasks[t2.id] = t2
        orch.queue.append(t1.id)

        summary = orch.get_status_summary()
        assert summary["total_tasks"] == 2
        assert summary["queue_size"] == 1
        assert summary["status_counts"]["pending"] == 1
        assert summary["status_counts"]["completed"] == 1
        assert "state" in summary
        assert summary["state"]["phase"] == "idle"

    def test_empty_summary(self) -> None:
        orch = Orchestrator(config=_config())
        summary = orch.get_status_summary()
        assert summary["total_tasks"] == 0
        assert summary["queue_size"] == 0
        assert summary["status_counts"] == {}


# ---------------------------------------------------------------------------
# Finalize task (autonomy tier dispatch)
# ---------------------------------------------------------------------------


class TestFinalizeTask:
    """Test _finalize_task dispatches correctly based on autonomy tier."""

    async def test_finalize_manual_only_goes_to_human_gate(self) -> None:
        """MANUAL_ONLY at finalize still enters HUMAN_GATE."""
        human_tasks: list[Task] = []
        orch = Orchestrator(config=_config())
        orch.on_human_approval_needed(lambda t: human_tasks.append(t))

        task = _task(autonomy_tier=AutonomyTier.MANUAL_ONLY)
        orch.tasks[task.id] = task

        await orch._finalize_task(task)
        assert task.status == TaskStatus.AWAITING_HUMAN
        assert orch.state.phase == Phase.HUMAN_GATE
        assert len(human_tasks) == 1
