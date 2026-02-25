"""Core orchestrator state machine.

The orchestrator is a lightweight control plane that drives work through a
deterministic state machine:

    INGEST -> PLAN -> EXECUTE -> PUBLISH -> COMPLETE
                                    |          |
                                    v          v
                               HUMAN_GATE   FAILED
                                    |
                                    v
                                 COMPLETE

It is NOT an LLM agent. It invokes LLM agents at specific stages (planning)
but the flow control is deterministic based on task configuration.

NOTE: This class is **not** thread-safe.  All public methods must be called
from the same asyncio event loop.  An ``asyncio.Lock`` guards internal state
to prevent re-entrancy from concurrent coroutines.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from .models import (
    AutonomyTier,
    OrchestratorConfig,
    OrchestratorState,
    Phase,
    Task,
    TaskStatus,
    _utcnow,
)
from .planner import PlanningError, plan_task
from .workers import dispatch_worker, ensure_workspace, get_workspace_diff, push_and_create_pr

logger = logging.getLogger(__name__)


class TaskLimitExceeded(Exception):
    """Raised when the global task limit is reached."""


class Orchestrator:
    """Task-driven orchestration state machine.

    The orchestrator maintains a task registry and processes tasks through
    a deterministic pipeline. It does not make LLM-based routing decisions;
    routing is based on task configuration (autonomy tier) and review
    outcomes (pass/fail).

    Concurrency: All public methods are guarded by an ``asyncio.Lock``.
    Do **not** call from multiple threads; use a single event loop.

    Usage:
        config = OrchestratorConfig()
        orch = Orchestrator(config)

        # Add a task
        task = Task(title="Implement feature X", description="...")
        orch.add_task(task)

        # Run the loop (processes one task per call)
        result = await orch.step()

        # Or run continuously
        await orch.run()
    """

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        git_repo_url: str | None = None,
    ) -> None:
        self.config = config or OrchestratorConfig()
        self.git_repo_url = git_repo_url

        # Task registry: id -> Task
        self.tasks: dict[str, Task] = {}

        # Queue of task IDs ready for processing
        self.queue: deque[str] = deque()

        # Orchestrator state for observability
        self.state = OrchestratorState()

        # Callbacks for human gate, notifications, and progress
        self._on_human_approval_needed: list[Any] = []
        self._on_task_complete: list[Any] = []
        self._on_task_failed: list[Any] = []
        self._on_progress: list[Any] = []

        # Lock to prevent re-entrant state mutation from concurrent coroutines
        self._lock = asyncio.Lock()

    def add_task(self, task: Task) -> Task:
        """Add a task to the orchestrator.

        Args:
            task: Task to add.

        Returns:
            The task (with any modifications).

        Raises:
            TaskLimitExceeded: If the global task limit would be exceeded.
        """
        if len(self.tasks) >= self.config.max_total_tasks:
            raise TaskLimitExceeded(
                f"Global task limit reached ({self.config.max_total_tasks}). "
                f"Cannot add task: {task.title!r}"
            )

        self.tasks[task.id] = task
        if task.status == TaskStatus.PENDING:
            self.queue.append(task.id)
        logger.info(f"Added task {task.id}: {task.title} (queue size: {len(self.queue)})")
        return task

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self.tasks.get(task_id)

    def get_subtasks(self, parent_id: str) -> list[Task]:
        """Get all subtasks of a parent task."""
        return [t for t in self.tasks.values() if t.parent_id == parent_id]

    async def step(self) -> Task | None:
        """Process the next task in the queue through one full cycle.

        Returns the processed task, or None if the queue is empty.
        """
        async with self._lock:
            if not self.queue:
                self.state.phase = Phase.IDLE
                return None

            task_id = self.queue.popleft()
            task = self.tasks.get(task_id)
            if task is None:
                logger.warning(f"Task {task_id} not found in registry, skipping")
                return None

            self.state.current_task_id = task.id
            if self.state.started_at is None:
                self.state.started_at = _utcnow()

        # Process outside the lock (long-running I/O)
        try:
            await self._process_task(task)
        except TaskLimitExceeded as e:
            logger.error(f"Task limit exceeded while processing {task.id}: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            async with self._lock:
                self.state.tasks_failed += 1
                self.state.phase = Phase.FAILED
            await self._notify_failure(task)
        except Exception as e:
            logger.exception(f"Unhandled error processing task {task.id}: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            async with self._lock:
                self.state.tasks_failed += 1
                self.state.phase = Phase.FAILED
            await self._notify_failure(task)

        async with self._lock:
            self.state.current_task_id = None
        return task

    async def run(self, max_tasks: int | None = None) -> list[Task]:
        """Run the orchestrator loop until the queue is empty.

        Args:
            max_tasks: Stop after processing this many tasks (safety limit).

        Returns:
            List of all processed tasks.
        """
        processed: list[Task] = []
        count = 0

        while self.queue:
            if max_tasks is not None and count >= max_tasks:
                logger.info(f"Reached max_tasks limit ({max_tasks}), stopping")
                break

            task = await self.step()
            if task:
                processed.append(task)
                count += 1

            # Fail-fast: stop if the same error keeps repeating
            if self.state.consecutive_identical_errors >= 2:
                logger.warning(
                    f"Stopping: {self.state.consecutive_identical_errors} consecutive "
                    f"identical worker errors: {self.state.last_worker_error!r}"
                )
                self.queue.clear()
                break

        logger.info(
            f"Orchestrator run complete: {len(processed)} tasks processed, "
            f"{self.state.tasks_completed} completed, {self.state.tasks_failed} failed"
        )
        return processed

    async def _process_task(self, task: Task) -> None:
        """Process a single task through the full pipeline.

        Pipeline: INGEST -> PLAN -> EXECUTE -> PUBLISH -> COMPLETE/HUMAN_GATE
        """
        # INGEST: Validate and prepare
        async with self._lock:
            self.state.phase = Phase.INGEST
        task.started_at = _utcnow()
        await self._notify_progress("ingest", task)

        if task.autonomy_tier == AutonomyTier.MANUAL_ONLY:
            logger.info(f"Task {task.id} is MANUAL_ONLY, notifying human")
            task.status = TaskStatus.AWAITING_HUMAN
            async with self._lock:
                self.state.phase = Phase.HUMAN_GATE
            await self._notify_human_required(task)
            return

        # PLAN: Decompose into subtasks if this is a high-level task
        async with self._lock:
            self.state.phase = Phase.PLAN
        task.status = TaskStatus.PLANNING
        await self._notify_progress("plan", task)

        if task.is_leaf() and self._should_decompose(task):
            # Check headroom before spending an LLM call on planning
            headroom = self.config.max_total_tasks - len(self.tasks)
            if headroom < self.config.max_subtasks_per_task:
                logger.warning(
                    f"Insufficient task headroom ({headroom} slots for up to "
                    f"{self.config.max_subtasks_per_task} subtasks), "
                    f"executing task {task.id} as-is"
                )
            else:
                subtasks = await self._plan_task(task)
                if subtasks is not None and len(subtasks) > 1:
                    # This task becomes a parent; queue subtasks instead
                    for subtask in subtasks:
                        self.add_task(subtask)
                        task.subtask_ids.append(subtask.id)
                    task.status = TaskStatus.IN_PROGRESS
                    logger.info(f"Task {task.id} decomposed into {len(subtasks)} subtasks")
                    return

        # EXECUTE: Dispatch worker
        async with self._lock:
            self.state.phase = Phase.EXECUTE
        task.status = TaskStatus.IN_PROGRESS
        await self._notify_progress("execute", task, "dispatching worker")
        await self._execute_task(task)

        if task.status == TaskStatus.FAILED:
            async with self._lock:
                self.state.tasks_failed += 1
                self.state.phase = Phase.FAILED
            await self._notify_failure(task)
            return

        # PUBLISH: Push branch and create PR (only for tasks with changes)
        if task.branch_name and task.workspace_name:
            async with self._lock:
                self.state.phase = Phase.PUBLISH
            await self._notify_progress("publish", task, "pushing branch and creating PR")
            await self._publish_task(task)

        # COMPLETE or HUMAN_GATE based on autonomy tier
        await self._finalize_task(task)

        # If this task has a parent, check whether the parent can be finalized
        if task.parent_id:
            await self._try_finalize_parent(task.parent_id)

    def _should_decompose(self, task: Task) -> bool:
        """Determine if a task should be decomposed into subtasks.

        Tasks are NOT decomposed if:
        - Decomposition is globally disabled (skip_decomposition)
        - They're already a subtask (have a parent_id)
        - They're already at max depth
        - They're already decomposed (have subtask_ids)
        - Their description is very short (likely already atomic)
        - Their estimated hours are at or below the threshold (small enough to do in one shot)
        """
        if self.config.skip_decomposition:
            return False
        # Subtasks are never decomposed — the taskmanager only supports one
        # layer of subtasks, and the depth check alone depends on depth being
        # set correctly when subtasks are created.
        if task.parent_id is not None:
            return False
        if task.depth >= self.config.max_subtask_depth:
            return False
        if task.subtask_ids:
            return False
        # Short descriptions suggest atomic tasks
        if len(task.description) < 100:
            return False
        # Small tasks don't need decomposition
        if (
            task.estimated_hours is not None
            and task.estimated_hours <= self.config.decompose_threshold_hours
        ):
            logger.info(
                f"Skipping decomposition for {task.id}: "
                f"estimated {task.estimated_hours}h <= {self.config.decompose_threshold_hours}h threshold"
            )
            return False
        return True

    async def _plan_task(self, task: Task) -> list[Task] | None:
        """Plan/decompose a task into subtasks.

        Returns:
            List of subtasks, or None if planning failed (task executes as-is).
        """
        try:
            subtasks = await plan_task(
                task,
                model=self.config.planner_model,
                max_subtasks=self.config.max_subtasks_per_task,
            )
            return subtasks
        except PlanningError as e:
            logger.error(f"Planning failed for task {task.id}: {e}")
            # Fall through to execute the task as-is
            return None
        except Exception as e:
            logger.error(f"Unexpected planning error for task {task.id}: {e}")
            return None

    async def _execute_task(self, task: Task) -> None:
        """Execute a task by dispatching a Claude Code worker."""
        try:
            # Ensure workspace exists
            workspace_name = await ensure_workspace(
                task, self.config, git_repo_url=self.git_repo_url
            )
            task.workspace_name = workspace_name

            # Dispatch worker
            result = await dispatch_worker(task, self.config)

            task.worker_output = result.output
            async with self._lock:
                self.state.total_worker_turns += result.turns_used

            if not result.success:
                task.status = TaskStatus.FAILED
                task.error = result.error or "Worker execution failed"
                logger.warning(f"Worker failed for task {task.id}: {task.error}")
                async with self._lock:
                    error_key = task.error
                    if error_key == self.state.last_worker_error:
                        self.state.consecutive_identical_errors += 1
                    else:
                        self.state.last_worker_error = error_key
                        self.state.consecutive_identical_errors = 1
            else:
                async with self._lock:
                    self.state.last_worker_error = None
                    self.state.consecutive_identical_errors = 0

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"Execution failed for task {task.id}: {e}")
            async with self._lock:
                error_key = str(e)
                if error_key == self.state.last_worker_error:
                    self.state.consecutive_identical_errors += 1
                else:
                    self.state.last_worker_error = error_key
                    self.state.consecutive_identical_errors = 1

    async def _publish_task(self, task: Task) -> None:
        """Push branch and create a PR for a completed task.

        Best-effort: if push or PR creation fails, the task still proceeds
        to finalization. The code is committed locally regardless.
        """
        try:
            # Get diff summary for the PR body
            diff = await get_workspace_diff(
                task.workspace_name,  # type: ignore[arg-type]
                task.branch_name,  # type: ignore[arg-type]
                self.config,
            )
            # Use a short stat-like summary, not the full diff
            diff_lines = diff.strip().splitlines()
            diff_summary = "\n".join(diff_lines[:50]) if diff_lines else ""

            pr_url = await push_and_create_pr(task, self.config, diff_summary=diff_summary)
            task.pr_url = pr_url

            if pr_url:
                logger.info(f"Task {task.id} published: {pr_url}")
            else:
                logger.warning(f"Task {task.id}: push/PR creation returned no URL")
        except Exception as e:
            logger.error(f"Publish failed for task {task.id}: {e}")
            # Non-fatal: task proceeds to finalization

    async def _finalize_task(self, task: Task) -> None:
        """Finalize a task based on its autonomy tier."""
        match task.autonomy_tier:
            case AutonomyTier.AUTO_MERGE:
                # Auto-complete
                task.status = TaskStatus.COMPLETED
                task.completed_at = _utcnow()
                async with self._lock:
                    self.state.tasks_completed += 1
                    self.state.phase = Phase.COMPLETE
                logger.info(f"Task {task.id} auto-completed (tier 1)")
                await self._notify_complete(task)

            case AutonomyTier.PROPOSE_EXECUTE:
                # Complete but notify human
                task.status = TaskStatus.COMPLETED
                task.completed_at = _utcnow()
                async with self._lock:
                    self.state.tasks_completed += 1
                    self.state.phase = Phase.COMPLETE
                logger.info(f"Task {task.id} completed, notifying human (tier 2)")
                await self._notify_complete(task)

            case AutonomyTier.PROPOSE_WAIT:
                # Wait for human approval
                task.status = TaskStatus.AWAITING_HUMAN
                async with self._lock:
                    self.state.phase = Phase.HUMAN_GATE
                logger.info(f"Task {task.id} awaiting human approval (tier 3)")
                await self._notify_human_required(task)

            case AutonomyTier.MANUAL_ONLY:
                # Should not reach here, but handle gracefully
                task.status = TaskStatus.AWAITING_HUMAN
                async with self._lock:
                    self.state.phase = Phase.HUMAN_GATE
                await self._notify_human_required(task)

    async def _try_finalize_parent(self, parent_id: str) -> None:
        """Check if all subtasks of a parent are done; if so, finalize it.

        A parent is finalized when every one of its subtasks has reached a
        terminal status (COMPLETED or FAILED).  If any subtask failed, the
        parent is marked FAILED.  Otherwise the parent goes through the
        normal autonomy-tier finalization path.
        """
        parent = self.tasks.get(parent_id)
        if parent is None or parent.status not in (
            TaskStatus.IN_PROGRESS,
            TaskStatus.PLANNING,
        ):
            return

        subtasks = self.get_subtasks(parent_id)
        if not subtasks:
            return

        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED}
        if not all(st.status in terminal for st in subtasks):
            return  # Some subtasks still running

        any_failed = any(st.status == TaskStatus.FAILED for st in subtasks)
        if any_failed:
            parent.status = TaskStatus.FAILED
            failed_titles = [st.title for st in subtasks if st.status == TaskStatus.FAILED]
            parent.error = f"Subtask(s) failed: {failed_titles}"
            parent.completed_at = _utcnow()
            async with self._lock:
                self.state.tasks_failed += 1
            logger.info(f"Parent task {parent_id} marked FAILED (subtask failures)")
            await self._notify_failure(parent)
        else:
            logger.info(f"All {len(subtasks)} subtasks of {parent_id} completed, finalizing parent")
            await self._finalize_task(parent)

        # Recurse upward: if this parent also has a parent, check it too
        if parent.parent_id:
            await self._try_finalize_parent(parent.parent_id)

    # ------------------------------------------------------------------
    # Notification hooks
    # ------------------------------------------------------------------

    def on_progress(self, callback) -> None:
        """Register a callback for progress updates.

        Callback receives (phase: str, task_title: str, detail: str).
        """
        self._on_progress.append(callback)

    def on_human_approval_needed(self, callback) -> None:
        """Register a callback for when human approval is needed."""
        self._on_human_approval_needed.append(callback)

    def on_task_complete(self, callback) -> None:
        """Register a callback for task completion."""
        self._on_task_complete.append(callback)

    def on_task_failed(self, callback) -> None:
        """Register a callback for task failure."""
        self._on_task_failed.append(callback)

    async def _notify_human_required(self, task: Task) -> None:
        """Fire callbacks when human approval is needed."""
        for cb in self._on_human_approval_needed:
            try:
                result = cb(task)
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logger.error(f"Human approval callback failed: {e}")

    async def _notify_complete(self, task: Task) -> None:
        """Fire callbacks when a task completes."""
        for cb in self._on_task_complete:
            try:
                result = cb(task)
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logger.error(f"Completion callback failed: {e}")

    async def _notify_failure(self, task: Task) -> None:
        """Fire callbacks when a task fails."""
        for cb in self._on_task_failed:
            try:
                result = cb(task)
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logger.error(f"Failure callback failed: {e}")

    async def _notify_progress(self, phase: str, task: Task, detail: str = "") -> None:
        """Fire progress callbacks for visibility into long-running operations."""
        for cb in self._on_progress:
            try:
                result = cb(phase, task.title, detail)
                if hasattr(result, "__await__"):
                    await result
            except Exception:  # nosec B110
                pass  # Progress callbacks must never disrupt execution

    async def approve_task(self, task_id: str) -> bool:
        """Approve a task that is awaiting human approval.

        Args:
            task_id: ID of the task to approve.

        Returns:
            True if the task was approved, False if not found or not awaiting.
        """
        async with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.status != TaskStatus.AWAITING_HUMAN:
                return False

            task.status = TaskStatus.COMPLETED
            task.completed_at = _utcnow()
            self.state.tasks_completed += 1
            logger.info(f"Task {task_id} approved by human")

        # Check if completing this task finalizes a parent
        if task.parent_id:
            await self._try_finalize_parent(task.parent_id)

        return True

    async def reject_task(self, task_id: str, reason: str = "") -> bool:
        """Reject a task that is awaiting human approval.

        Args:
            task_id: ID of the task to reject.
            reason: Reason for rejection.

        Returns:
            True if the task was rejected, False if not found or not awaiting.
        """
        async with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.status != TaskStatus.AWAITING_HUMAN:
                return False

            task.status = TaskStatus.FAILED
            task.error = f"Rejected by human: {reason}" if reason else "Rejected by human"
            self.state.tasks_failed += 1
            logger.info(f"Task {task_id} rejected by human: {reason}")

        return True

    def get_status_summary(self) -> dict[str, Any]:
        """Get a summary of the orchestrator's current state."""
        status_counts: dict[str, int] = {}
        for task in self.tasks.values():
            status_counts[task.status.value] = status_counts.get(task.status.value, 0) + 1

        return {
            "state": self.state.to_dict(),
            "queue_size": len(self.queue),
            "total_tasks": len(self.tasks),
            "status_counts": status_counts,
        }
