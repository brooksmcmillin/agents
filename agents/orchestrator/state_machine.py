"""Core orchestrator state machine.

The orchestrator is a lightweight control plane that drives work through a
deterministic state machine:

    INGEST -> PLAN -> EXECUTE -> REVIEW -> COMPLETE
                                   |          |
                                   v          v
                              HUMAN_GATE   FAILED
                                   |
                                   v
                                COMPLETE

It is NOT an LLM agent. It invokes LLM agents at specific stages (planning,
review) but the flow control is deterministic based on task configuration
and review outcomes.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from typing import Any

from .models import (
    AutonomyTier,
    OrchestratorConfig,
    OrchestratorState,
    Phase,
    ReviewIssue,
    ReviewResult,
    ReviewVerdict,
    Task,
    TaskStatus,
)
from .planner import plan_task
from .reviewers import run_code_review, run_security_review
from .workers import dispatch_worker, ensure_workspace, get_workspace_diff

logger = logging.getLogger(__name__)


class Orchestrator:
    """Task-driven orchestration state machine.

    The orchestrator maintains a task registry and processes tasks through
    a deterministic pipeline. It does not make LLM-based routing decisions;
    routing is based on task configuration (autonomy tier) and review
    outcomes (pass/fail).

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

        # Callbacks for human gate and notifications
        self._on_human_approval_needed: list[Any] = []
        self._on_task_complete: list[Any] = []
        self._on_task_failed: list[Any] = []

    def add_task(self, task: Task) -> Task:
        """Add a task to the orchestrator.

        Args:
            task: Task to add.

        Returns:
            The task (with any modifications).
        """
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
            self.state.started_at = datetime.now()

        try:
            await self._process_task(task)
        except Exception as e:
            logger.exception(f"Unhandled error processing task {task.id}: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            self.state.tasks_failed += 1
            self.state.phase = Phase.FAILED
            await self._notify_failure(task)

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

        logger.info(
            f"Orchestrator run complete: {len(processed)} tasks processed, "
            f"{self.state.tasks_completed} completed, {self.state.tasks_failed} failed"
        )
        return processed

    async def _process_task(self, task: Task) -> None:
        """Process a single task through the full pipeline.

        Pipeline: INGEST -> PLAN -> EXECUTE -> REVIEW -> COMPLETE/HUMAN_GATE
        """
        # INGEST: Validate and prepare
        self.state.phase = Phase.INGEST
        task.started_at = datetime.now()

        if task.autonomy_tier == AutonomyTier.MANUAL_ONLY:
            logger.info(f"Task {task.id} is MANUAL_ONLY, notifying human")
            task.status = TaskStatus.AWAITING_HUMAN
            self.state.phase = Phase.HUMAN_GATE
            await self._notify_human_required(task)
            return

        # PLAN: Decompose into subtasks if this is a high-level task
        self.state.phase = Phase.PLAN
        task.status = TaskStatus.PLANNING

        if task.is_leaf() and self._should_decompose(task):
            subtasks = await self._plan_task(task)
            if len(subtasks) > 1:
                # This task becomes a parent; queue subtasks instead
                for subtask in subtasks:
                    self.add_task(subtask)
                    task.subtask_ids.append(subtask.id)
                task.status = TaskStatus.IN_PROGRESS
                logger.info(
                    f"Task {task.id} decomposed into {len(subtasks)} subtasks"
                )
                return

        # EXECUTE: Dispatch worker
        self.state.phase = Phase.EXECUTE
        task.status = TaskStatus.IN_PROGRESS
        await self._execute_task(task)

        if task.status == TaskStatus.FAILED:
            self.state.tasks_failed += 1
            self.state.phase = Phase.FAILED
            await self._notify_failure(task)
            return

        # REVIEW: Run review gates
        self.state.phase = Phase.REVIEW
        task.status = TaskStatus.IN_REVIEW
        review_passed = await self._review_task(task)

        if not review_passed:
            # Check if we should create remediation tasks
            await self._handle_review_failure(task)
            return

        # COMPLETE or HUMAN_GATE based on autonomy tier
        await self._finalize_task(task)

    def _should_decompose(self, task: Task) -> bool:
        """Determine if a task should be decomposed into subtasks.

        Tasks are NOT decomposed if:
        - They're already subtasks at max depth
        - They're already decomposed (have subtask_ids)
        - Their description is very short (likely already atomic)
        """
        if task.depth >= self.config.max_subtask_depth:
            return False
        if task.subtask_ids:
            return False
        # Short descriptions suggest atomic tasks
        if len(task.description) < 100:
            return False
        return True

    async def _plan_task(self, task: Task) -> list[Task]:
        """Plan/decompose a task into subtasks."""
        try:
            subtasks = await plan_task(
                task,
                max_subtasks=self.config.max_subtasks_per_task,
            )
            return subtasks
        except Exception as e:
            logger.error(f"Planning failed for task {task.id}: {e}")
            # Fall through to execute the task as-is
            return [task]

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
            self.state.total_worker_turns += result.turns_used

            if not result.success:
                task.status = TaskStatus.FAILED
                task.error = result.error or "Worker execution failed"
                logger.warning(f"Worker failed for task {task.id}: {task.error}")

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"Execution failed for task {task.id}: {e}")

    async def _review_task(self, task: Task) -> bool:
        """Run review gates on a completed task.

        Returns True if all reviews passed.
        """
        if not task.workspace_name or not task.branch_name:
            logger.warning(f"Task {task.id} has no workspace/branch for review, skipping")
            return True

        # Get the diff
        diff = await get_workspace_diff(task.workspace_name, task.branch_name)
        if not diff.strip():
            logger.info(f"No diff for task {task.id}, skipping review")
            return True

        all_passed = True

        # Code review
        if self.config.enable_code_review:
            code_result = await run_code_review(task, diff, self.config)
            task.review_results.append(code_result)
            if code_result.verdict == ReviewVerdict.PASSED:
                self.state.total_review_passes += 1
            else:
                self.state.total_review_failures += 1
                all_passed = False
            logger.info(
                f"Code review for task {task.id}: {code_result.verdict.value} "
                f"({len(code_result.issues)} issues)"
            )

        # Security review
        if self.config.enable_security_review:
            security_result = await run_security_review(task, diff, self.config)
            task.review_results.append(security_result)
            if security_result.verdict == ReviewVerdict.PASSED:
                self.state.total_review_passes += 1
            else:
                self.state.total_review_failures += 1
                all_passed = False
            logger.info(
                f"Security review for task {task.id}: {security_result.verdict.value} "
                f"({len(security_result.issues)} issues)"
            )

        return all_passed

    async def _handle_review_failure(self, task: Task) -> None:
        """Handle a task that failed review by creating remediation tasks.

        Collects issues from all review results and creates child tasks
        to fix them, subject to recursion depth limits.
        """
        all_issues: list[ReviewIssue] = []
        for result in task.review_results:
            if result.verdict != ReviewVerdict.PASSED:
                all_issues.extend(result.issues)

        if not all_issues:
            # Review failed but no specific issues -> mark as failed
            task.status = TaskStatus.FAILED
            task.error = "Review failed without specific issues"
            self.state.tasks_failed += 1
            await self._notify_failure(task)
            return

        # Check recursion limit
        if task.depth >= self.config.max_subtask_depth:
            logger.warning(
                f"Task {task.id} failed review at max depth {task.depth}, "
                f"cannot create remediation tasks"
            )
            task.status = TaskStatus.FAILED
            task.error = (
                f"Review failed at max recursion depth. "
                f"Issues: {[i.title for i in all_issues]}"
            )
            self.state.tasks_failed += 1
            await self._notify_failure(task)
            return

        # Create remediation tasks (limited count)
        remediation_count = min(len(all_issues), self.config.max_remediation_tasks)
        # Sort by severity (critical first)
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_issues = sorted(all_issues, key=lambda i: severity_order.get(i.severity, 2))

        for issue in sorted_issues[:remediation_count]:
            remediation = Task(
                title=issue.to_task_title(),
                description=(
                    f"{issue.description}\n\n"
                    f"File: {issue.file_path or 'N/A'}\n"
                    f"Suggestion: {issue.suggestion or 'N/A'}"
                ),
                parent_id=task.id,
                priority=issue.severity_to_priority(),
                tags=["auto-generated", "remediation"],
                autonomy_tier=task.autonomy_tier,
                category=task.category,
                depth=task.depth + 1,
                workspace_name=task.workspace_name,
                branch_name=task.branch_name,
            )
            self.add_task(remediation)
            task.subtask_ids.append(remediation.id)

        logger.info(
            f"Created {remediation_count} remediation tasks for task {task.id}"
        )
        task.status = TaskStatus.IN_PROGRESS  # Parent stays in progress

    async def _finalize_task(self, task: Task) -> None:
        """Finalize a task based on its autonomy tier after review passes."""
        match task.autonomy_tier:
            case AutonomyTier.AUTO_MERGE:
                # Auto-complete
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
                self.state.tasks_completed += 1
                self.state.phase = Phase.COMPLETE
                logger.info(f"Task {task.id} auto-completed (tier 1)")
                await self._notify_complete(task)

            case AutonomyTier.PROPOSE_EXECUTE:
                # Complete but notify human
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now()
                self.state.tasks_completed += 1
                self.state.phase = Phase.COMPLETE
                logger.info(f"Task {task.id} completed, notifying human (tier 2)")
                await self._notify_complete(task)

            case AutonomyTier.PROPOSE_WAIT:
                # Wait for human approval
                task.status = TaskStatus.AWAITING_HUMAN
                self.state.phase = Phase.HUMAN_GATE
                logger.info(f"Task {task.id} awaiting human approval (tier 3)")
                await self._notify_human_required(task)

            case AutonomyTier.MANUAL_ONLY:
                # Should not reach here, but handle gracefully
                task.status = TaskStatus.AWAITING_HUMAN
                self.state.phase = Phase.HUMAN_GATE
                await self._notify_human_required(task)

    # ------------------------------------------------------------------
    # Notification hooks
    # ------------------------------------------------------------------

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

    def approve_task(self, task_id: str) -> bool:
        """Approve a task that is awaiting human approval.

        Args:
            task_id: ID of the task to approve.

        Returns:
            True if the task was approved, False if not found or not awaiting.
        """
        task = self.tasks.get(task_id)
        if not task or task.status != TaskStatus.AWAITING_HUMAN:
            return False

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        self.state.tasks_completed += 1
        logger.info(f"Task {task_id} approved by human")
        return True

    def reject_task(self, task_id: str, reason: str = "") -> bool:
        """Reject a task that is awaiting human approval.

        Args:
            task_id: ID of the task to reject.
            reason: Reason for rejection.

        Returns:
            True if the task was rejected, False if not found or not awaiting.
        """
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
