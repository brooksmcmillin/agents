"""Task queue runner - automated batch processing of TaskManager tasks.

Fetches actionable tasks from TaskManager via MCP, triages them with LLM,
and routes to orchestrator execution, pre-research, or blocking.

Extends BatchAgent for MCP connectivity. Not an interactive agent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date

from agent_framework.tools import send_slack_message

from agents.orchestrator.models import AutonomyTier, OrchestratorConfig, Task
from agents.orchestrator.state_machine import Orchestrator
from shared import BatchAgent, parse_task_result

from .dependency_graph import compute_processing_order, identify_blocked_tasks
from .lightweight_executor import execute_lightweight
from .models import (
    ProcessedTask,
    RunReport,
    TaskContext,
    TaskQueueConfig,
    TriageResult,
    TriageVerdict,
    _utcnow,
)
from .pre_research import do_pre_research
from .triage import triage_task

logger = logging.getLogger(__name__)

# Max characters for comment content posted to tasks.
COMMENT_MAX_LENGTH = 1000


def _normalize_task_id(task_id: str) -> str:
    """Ensure task ID has the ``task_`` prefix."""
    if not task_id.startswith("task_"):
        return f"task_{task_id}"
    return task_id


class TaskQueueRunner(BatchAgent):
    """Batch agent that processes TaskManager tasks through triage and execution.

    Pipeline:
        1. Fetch actionable tasks (overdue + today)
        2. Bump overdue priorities
        3. Fetch dependency graph
        4. Compute processing order
        5. For each ready task: triage -> route (execute/research/block)
        6. Send batch notification
    """

    def __init__(self, config: TaskQueueConfig | None = None) -> None:
        self.config = config or TaskQueueConfig()
        super().__init__(mcp_url=self.config.mcp_url)
        self.context = TaskContext()
        self.report = RunReport(dry_run=self.config.dry_run)

    def get_name(self) -> str:
        return "TaskQueueRunner"

    async def _add_comment(self, task_id: str, content: str) -> None:
        """Add a comment to a task, logging failures without raising."""
        try:
            await self.call_tool(
                "add_task_comment",
                {"task_id": task_id, "content": content[:COMMENT_MAX_LENGTH]},
            )
        except Exception as e:
            logger.warning(f"Failed to add comment to {task_id}: {e}")

    async def execute(self) -> None:
        """Run the full task queue pipeline."""
        logger.info(
            f"Starting task queue run "
            f"(dry_run={self.config.dry_run}, max_tasks={self.config.max_tasks})"
        )

        # Phase 1: Fetch actionable tasks
        if self.config.task_ids:
            tasks = await self._fetch_specific_tasks(self.config.task_ids)
        else:
            tasks = await self._fetch_actionable_tasks()
        if not tasks:
            logger.info("No actionable tasks found")
            print("No actionable tasks found.")
            return

        self.report.total_fetched = len(tasks)
        logger.info(f"Fetched {len(tasks)} actionable tasks")

        # Phase 2: Bump overdue priorities
        if self.config.priority_bump_overdue:
            await self._bump_overdue_priorities(tasks)

        # Phase 3: Fetch dependency graph
        dependencies = await self._fetch_dependencies(tasks)

        # Phase 4: Compute processing order
        ordered_tasks = compute_processing_order(tasks, dependencies)
        blocked = identify_blocked_tasks(tasks, dependencies)
        logger.info(
            f"Processing order computed: {len(ordered_tasks)} tasks, {len(blocked)} blocked"
        )

        # Phase 5: Process each task
        processed_count = 0
        for task in ordered_tasks:
            if processed_count >= self.config.max_tasks:
                logger.info(f"Reached max_tasks limit ({self.config.max_tasks})")
                break

            task_id = task.get("id", "unknown")

            # Skip blocked tasks
            if task_id in blocked:
                blockers = blocked[task_id]
                logger.info(f"Skipping {task_id}: blocked by {blockers}")
                self.report.tasks_processed.append(
                    ProcessedTask(
                        external_id=task_id,
                        title=task.get("title", ""),
                        triage_verdict=TriageVerdict.SKIP_DEPENDENCIES,
                        confidence=1.0,
                        outcome="skipped",
                        notes=f"Blocked by: {', '.join(blockers)}",
                    )
                )
                self.context.skipped_ids.append(task_id)
                processed_count += 1
                continue

            await self._process_single_task(task)
            processed_count += 1

        # Phase 6: Send notification
        self.report.completed_at = _utcnow()
        await self._send_batch_notification()

        # Print summary
        print("\n" + self.report.format_summary())

    async def _fetch_specific_tasks(self, task_ids: list[str]) -> list[dict]:
        """Fetch specific tasks by ID from TaskManager via MCP."""
        tasks: list[dict] = []
        for task_id in task_ids:
            task_id = _normalize_task_id(task_id)
            try:
                result = await self.call_tool("get_task", {"task_id": task_id})
                data = json.loads(result) if isinstance(result, str) else result
                if "error" in data:
                    logger.error(f"Failed to fetch {task_id}: {data['error']}")
                    continue
                # get_task wraps task data inside a "task" key
                task_data = data.get("task", data)
                tasks.append(task_data)
                logger.info(f"Fetched task {task_id}: {data.get('title', '')[:60]}")
            except Exception as e:
                logger.error(f"Failed to fetch {task_id}: {e}")
        return tasks

    async def _fetch_actionable_tasks(self) -> list[dict]:
        """Fetch overdue and today's tasks from TaskManager via MCP."""
        all_tasks: list[dict] = []
        today_str = date.today().isoformat()

        # Fetch today's tasks
        try:
            today_result = await self.call_tool(
                "get_tasks",
                {"status": "pending", "start_date": today_str, "end_date": today_str},
            )
            today_tasks = parse_task_result(today_result)
            all_tasks.extend(today_tasks)
            logger.info(f"Fetched {len(today_tasks)} tasks due today")
        except Exception as e:
            logger.error(f"Failed to fetch today's tasks: {e}")

        # Fetch overdue tasks
        if self.config.include_overdue:
            try:
                overdue_result = await self.call_tool("get_tasks", {"status": "overdue"})
                overdue_tasks = parse_task_result(overdue_result)
                all_tasks.extend(overdue_tasks)
                logger.info(f"Fetched {len(overdue_tasks)} overdue tasks")
            except Exception as e:
                logger.error(f"Failed to fetch overdue tasks: {e}")

        # Deduplicate by ID
        seen: set[str] = set()
        unique_tasks: list[dict] = []
        for task in all_tasks:
            task_id = task.get("id", "")
            if task_id and task_id not in seen:
                seen.add(task_id)
                unique_tasks.append(task)

        # Sort: due_date ASC, then priority DESC
        def sort_key(t: dict) -> tuple:
            due = t.get("due_date") or "9999-99-99"
            # Invert priority for DESC (higher priority first)
            priority_map = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
            priority = priority_map.get(str(t.get("priority", "medium")).lower(), 2)
            return (due, priority)

        unique_tasks.sort(key=sort_key)
        return unique_tasks

    async def _bump_overdue_priorities(self, tasks: list[dict]) -> None:
        """Bump priority of overdue low/medium tasks to high."""
        today_str = date.today().isoformat()
        for task in tasks:
            due_date = task.get("due_date")
            if not due_date or due_date >= today_str:
                continue

            priority = str(task.get("priority", "")).lower()
            if priority in ("low", "medium"):
                task_id = task.get("id", "")
                try:
                    await self.call_tool(
                        "update_task",
                        {"task_id": task_id, "priority": "high"},
                    )
                    task["priority"] = "high"
                    logger.info(f"Bumped priority of overdue task {task_id} to high")
                    await self._add_comment(
                        task_id,
                        f"Priority bumped from {priority} to high (task is overdue, due {due_date})",
                    )
                except Exception as e:
                    logger.warning(f"Failed to bump priority for {task_id}: {e}")

    async def _fetch_dependencies(self, tasks: list[dict]) -> dict[str, list[dict]]:
        """Fetch dependency graph for all tasks via MCP."""
        dependencies: dict[str, list[dict]] = {}
        for task in tasks:
            task_id = task.get("id", "")
            if not task_id:
                continue
            try:
                result = await self.call_tool("list_dependencies", {"task_id": task_id})
                data = json.loads(result) if isinstance(result, str) else result
                deps = data.get("dependencies", [])
                if deps:
                    dependencies[task_id] = deps
            except Exception as e:
                logger.warning(f"Failed to fetch dependencies for {task_id}: {e}")
        return dependencies

    async def _process_single_task(self, task: dict) -> None:
        """Process a single task through triage and routing."""
        task_id = task.get("id", "unknown")
        title = task.get("title", "Untitled")

        # Skip if already processing
        agent_status = task.get("agent_status")
        if agent_status in ("in_progress", "completed"):
            logger.info(f"Skipping {task_id}: already {agent_status}")
            self.report.tasks_processed.append(
                ProcessedTask(
                    external_id=task_id,
                    title=title,
                    triage_verdict=TriageVerdict.SKIP_ALREADY_PROCESSING,
                    confidence=1.0,
                    outcome="skipped",
                    notes=f"Already {agent_status}",
                )
            )
            self.context.skipped_ids.append(task_id)
            return

        # Skip if task already has subtasks (previously decomposed)
        existing_subtasks = task.get("subtasks") or []
        if existing_subtasks:
            subtask_titles = [s.get("title", "") for s in existing_subtasks[:5]]
            logger.info(f"Skipping {task_id}: already has {len(existing_subtasks)} subtasks")
            self.report.tasks_processed.append(
                ProcessedTask(
                    external_id=task_id,
                    title=title,
                    triage_verdict=TriageVerdict.SKIP_ALREADY_PROCESSING,
                    confidence=1.0,
                    outcome="skipped",
                    notes=f"Already decomposed into {len(existing_subtasks)} subtasks: {subtask_titles}",
                )
            )
            self.context.skipped_ids.append(task_id)
            return

        # Mark as in_progress
        try:
            await self.call_tool(
                "set_agent_status",
                {"task_id": task_id, "status": "in_progress"},
            )
        except Exception as e:
            logger.warning(f"Failed to set in_progress for {task_id}: {e}")

        # Triage and route — reset status on unexpected failure so the task
        # doesn't stay stuck in in_progress indefinitely.
        try:
            await self._triage_and_route(task, task_id, title)
        except Exception as e:
            logger.error(f"Triage/routing failed for {task_id}: {e}")
            try:
                await self.call_tool(
                    "set_agent_status",
                    {
                        "task_id": task_id,
                        "status": "blocked",
                        "blocking_reason": f"Triage/routing error: {str(e)[:180]}",
                    },
                )
            except Exception:
                logger.debug("Failed to reset status for %s after triage failure", task_id)
            await self._add_comment(task_id, f"Processing failed: {str(e)[:500]}")
            self.report.tasks_processed.append(
                ProcessedTask(
                    external_id=task_id,
                    title=title,
                    triage_verdict=TriageVerdict.NOT_ACTIONABLE,
                    confidence=0.0,
                    outcome="failed",
                    error=str(e),
                )
            )
            self.context.failed_ids.append(task_id)

    async def _triage_and_route(self, task: dict, task_id: str, title: str) -> None:
        """Run triage and route the task to the appropriate executor."""
        accumulated_context = self.context.get_related_context(title, task.get("description", ""))
        triage = await triage_task(
            task=task,
            available_tools=[],  # We don't enumerate tools here
            accumulated_context=accumulated_context,
            model=self.config.triage_model,
        )

        # Classify in TaskManager if unclassified
        if not task.get("action_type") and triage.suggested_action_type:
            try:
                classify_args: dict = {
                    "task_id": task_id,
                    "action_type": triage.suggested_action_type,
                    "agent_actionable": triage.verdict == TriageVerdict.FULLY_EXECUTABLE,
                }
                if triage.suggested_autonomy_tier:
                    classify_args["autonomy_tier"] = triage.suggested_autonomy_tier
                await self.call_tool("classify_task", classify_args)
            except Exception as e:
                logger.warning(f"Failed to classify {task_id}: {e}")

        # Comment with triage decision
        triage_comment = (
            f"**Triage:** {triage.verdict.value} "
            f"(confidence: {triage.confidence:.0%})\n"
            f"{triage.reasoning}"
        )
        if triage.suggested_action_type:
            triage_comment += f"\nAction type: {triage.suggested_action_type}"
        if triage.estimated_hours:
            triage_comment += f"\nEstimated hours: {triage.estimated_hours}"
        await self._add_comment(task_id, triage_comment)

        # Dry run: log and reset
        if self.config.dry_run:
            logger.info(
                f"[DRY RUN] {task_id}: {triage.verdict.value} (confidence={triage.confidence:.0%})"
            )
            self.report.tasks_processed.append(
                ProcessedTask(
                    external_id=task_id,
                    title=title,
                    triage_verdict=triage.verdict,
                    confidence=triage.confidence,
                    outcome="skipped",
                    notes=f"Dry run. {triage.reasoning}",
                    estimated_hours=triage.estimated_hours,
                )
            )
            # Reset agent status
            try:
                await self.call_tool(
                    "set_agent_status",
                    {"task_id": task_id, "status": "pending_review"},
                )
            except Exception:
                logger.debug("Failed to reset agent status for %s after dry-run", task_id)
            return

        # Route by verdict
        match triage.verdict:
            case TriageVerdict.FULLY_EXECUTABLE:
                if self._should_use_lightweight(triage):
                    await self._execute_lightweight_task(task, triage)
                else:
                    await self._execute_task(task, triage)
            case TriageVerdict.PRE_RESEARCH_ONLY:
                await self._pre_research_task(task, triage)
            case TriageVerdict.NOT_ACTIONABLE:
                await self._mark_not_actionable(task, triage)
            case _:
                logger.warning(f"Unexpected triage verdict: {triage.verdict}")

    async def _execute_task(self, task: dict, triage: TriageResult) -> None:
        """Execute a task via the orchestrator state machine."""
        task_id = task.get("id", "unknown")
        title = task.get("title", "Untitled")

        try:
            # Convert to orchestrator Task
            orch_task = self._to_orchestrator_task(task, triage)

            # Create orchestrator instance
            # max_subtask_depth=1: decompose once, don't recursively explode.
            # The task queue handles high-level decomposition; the orchestrator
            # should split into atomic subtasks and execute them.
            orch_config = OrchestratorConfig(
                worker_model=self.config.worker_model,
                enable_code_review=self.config.enable_code_review,
                enable_security_review=self.config.enable_security_review,
                max_subtask_depth=1,
            )
            orch = Orchestrator(
                config=orch_config,
                git_repo_url=self.config.git_repo_url,
            )

            # Add task and run
            orch.add_task(orch_task)
            results = await orch.run(max_tasks=10)

            # Always sync subtasks to TaskManager (even if execution failed)
            await self._sync_subtasks_to_taskmanager(task_id, orch, orch_task)

            # Determine outcome
            if not results:
                raise RuntimeError("Orchestrator produced no results")

            root_result = results[0]

            if root_result.status.value == "completed":
                # Sync completion back to TaskManager
                try:
                    await self.call_tool("complete_task", {"task_id": task_id})
                except Exception as e:
                    logger.warning(f"Failed to complete task in TM: {e}")

                # Comment with completion details
                completion_comment = "Task completed via orchestrator."
                if root_result.branch_name:
                    completion_comment += f"\nBranch: `{root_result.branch_name}`"
                if root_result.worker_output:
                    output_preview = root_result.worker_output[:500]
                    completion_comment += f"\n\nOutput:\n{output_preview}"
                await self._add_comment(task_id, completion_comment)

                self.report.tasks_processed.append(
                    ProcessedTask(
                        external_id=task_id,
                        title=title,
                        triage_verdict=triage.verdict,
                        confidence=triage.confidence,
                        outcome="completed",
                        notes=root_result.worker_output or "",
                        estimated_hours=triage.estimated_hours,
                        orchestrator_task_id=root_result.id,
                        branch_name=root_result.branch_name,
                    )
                )
                self.context.completed_ids.append(task_id)

            elif root_result.status.value == "awaiting_human":
                # Worker ran but needs human review — not "completed"
                has_changes = bool(root_result.branch_name and root_result.worker_output)
                note = (
                    f"Worker finished, awaiting human review"
                    f"{f' on branch {root_result.branch_name}' if root_result.branch_name else ''}"
                    f"{' (no code changes produced)' if not has_changes else ''}"
                )
                try:
                    await self.call_tool(
                        "set_agent_status",
                        {"task_id": task_id, "status": "needs_human"},
                    )
                    await self.call_tool(
                        "add_agent_note",
                        {"task_id": task_id, "note": note},
                    )
                except Exception as e:
                    logger.warning(f"Failed to set needs_human: {e}")

                await self._add_comment(task_id, f"Needs human review: {note}")

                self.report.tasks_processed.append(
                    ProcessedTask(
                        external_id=task_id,
                        title=title,
                        triage_verdict=triage.verdict,
                        confidence=triage.confidence,
                        outcome="needs_human",
                        notes=note,
                        orchestrator_task_id=root_result.id,
                        branch_name=root_result.branch_name,
                    )
                )
            elif root_result.status.value in ("in_progress", "planning", "in_review"):
                # Orchestrator ran out of steps but task isn't done yet.
                # This is normal for large tasks — subtasks were written back.
                summary = orch.get_status_summary()
                note = (
                    f"Orchestrator partially complete: "
                    f"{summary['status_counts']}. "
                    f"Subtasks written to TaskManager."
                )
                try:
                    await self.call_tool(
                        "add_agent_note",
                        {"task_id": task_id, "note": note},
                    )
                    await self.call_tool(
                        "set_agent_status",
                        {"task_id": task_id, "status": "in_progress"},
                    )
                except Exception as e:
                    logger.warning(f"Failed to update partial status: {e}")

                await self._add_comment(task_id, f"Partially complete: {note}")

                self.report.tasks_processed.append(
                    ProcessedTask(
                        external_id=task_id,
                        title=title,
                        triage_verdict=triage.verdict,
                        confidence=triage.confidence,
                        outcome="completed",
                        notes=note,
                        orchestrator_task_id=root_result.id,
                    )
                )
                self.context.completed_ids.append(task_id)

            else:
                # Actually failed
                error_msg = root_result.error or f"Orchestrator status: {root_result.status.value}"
                try:
                    await self.call_tool(
                        "set_agent_status",
                        {
                            "task_id": task_id,
                            "status": "blocked",
                            "blocking_reason": error_msg[:200],
                        },
                    )
                    await self.call_tool(
                        "add_agent_note",
                        {"task_id": task_id, "note": f"Execution failed: {error_msg}"},
                    )
                except Exception as e:
                    logger.warning(f"Failed to update task status: {e}")

                await self._add_comment(task_id, f"Execution failed: {error_msg[:500]}")

                self.report.tasks_processed.append(
                    ProcessedTask(
                        external_id=task_id,
                        title=title,
                        triage_verdict=triage.verdict,
                        confidence=triage.confidence,
                        outcome="failed",
                        error=error_msg,
                        orchestrator_task_id=root_result.id,
                    )
                )
                self.context.failed_ids.append(task_id)

        except Exception as e:
            logger.error(f"Execution failed for {task_id}: {e}")
            try:
                await self.call_tool(
                    "set_agent_status",
                    {
                        "task_id": task_id,
                        "status": "blocked",
                        "blocking_reason": str(e)[:200],
                    },
                )
            except Exception:
                logger.debug("Failed to set blocked status for %s", task_id)

            await self._add_comment(task_id, f"Execution failed with exception: {str(e)[:500]}")

            self.report.tasks_processed.append(
                ProcessedTask(
                    external_id=task_id,
                    title=title,
                    triage_verdict=triage.verdict,
                    confidence=triage.confidence,
                    outcome="failed",
                    error=str(e),
                )
            )
            self.context.failed_ids.append(task_id)

    def _should_use_lightweight(self, triage: TriageResult) -> bool:
        """Determine if a task should use the lightweight executor.

        Returns True for non-code tasks, or code tasks without a configured repo.
        """
        action = triage.suggested_action_type
        if action != "code":
            return True
        # Code task but no repo configured — can't use orchestrator
        if not self.config.git_repo_url:
            return True
        return False

    async def _execute_lightweight_task(self, task: dict, triage: TriageResult) -> None:
        """Execute a non-code task via the lightweight executor."""
        task_id = task.get("id", "unknown")
        title = task.get("title", "Untitled")
        action_type = triage.suggested_action_type or "other"

        logger.info(f"Routing {task_id} to lightweight executor (action_type={action_type})")

        try:
            result = await execute_lightweight(
                task=task,
                call_tool=self.call_tool,
                list_tools=self.list_tools,
                model=self.config.lightweight_model,
            )

            if result.success:
                # Complete the task in TaskManager
                try:
                    await self.call_tool("complete_task", {"task_id": task_id})
                except Exception as e:
                    logger.warning(f"Failed to complete task in TM: {e}")

                # Store output as agent note
                note = f"Lightweight execution ({result.turns_used} turns):\n{result.output[:500]}"
                try:
                    await self.call_tool(
                        "add_agent_note",
                        {"task_id": task_id, "note": note},
                    )
                except Exception as e:
                    logger.warning(f"Failed to add agent note: {e}")

                # Comment with execution results
                output_preview = result.output[:800] if result.output else "No output"
                await self._add_comment(
                    task_id,
                    f"Completed ({action_type}, {result.turns_used} turns):\n\n{output_preview}",
                )

                # Accumulate context for subsequent tasks
                self.context.research_notes[task_id] = result.output[:1000]

                self.report.tasks_processed.append(
                    ProcessedTask(
                        external_id=task_id,
                        title=title,
                        triage_verdict=triage.verdict,
                        confidence=triage.confidence,
                        outcome="completed",
                        notes=f"Lightweight ({action_type}, {result.turns_used} turns)",
                        estimated_hours=triage.estimated_hours,
                    )
                )
                self.context.completed_ids.append(task_id)

            else:
                error_msg = result.error or "Lightweight execution failed"
                try:
                    await self.call_tool(
                        "set_agent_status",
                        {
                            "task_id": task_id,
                            "status": "blocked",
                            "blocking_reason": error_msg[:200],
                        },
                    )
                    if result.output:
                        await self.call_tool(
                            "add_agent_note",
                            {
                                "task_id": task_id,
                                "note": f"Partial output:\n{result.output[:500]}",
                            },
                        )
                except Exception as e:
                    logger.warning(f"Failed to update task status: {e}")

                fail_comment = f"Lightweight execution failed: {error_msg[:300]}"
                if result.output:
                    fail_comment += f"\n\nPartial output:\n{result.output[:500]}"
                await self._add_comment(task_id, fail_comment)

                self.report.tasks_processed.append(
                    ProcessedTask(
                        external_id=task_id,
                        title=title,
                        triage_verdict=triage.verdict,
                        confidence=triage.confidence,
                        outcome="failed",
                        error=error_msg,
                        estimated_hours=triage.estimated_hours,
                    )
                )
                self.context.failed_ids.append(task_id)

        except Exception as e:
            logger.error(f"Lightweight execution failed for {task_id}: {e}")
            try:
                await self.call_tool(
                    "set_agent_status",
                    {
                        "task_id": task_id,
                        "status": "blocked",
                        "blocking_reason": str(e)[:200],
                    },
                )
            except Exception:
                logger.debug("Failed to set blocked status for %s", task_id)

            await self._add_comment(
                task_id, f"Lightweight execution failed with exception: {str(e)[:500]}"
            )

            self.report.tasks_processed.append(
                ProcessedTask(
                    external_id=task_id,
                    title=title,
                    triage_verdict=triage.verdict,
                    confidence=triage.confidence,
                    outcome="failed",
                    error=str(e),
                )
            )
            self.context.failed_ids.append(task_id)

    async def _pre_research_task(self, task: dict, triage: TriageResult) -> None:
        """Perform pre-research for a task and store findings."""
        task_id = task.get("id", "unknown")
        title = task.get("title", "Untitled")

        try:
            summary = await do_pre_research(
                task=task,
                search_queries=triage.pre_research_queries,
                call_tool=self.call_tool,
                model=self.config.research_model,
            )

            # Store research notes via MCP
            await self.call_tool(
                "add_agent_note",
                {"task_id": task_id, "note": f"Pre-research findings:\n{summary}"},
            )

            # Set status to pending_review
            await self.call_tool(
                "set_agent_status",
                {"task_id": task_id, "status": "pending_review"},
            )

            # Comment with research findings
            await self._add_comment(task_id, f"Pre-research findings:\n\n{summary[:1000]}")

            # Accumulate context for subsequent tasks
            self.context.research_notes[task_id] = summary

            self.report.tasks_processed.append(
                ProcessedTask(
                    external_id=task_id,
                    title=title,
                    triage_verdict=triage.verdict,
                    confidence=triage.confidence,
                    outcome="researched",
                    notes=summary[:200],
                    estimated_hours=triage.estimated_hours,
                )
            )

        except Exception as e:
            logger.error(f"Pre-research failed for {task_id}: {e}")
            try:
                await self.call_tool(
                    "add_agent_note",
                    {"task_id": task_id, "note": f"Pre-research failed: {e}"},
                )
                await self.call_tool(
                    "set_agent_status",
                    {
                        "task_id": task_id,
                        "status": "blocked",
                        "blocking_reason": f"Pre-research failed: {e}",
                    },
                )
            except Exception:
                logger.debug("Failed to set blocked status for %s", task_id)

            await self._add_comment(task_id, f"Pre-research failed: {str(e)[:500]}")

            self.report.tasks_processed.append(
                ProcessedTask(
                    external_id=task_id,
                    title=title,
                    triage_verdict=triage.verdict,
                    confidence=triage.confidence,
                    outcome="failed",
                    error=str(e),
                )
            )
            self.context.failed_ids.append(task_id)

    async def _mark_not_actionable(self, task: dict, triage: TriageResult) -> None:
        """Mark a task as not actionable by the agent."""
        task_id = task.get("id", "unknown")
        title = task.get("title", "Untitled")

        blocking_reason = triage.blocking_reason or triage.reasoning or "Not actionable by agent"

        try:
            await self.call_tool(
                "add_agent_note",
                {
                    "task_id": task_id,
                    "note": f"Not actionable: {blocking_reason}",
                },
            )
            await self.call_tool(
                "set_agent_status",
                {
                    "task_id": task_id,
                    "status": "blocked",
                    "blocking_reason": blocking_reason[:200],
                },
            )
        except Exception as e:
            logger.warning(f"Failed to mark {task_id} as not actionable: {e}")

        await self._add_comment(task_id, f"Not actionable by agent: {blocking_reason[:500]}")

        self.report.tasks_processed.append(
            ProcessedTask(
                external_id=task_id,
                title=title,
                triage_verdict=triage.verdict,
                confidence=triage.confidence,
                outcome="blocked",
                notes=blocking_reason,
            )
        )

    async def _sync_subtasks_to_taskmanager(
        self,
        parent_id: str,
        orch: Orchestrator,
        orch_task: Task,
    ) -> None:
        """Write orchestrator-generated subtasks back to TaskManager."""
        subtasks = orch.get_subtasks(orch_task.id)
        if not subtasks:
            return

        created_titles: list[str] = []
        for subtask in subtasks:
            try:
                await self.call_tool(
                    "create_task",
                    {
                        "title": subtask.title,
                        "description": subtask.description,
                        "parent_id": parent_id,
                        "priority": _priority_int_to_text(subtask.priority),
                        "tags": subtask.tags,
                    },
                )
                created_titles.append(subtask.title)
                logger.info(f"Created subtask in TaskManager: {subtask.title} (parent={parent_id})")
            except Exception as e:
                logger.warning(f"Failed to create subtask in TM: {e}")

        if created_titles:
            subtask_list = "\n".join(f"- {t}" for t in created_titles)
            await self._add_comment(
                parent_id,
                f"Created {len(created_titles)} subtask(s):\n{subtask_list}",
            )

    def _to_orchestrator_task(self, mcp_task: dict, triage: TriageResult) -> Task:
        """Convert an MCP task dict to an orchestrator Task model."""
        priority_text = str(mcp_task.get("priority", "medium")).lower()
        priority_map = {"low": 2, "medium": 5, "high": 8, "urgent": 10}
        priority = priority_map.get(priority_text, 5)

        # Determine autonomy tier
        tier_value = triage.suggested_autonomy_tier or mcp_task.get("autonomy_tier") or 2
        try:
            autonomy_tier = AutonomyTier(tier_value)
        except ValueError:
            autonomy_tier = AutonomyTier.PROPOSE_EXECUTE

        return Task(
            title=mcp_task.get("title", "Untitled"),
            description=mcp_task.get("description", ""),
            priority=priority,
            autonomy_tier=autonomy_tier,
            tags=mcp_task.get("tags", []),
            category=mcp_task.get("category", ""),
            external_id=mcp_task.get("id"),
        )

    async def _send_batch_notification(self) -> None:
        """Send batch notification via Slack and/or email."""
        if not self.report.tasks_processed:
            return

        # Slack notification
        webhook_url = self.config.slack_webhook_url or os.getenv("SLACK_WEBHOOK_URL")
        if webhook_url:
            try:
                message = self.report.format_slack_message()
                await send_slack_message(
                    text=message,
                    webhook_url=webhook_url,
                    username="Task Queue Runner",
                    icon_emoji=":robot_face:",
                )
                logger.info("Slack notification sent")
            except Exception as e:
                logger.warning(f"Failed to send Slack notification: {e}")

        # Email report
        if self.config.send_email_report:
            try:
                await self.call_tool(
                    "send_agent_report",
                    {
                        "subject": f"Task Queue Run: {len(self.report.tasks_processed)} tasks processed",
                        "body": self.report.format_summary(),
                    },
                )
                logger.info("Email report sent")
            except Exception as e:
                logger.warning(f"Failed to send email report: {e}")


def _priority_int_to_text(priority: int) -> str:
    """Convert integer priority (1-10) to text for TaskManager."""
    if priority >= 9:
        return "urgent"
    if priority >= 7:
        return "high"
    if priority >= 4:
        return "medium"
    return "low"
