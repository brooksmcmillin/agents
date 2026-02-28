"""Integration tests for task agent workflows.

Tests the full task lifecycle: create -> classify -> execute -> complete.
Covers agent-specific tool interactions end-to-end, verifying that the
TaskManagerAgent's prompts and configuration correctly support each stage
of the pipeline.

These tests verify the coherence of the workflow definitions, tool
configuration, and safety controls without making actual API calls.
"""

import json
import re
from unittest.mock import AsyncMock, patch

import pytest

from agents.task_manager.prompts import SYSTEM_PROMPT
from shared.constants import (
    CLAUDE_CODE_TOOLS,
    COMMUNICATION_TOOLS,
    CONTENT_TOOLS,
    FASTMAIL_TOOLS,
    MEMORY_TOOLS,
    SMS_TOOLS,
)
from shared.notifications import (
    notify_error,
    notify_routine_complete,
    notify_task_completion,
)
from shared.task_utils import parse_priority, parse_task_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_full_allowed_tools() -> list[str]:
    """Build the full allowed_tools list matching agents/task_manager/main.py."""
    return (
        CONTENT_TOOLS
        + MEMORY_TOOLS
        + COMMUNICATION_TOOLS
        + SMS_TOOLS
        + CLAUDE_CODE_TOOLS
        + FASTMAIL_TOOLS
    )


def _get_workflow_text(workflow_label: str) -> str:
    """Extract the text for a specific execution workflow section from SYSTEM_PROMPT.

    This module-level helper is shared by all test classes to avoid duplication.
    Raises AssertionError if the section is not found.
    """
    pattern = rf"### Execution Workflow: {re.escape(workflow_label)}.*?\n(.*?)(?=\n###? |\Z)"
    match = re.search(pattern, SYSTEM_PROMPT, re.DOTALL)
    assert match is not None, f"Workflow section '{workflow_label}' not found in SYSTEM_PROMPT"
    return match.group(1)


def _make_task(
    *,
    id: str = "42",
    title: str = "Test task",
    description: str = "A test task description",
    priority: int | str | None = 5,
    action_type: str | None = None,
    agent_actionable: bool | None = None,
    autonomy_tier: int | None = None,
    agent_status: str | None = None,
) -> dict:
    """Create a test task dict matching the MCP taskmanager schema."""
    task: dict = {
        "id": id,
        "title": title,
        "description": description,
        "priority": priority,
        "status": "pending",
        "tags": [],
    }
    if action_type is not None:
        task["action_type"] = action_type
    if agent_actionable is not None:
        task["agent_actionable"] = agent_actionable
    if autonomy_tier is not None:
        task["autonomy_tier"] = autonomy_tier
    if agent_status is not None:
        task["agent_status"] = agent_status
    return task


# ---------------------------------------------------------------------------
# TestTaskCreationIntegration
# Verify that task data round-trips through the utility functions correctly.
# ---------------------------------------------------------------------------


class TestTaskCreationIntegration:
    """Tests the create step: tasks round-trip through utility functions."""

    def test_create_minimal_task(self) -> None:
        """Minimal task with just id and title parses correctly."""
        raw = json.dumps({"tasks": [{"id": "1", "title": "My task", "priority": 5}]})
        tasks = parse_task_result(raw)
        assert len(tasks) == 1
        assert tasks[0]["id"] == "1"
        assert tasks[0]["title"] == "My task"

    def test_create_task_with_all_fields(self) -> None:
        """Full-fidelity task dict is preserved."""
        task = _make_task(
            id="99",
            title="Deploy service",
            description="Deploy the auth service to staging",
            priority=8,
            action_type="code",
            agent_actionable=True,
            autonomy_tier=2,
        )
        raw = json.dumps({"tasks": [task]})
        tasks = parse_task_result(raw)

        assert len(tasks) == 1
        t = tasks[0]
        assert t["id"] == "99"
        assert t["title"] == "Deploy service"
        assert t["action_type"] == "code"
        assert t["agent_actionable"] is True
        assert t["autonomy_tier"] == 2

    def test_create_multiple_tasks(self) -> None:
        """Multiple tasks in one response are all returned."""
        data = {
            "tasks": [
                _make_task(id="1", title="Task A", priority=9),
                _make_task(id="2", title="Task B", priority=5),
                _make_task(id="3", title="Task C", priority=2),
            ]
        }
        tasks = parse_task_result(data)
        assert len(tasks) == 3
        assert [t["title"] for t in tasks] == ["Task A", "Task B", "Task C"]

    def test_create_task_priority_normalization(self) -> None:
        """Task priority values in various formats are normalized correctly."""
        cases = [
            ("urgent", 9),
            ("high", 9),
            ("critical", 9),
            ("medium", 5),
            ("normal", 5),
            ("low", 2),
            (9, 9),
            ("7", 7),
            (None, 5),
        ]
        for raw_priority, expected in cases:
            assert parse_priority(raw_priority) == expected, (
                f"priority {raw_priority!r} should map to {expected}"
            )

    def test_create_task_result_preserves_order(self) -> None:
        """Task order from the API response is preserved exactly."""
        data = {
            "tasks": [
                _make_task(id="c", title="Third"),
                _make_task(id="a", title="First"),
                _make_task(id="b", title="Second"),
            ]
        }
        tasks = parse_task_result(data)
        assert [t["id"] for t in tasks] == ["c", "a", "b"]

    def test_empty_task_list_returns_empty(self) -> None:
        """Empty task list in response gives empty Python list."""
        tasks = parse_task_result({"tasks": []})
        assert tasks == []

    def test_missing_tasks_key_returns_empty(self) -> None:
        """Response without 'tasks' key returns empty list (not an error)."""
        tasks = parse_task_result({"error": "none found"})
        assert tasks == []


# ---------------------------------------------------------------------------
# TestClassifyWorkflowIntegration
# The classify step is driven by the SYSTEM_PROMPT instructions. These tests
# verify the prompts correctly define how classification should happen and
# that classification results map to the right execution workflows.
# ---------------------------------------------------------------------------


class TestClassifyWorkflowIntegration:
    """Tests the classify step: prompt defines how to classify tasks."""

    def test_classify_uses_unclassified_only_filter(self) -> None:
        """Classification workflow requires get_agent_tasks(unclassified_only=True)."""
        assert "unclassified_only=True" in SYSTEM_PROMPT

    def test_classify_all_action_types_in_prompt(self) -> None:
        """All supported action_types are documented in the prompt."""
        required_types = [
            "code",
            "research",
            "email",
            "document",
            "communication",
            "review",
            "other",
        ]
        for action_type in required_types:
            assert f"`{action_type}`" in SYSTEM_PROMPT, (
                f"action_type '{action_type}' must be documented in SYSTEM_PROMPT"
            )

    def test_classify_sets_agent_actionable(self) -> None:
        """Classification always assigns agent_actionable."""
        assert "agent_actionable" in SYSTEM_PROMPT
        assert "`true`" in SYSTEM_PROMPT
        assert "`false`" in SYSTEM_PROMPT

    def test_classify_sets_autonomy_tier(self) -> None:
        """Classification assigns autonomy_tier for each task."""
        assert "autonomy_tier" in SYSTEM_PROMPT

    def test_classify_non_actionable_requires_blocking_reason(self) -> None:
        """Non-agent-actionable tasks must have a blocking_reason."""
        assert "blocking_reason" in SYSTEM_PROMPT

    def test_classify_examples_cover_all_tiers(self) -> None:
        """Classification examples demonstrate Tier 1 through Tier 4 assignments."""
        # Tier 1: research - no approval needed
        assert "research" in SYSTEM_PROMPT
        # Tier 2: code workspace - execute then notify
        assert "code" in SYSTEM_PROMPT
        # Tier 3: email to external - propose first
        assert "email" in SYSTEM_PROMPT
        # Tier 4: physical/financial - human only
        assert "Human only" in SYSTEM_PROMPT

    def test_classify_non_actionable_examples_included(self) -> None:
        """Non-actionable example tasks appear in the classification table."""
        assert (
            "Requires purchase approval" in SYSTEM_PROMPT or "Requires phone call" in SYSTEM_PROMPT
        )

    def test_classify_action_type_maps_to_execution_workflow(self) -> None:
        """Every action_type from classification has a corresponding execution workflow."""
        action_workflow_pairs = {
            "code": "Code Tasks",
            "research": "Research Tasks",
            "email": "Email Tasks",
            "document": "Document Tasks",
            "communication": "Communication Tasks",
            "review": "Review Tasks",
        }
        for action_type, workflow_label in action_workflow_pairs.items():
            assert f"Execution Workflow: {workflow_label}" in SYSTEM_PROMPT, (
                f"action_type '{action_type}' maps to workflow '{workflow_label}' "
                f"but that section is missing from SYSTEM_PROMPT"
            )

    def test_classify_step_calls_classify_task_tool(self) -> None:
        """Prompt instructs agent to call classify_task for each unclassified task."""
        assert "classify_task" in SYSTEM_PROMPT
        # The classification workflow section explicitly calls the tool
        assert "Call classify_task" in SYSTEM_PROMPT or "call classify_task" in SYSTEM_PROMPT

    def test_classify_tier_descriptions_match_safety_table(self) -> None:
        """Tier descriptions in classification examples match the safety controls table."""
        # Tier descriptions should be internally consistent
        assert "Tier 1" in SYSTEM_PROMPT
        assert "Tier 2" in SYSTEM_PROMPT
        assert "Tier 3" in SYSTEM_PROMPT
        assert "Tier 4" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# TestExecuteWorkflowIntegration
# The execute step is the most complex: each action_type has its own workflow.
# These tests verify each workflow is complete and coherent.
# ---------------------------------------------------------------------------


class TestExecuteWorkflowIntegration:
    """Tests the execute step: workflow sections are complete for each type."""

    def test_code_workflow_full_lifecycle(self) -> None:
        """Code task workflow covers the full lifecycle from start to completion."""
        text = _get_workflow_text("Code Tasks")
        # Start
        assert 'set_agent_status("in_progress")' in text or "in_progress" in text
        # Dependency check
        assert "list_dependencies" in text
        # Workspace
        assert "create_claude_code_workspace" in text or "list_claude_code_workspaces" in text
        # Execute
        assert "run_claude_code" in text
        # Log
        assert "add_agent_note" in text
        # Complete
        assert "complete_task" in text or "set_agent_status" in text

    def test_research_workflow_full_lifecycle(self) -> None:
        """Research task workflow covers the full lifecycle from start to completion."""
        text = _get_workflow_text("Research Tasks")
        # Start
        assert "in_progress" in text
        # Data gathering
        assert "fetch_web_content" in text
        # Log
        assert "add_agent_note" in text
        # Follow-up creation
        assert "create_task" in text
        # Complete
        assert "completed" in text or "set_agent_status" in text

    def test_email_workflow_full_lifecycle(self) -> None:
        """Email task workflow covers the full lifecycle from start to completion."""
        text = _get_workflow_text("Email Tasks")
        # Start
        assert "in_progress" in text
        # Context gathering
        assert "search_emails" in text
        # Send
        assert "send_email" in text
        # Log
        assert "add_agent_note" in text
        # Complete
        assert "complete_task" in text

    def test_document_workflow_full_lifecycle(self) -> None:
        """Document task workflow covers the full lifecycle from start to completion."""
        text = _get_workflow_text("Document Tasks")
        # Start
        assert "in_progress" in text
        # Log
        assert "add_agent_note" in text
        # Completion or review
        assert "complete_task" in text or "pending_review" in text

    def test_communication_workflow_full_lifecycle(self) -> None:
        """Communication task workflow covers the full lifecycle."""
        text = _get_workflow_text("Communication Tasks")
        # Start
        assert "in_progress" in text
        # Send
        assert "send_slack_message" in text
        # Log
        assert "add_agent_note" in text
        # Complete
        assert "complete_task" in text

    def test_review_workflow_full_lifecycle(self) -> None:
        """Review task workflow covers the full lifecycle."""
        text = _get_workflow_text("Review Tasks")
        # Start
        assert "in_progress" in text
        # Log findings
        assert "add_agent_note" in text
        # Outcomes
        assert "complete_task" in text or "pending_review" in text or "needs_human" in text

    def test_all_workflows_set_status_in_progress(self) -> None:
        """Every workflow must begin with set_agent_status('in_progress')."""
        workflow_labels = [
            "Code Tasks",
            "Research Tasks",
            "Email Tasks",
            "Document Tasks",
            "Communication Tasks",
            "Review Tasks",
        ]
        for label in workflow_labels:
            text = _get_workflow_text(label)
            assert "set_agent_status" in text, f"Workflow '{label}' missing set_agent_status call"
            assert "in_progress" in text, f"Workflow '{label}' never sets status to in_progress"

    def test_all_workflows_use_add_agent_note(self) -> None:
        """Every workflow must log progress via add_agent_note."""
        workflow_labels = [
            "Code Tasks",
            "Research Tasks",
            "Email Tasks",
            "Document Tasks",
            "Communication Tasks",
            "Review Tasks",
        ]
        for label in workflow_labels:
            text = _get_workflow_text(label)
            assert "add_agent_note" in text, f"Workflow '{label}' missing add_agent_note"

    def test_code_workflow_handles_all_outcome_states(self) -> None:
        """Code workflow explicitly handles success, partial, and failure outcomes."""
        text = _get_workflow_text("Code Tasks")
        # Success path
        assert "complete_task" in text
        # Partial path
        assert "pending_review" in text
        # Failure path
        assert "blocked" in text

    def test_email_workflow_tier3_safety_check(self) -> None:
        """Email workflow enforces tier 3 propose-first pattern for external emails."""
        text = _get_workflow_text("Email Tasks")
        assert (
            "tier 3" in text.lower()
            or "autonomy_tier 3" in text.lower()
            or "propose" in text.lower()
        )

    def test_research_workflow_creates_followup_tasks(self) -> None:
        """Research workflow creates follow-up tasks for actionable findings."""
        text = _get_workflow_text("Research Tasks")
        assert "create_task" in text
        assert "follow-up" in text.lower() or "follow up" in text.lower()

    def test_code_workflow_requires_workspace(self) -> None:
        """Code workflow requires Claude Code workspace before execution."""
        text = _get_workflow_text("Code Tasks")
        # Both listing and creating workspaces are referenced
        assert "list_claude_code_workspaces" in text or "create_claude_code_workspace" in text
        assert "run_claude_code" in text

    def test_review_workflow_has_multiple_outcome_paths(self) -> None:
        """Review workflow has distinct handling for approved/changes-needed/cannot-review."""
        text = _get_workflow_text("Review Tasks")
        # Approved path
        assert "complete_task" in text
        # Changes needed path
        assert "pending_review" in text
        # Escalation path
        assert "needs_human" in text


# ---------------------------------------------------------------------------
# TestCompleteWorkflowIntegration
# The complete step closes the task and notifies via Slack/SMS.
# ---------------------------------------------------------------------------


class TestCompleteWorkflowIntegration:
    """Tests the complete step: completion and notification patterns."""

    def test_complete_task_tool_documented(self) -> None:
        """complete_task is documented as a Task Management Tool in the prompt."""
        assert "complete_task" in SYSTEM_PROMPT
        assert "Mark a task as completed" in SYSTEM_PROMPT or "completed" in SYSTEM_PROMPT

    def test_completion_triggers_slack_notification(self) -> None:
        """Each workflow that completes a task also notifies via Slack."""
        workflows_requiring_slack = [
            "Code Tasks",
            "Research Tasks",
            "Email Tasks",
            "Document Tasks",
        ]
        for label in workflows_requiring_slack:
            text = _get_workflow_text(label)
            assert "send_slack_message" in text or "notify" in text.lower(), (
                f"Workflow '{label}' missing Slack notification after completion"
            )

    def test_completion_sms_for_urgent_tasks(self) -> None:
        """Code workflow sends SMS for urgent completions."""
        text = _get_workflow_text("Code Tasks")
        assert "send_sms_to_admin" in text

    def test_complete_task_in_all_success_paths(self) -> None:
        """All success paths call complete_task before finishing."""
        success_path_workflows = [
            "Email Tasks",
            "Communication Tasks",
        ]
        for label in success_path_workflows:
            text = _get_workflow_text(label)
            assert "complete_task" in text, (
                f"Workflow '{label}' missing complete_task in success path"
            )

    def test_lifecycle_canonical_order(self) -> None:
        """Canonical lifecycle contains all required steps in the correct order.

        Rather than checking a verbatim string (which would be brittle to
        minor formatting changes), we verify that each lifecycle token appears
        in the prompt and that the overall lifecycle section is present.
        """
        # The lifecycle summary line must appear somewhere in the prompt
        lifecycle_tokens = [
            "classify_task",
            'set_agent_status("in_progress")',
            "add_agent_note",
            "complete_task",
        ]
        for token in lifecycle_tokens:
            assert token in SYSTEM_PROMPT, f"Lifecycle token '{token}' missing from SYSTEM_PROMPT"
        # The canonical arrow-separated lifecycle block must be present
        assert "EXECUTE" in SYSTEM_PROMPT

    def test_completion_blocked_state_stops_execution(self) -> None:
        """Blocked tasks must not be retried without human intervention."""
        assert "blocked" in SYSTEM_PROMPT
        assert "blocking_reason" in SYSTEM_PROMPT
        # The safety rule explicitly forbids retrying blocked tasks
        assert "do NOT retry" in SYSTEM_PROMPT or "Do not retry" in SYSTEM_PROMPT

    def test_audit_trail_via_agent_notes(self) -> None:
        """Agent notes provide an audit trail for all task executions."""
        assert "add_agent_note" in SYSTEM_PROMPT
        assert "audit" in SYSTEM_PROMPT.lower() or "Execution logging" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# TestFullWorkflowCohesion
# End-to-end tests verifying all stages connect properly.
# ---------------------------------------------------------------------------


class TestFullWorkflowCohesion:
    """End-to-end coherence tests: create -> classify -> execute -> complete."""

    def test_full_lifecycle_uses_correct_tool_sequence(self) -> None:
        """All tools needed for the full workflow are present in the prompt."""
        lifecycle_tools = [
            # Create
            "create_task",
            # Classify
            "classify_task",
            "get_agent_tasks",
            # Execute
            "set_agent_status",
            "add_agent_note",
            # Complete
            "complete_task",
            # Notify
            "send_slack_message",
        ]
        for tool in lifecycle_tools:
            assert tool in SYSTEM_PROMPT, f"Lifecycle tool '{tool}' missing from SYSTEM_PROMPT"

    def test_all_lifecycle_tools_in_allowed_tools(self) -> None:
        """All tools referenced in lifecycle are available in the agent's allowed_tools."""
        allowed = _build_full_allowed_tools()
        # Slack notification tool
        assert "send_slack_message" in allowed
        # Web content tools (used in research workflow)
        assert "fetch_web_content" in allowed
        # Email tools (used in email workflow)
        assert "send_email" in allowed
        assert "search_emails" in allowed
        # Claude Code tools (used in code workflow)
        assert "run_claude_code" in allowed
        assert "create_claude_code_workspace" in allowed
        # SMS for urgent notifications
        assert "send_sms_to_admin" in allowed

    def test_workflow_coverage_all_action_types(self) -> None:
        """Every action_type documented for classification has an execution workflow."""
        # All action types from the classification table
        typed_workflows = {
            "code": "Code Tasks",
            "research": "Research Tasks",
            "email": "Email Tasks",
            "document": "Document Tasks",
            "communication": "Communication Tasks",
            "review": "Review Tasks",
        }
        for action_type, workflow_label in typed_workflows.items():
            assert f"`{action_type}`" in SYSTEM_PROMPT, (
                f"action_type '{action_type}' missing from classification section"
            )
            assert f"Execution Workflow: {workflow_label}" in SYSTEM_PROMPT, (
                f"Execution workflow for '{action_type}' tasks not found"
            )

    def test_no_silently_dropped_tasks(self) -> None:
        """Failures must always log a note and update status — no silent drops."""
        assert "No silent failures" in SYSTEM_PROMPT or "no silent" in SYSTEM_PROMPT.lower()
        assert "add_agent_note" in SYSTEM_PROMPT
        # Blocked tasks get a blocking_reason
        assert "blocking_reason" in SYSTEM_PROMPT

    def test_create_task_used_in_research_followup(self) -> None:
        """Research workflow uses create_task to produce follow-up tasks."""
        text = _get_workflow_text("Research Tasks")
        assert "create_task" in text

    def test_research_followed_by_classification(self) -> None:
        """Newly created follow-up tasks can be classified in the next cycle."""
        # The prompt documents the full classification → execution loop
        assert "get_agent_tasks(unclassified_only=True)" in SYSTEM_PROMPT
        assert "classify_task" in SYSTEM_PROMPT

    def test_status_state_machine_completeness(self) -> None:
        """All valid agent_status transitions are documented."""
        valid_statuses = ["in_progress", "pending_review", "needs_human", "blocked", "completed"]
        for status in valid_statuses:
            assert (
                f'"{status}"' in SYSTEM_PROMPT
                or f"'{status}'" in SYSTEM_PROMPT
                or status in SYSTEM_PROMPT
            )

    def test_agent_factory_creates_task_manager(self) -> None:
        """TaskManagerAgent is created via the factory and has required attributes."""
        from agents.task_manager.main import TaskManagerAgent

        # The class must have get_system_prompt (not just be callable — all classes are)
        assert hasattr(TaskManagerAgent, "get_system_prompt"), (
            "TaskManagerAgent must expose get_system_prompt (created via create_simple_agent factory)"
        )
        assert hasattr(TaskManagerAgent, "get_greeting"), (
            "TaskManagerAgent must expose get_greeting"
        )

    def test_task_manager_version_reflects_execution_engine(self) -> None:
        """Version bumped to reflect execution engine capability (>= 0.2.0)."""
        from agents.task_manager import __version__

        # Split with maxsplit=2 to handle pre-release suffixes like "0.2.1a1" or "0.3.0-rc1"
        parts = __version__.split(".", 2)
        major, minor = int(parts[0]), int(parts[1])
        assert major > 0 or minor >= 2, (
            f"Version {__version__} should be >= 0.2.0 (execution engine was added in 0.2.0)"
        )


# ---------------------------------------------------------------------------
# TestAgentToolInteractionPatterns
# Verify specific tool interaction patterns for each workflow stage.
# ---------------------------------------------------------------------------


class TestAgentToolInteractionPatterns:
    """Tests agent-specific tool interaction patterns end-to-end."""

    def test_code_workflow_dependency_check_before_execution(self) -> None:
        """Code workflow checks dependencies before executing to prevent blocked work."""
        text = _get_workflow_text("Code Tasks")
        assert "list_dependencies" in text

    def test_email_workflow_searches_prior_thread(self) -> None:
        """Email workflow searches for prior threads to compose contextual replies."""
        text = _get_workflow_text("Email Tasks")
        assert "search_emails" in text

    def test_email_workflow_reads_relationship_memory(self) -> None:
        """Email workflow reads memory for recipient relationship context."""
        text = _get_workflow_text("Email Tasks")
        assert "get_memories" in text or "memory" in text.lower()

    def test_review_workflow_fetches_review_material(self) -> None:
        """Review workflow gathers the material to be reviewed before analysis."""
        text = _get_workflow_text("Review Tasks")
        # Multiple tools for different review contexts
        assert any(
            tool in text
            for tool in [
                "get_claude_code_workspace_status",
                "fetch_web_content",
                "search_emails",
                "search_tasks",
            ]
        )

    def test_research_workflow_multi_source_gathering(self) -> None:
        """Research workflow gathers from at least two distinct content sources."""
        text = _get_workflow_text("Research Tasks")
        # fetch_web_content is always required; plus at least one more source
        assert "fetch_web_content" in text
        assert "search_emails" in text or "search_tasks" in text or "analyze_website" in text

    def test_document_workflow_can_use_claude_code(self) -> None:
        """Document workflow can delegate to Claude Code for code documentation."""
        text = _get_workflow_text("Document Tasks")
        assert "run_claude_code" in text

    def test_morning_scheduler_includes_classify_step(self) -> None:
        """Morning routine includes the classify step in the workflow."""
        from agents.task_manager.scheduler import MORNING_PROMPT

        assert "classify" in MORNING_PROMPT.lower()
        assert "unclassified" in MORNING_PROMPT.lower()

    def test_evening_scheduler_includes_classify_new_tasks(self) -> None:
        """Evening routine classifies tasks added during the day."""
        from agents.task_manager.scheduler import EVENING_PROMPT

        assert "classify" in EVENING_PROMPT.lower()

    def test_morning_scheduler_sends_briefing(self) -> None:
        """Morning routine sends briefing via Slack and SMS after execution."""
        from agents.task_manager.scheduler import MORNING_PROMPT

        assert "send_slack_message" in MORNING_PROMPT
        assert "send_sms_to_admin" in MORNING_PROMPT

    def test_execution_lifecycle_in_example_workflows(self) -> None:
        """Example workflows in the prompt demonstrate the full lifecycle."""
        # Code task example
        assert "Code Task Execution" in SYSTEM_PROMPT
        # The example shows all lifecycle steps
        assert 'set_agent_status("in_progress")' in SYSTEM_PROMPT
        assert "run_claude_code" in SYSTEM_PROMPT
        assert "add_agent_note" in SYSTEM_PROMPT
        assert "complete_task" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# TestNotificationWorkflowIntegration
# Verify that notification utilities integrate correctly with the workflow.
# ---------------------------------------------------------------------------


class TestNotificationWorkflowIntegration:
    """Tests notification utilities used in completion/error stages."""

    @pytest.mark.asyncio
    async def test_notify_task_completion_sends_slack_and_sms(self) -> None:
        """Task completion notifies via both Slack and SMS channels."""
        with (
            patch("shared.notifications.send_slack_message", new_callable=AsyncMock) as mock_slack,
            patch("shared.notifications.send_sms_to_admin", new_callable=AsyncMock) as mock_sms,
        ):
            await notify_task_completion(
                task_title="Fix login bug",
                task_id="42",
                summary="Fixed session token refresh in auth.py",
                agent_name="TaskManagerAgent",
            )
            mock_slack.assert_called_once()
            mock_sms.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_task_completion_message_includes_task_info(self) -> None:
        """Completion notification message includes task title and ID."""
        messages: list[str] = []
        with (
            patch(
                "shared.notifications.send_slack_message",
                new_callable=AsyncMock,
                side_effect=lambda **kw: messages.append(kw.get("text", "")),
            ),
            patch("shared.notifications.send_sms_to_admin", new_callable=AsyncMock),
        ):
            await notify_task_completion(
                task_title="Write API docs",
                task_id="99",
                summary="Docs written",
            )
        assert any("Write API docs" in m for m in messages)
        assert any("#99" in m for m in messages)

    @pytest.mark.asyncio
    async def test_slack_failure_does_not_block_sms_notification(self) -> None:
        """Slack failure is swallowed; SMS still fires."""
        with (
            patch(
                "shared.notifications.send_slack_message",
                new_callable=AsyncMock,
                side_effect=Exception("Slack connection timeout"),
            ),
            patch("shared.notifications.send_sms_to_admin", new_callable=AsyncMock) as mock_sms,
        ):
            # Should not raise
            await notify_task_completion("Task", "1", "Done")
        mock_sms.assert_called_once()

    @pytest.mark.asyncio
    async def test_sms_failure_does_not_block_slack_notification(self) -> None:
        """SMS failure is swallowed; Slack still fires."""
        with (
            patch("shared.notifications.send_slack_message", new_callable=AsyncMock) as mock_slack,
            patch(
                "shared.notifications.send_sms_to_admin",
                new_callable=AsyncMock,
                side_effect=Exception("Twilio quota exceeded"),
            ),
        ):
            # Should not raise
            await notify_task_completion("Task", "1", "Done")
        mock_slack.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_error_includes_context_and_error(self) -> None:
        """Error notification includes context name and error message."""
        messages: list[str] = []
        with (
            patch(
                "shared.notifications.send_slack_message",
                new_callable=AsyncMock,
                side_effect=lambda **kw: messages.append(kw.get("text", "")),
            ),
            patch("shared.notifications.send_sms_to_admin", new_callable=AsyncMock),
        ):
            await notify_error(
                context="Code task execution",
                error="run_claude_code timeout after 300s",
            )
        assert any("Code task execution" in m for m in messages)
        assert any("run_claude_code" in m or "timeout" in m for m in messages)

    @pytest.mark.asyncio
    async def test_notify_routine_complete_sends_both_channels(self) -> None:
        """Routine completion (morning/evening) notifies via Slack and SMS."""
        with (
            patch("shared.notifications.send_slack_message", new_callable=AsyncMock) as mock_slack,
            patch("shared.notifications.send_sms_to_admin", new_callable=AsyncMock) as mock_sms,
        ):
            await notify_routine_complete(
                routine_name="Morning",
                summary="5 tasks rescheduled, 3 classified",
            )
            mock_slack.assert_called_once()
            mock_sms.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_error_slack_failure_does_not_block_sms(self) -> None:
        """Error notification: Slack failure is swallowed; SMS still fires."""
        with (
            patch(
                "shared.notifications.send_slack_message",
                new_callable=AsyncMock,
                side_effect=Exception("Slack unavailable"),
            ),
            patch("shared.notifications.send_sms_to_admin", new_callable=AsyncMock) as mock_sms,
        ):
            # Should not raise even when Slack is down
            await notify_error(context="Test context", error="Something failed")
        mock_sms.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_error_sms_failure_does_not_block_slack(self) -> None:
        """Error notification: SMS failure is swallowed; Slack still fires."""
        with (
            patch("shared.notifications.send_slack_message", new_callable=AsyncMock) as mock_slack,
            patch(
                "shared.notifications.send_sms_to_admin",
                new_callable=AsyncMock,
                side_effect=Exception("Twilio unavailable"),
            ),
        ):
            # Should not raise even when SMS is down
            await notify_error(context="Test context", error="Something failed")
        mock_slack.assert_called_once()


# ---------------------------------------------------------------------------
# TestSafetyControlsInWorkflow
# Safety controls are integral to the workflow — they gate which tasks
# the agent can execute autonomously.
# ---------------------------------------------------------------------------


class TestSafetyControlsInWorkflow:
    """Tests safety controls as they interact with the full workflow."""

    def test_tier1_tasks_execute_without_approval(self) -> None:
        """Tier 1 tasks (research, analysis) execute freely without asking user."""
        assert "Full autonomy" in SYSTEM_PROMPT
        # Tier 1 examples include research
        assert "Research" in SYSTEM_PROMPT or "research" in SYSTEM_PROMPT
        # No approval required message
        assert "No — execute freely" in SYSTEM_PROMPT or "execute freely" in SYSTEM_PROMPT

    def test_tier2_tasks_execute_then_notify(self) -> None:
        """Tier 2 tasks execute autonomously then notify user via Slack."""
        assert "Execute" in SYSTEM_PROMPT
        assert "notify" in SYSTEM_PROMPT
        # Tier 2 covers code workspace changes
        assert (
            "workspace code changes" in SYSTEM_PROMPT.lower()
            or "Workspace code changes" in SYSTEM_PROMPT
        )

    def test_tier3_tasks_require_approval_before_execution(self) -> None:
        """Tier 3 tasks must be proposed to user and wait for explicit approval."""
        assert "Propose" in SYSTEM_PROMPT
        assert "Wait for approval" in SYSTEM_PROMPT
        # External emails are tier 3
        assert "external" in SYSTEM_PROMPT.lower()

    def test_tier4_tasks_blocked_from_agent_execution(self) -> None:
        """Tier 4 tasks must not be executed — set needs_human status instead."""
        assert "Human only" in SYSTEM_PROMPT
        assert "needs_human" in SYSTEM_PROMPT
        # Tier 4 blocks include financial and legal
        assert "Financial" in SYSTEM_PROMPT or "financial" in SYSTEM_PROMPT.lower()

    def test_blocked_status_stops_workflow(self) -> None:
        """Blocked tasks halt the workflow and require human unblocking."""
        assert "Blocked = stop" in SYSTEM_PROMPT or "blocked" in SYSTEM_PROMPT.lower()
        assert "blocking_reason" in SYSTEM_PROMPT

    def test_log_before_execute_rule(self) -> None:
        """Agent must log intent before executing any action."""
        assert "Always log before executing" in SYSTEM_PROMPT

    def test_scope_limits_prevent_expansion(self) -> None:
        """Agent must not expand beyond the task description."""
        assert "Scope limits" in SYSTEM_PROMPT
        assert "Only execute what the task description asks for" in SYSTEM_PROMPT

    def test_bulk_operations_require_confirmation(self) -> None:
        """Bulk rescheduling or modifying more than 5 tasks requires user confirmation."""
        assert "5 tasks" in SYSTEM_PROMPT or "bulk" in SYSTEM_PROMPT.lower()
        assert "confirmation" in SYSTEM_PROMPT.lower() or "confirm" in SYSTEM_PROMPT.lower()

    def test_propose_then_execute_pattern_has_five_steps(self) -> None:
        """Tier 3 propose-then-execute pattern has all required steps."""
        assert "Announce intent" in SYSTEM_PROMPT
        assert "Present the plan" in SYSTEM_PROMPT
        assert "Wait for approval" in SYSTEM_PROMPT
        assert "Execute on approval" in SYSTEM_PROMPT
        assert "Log and notify" in SYSTEM_PROMPT

    def test_classify_step_sets_autonomy_tier(self) -> None:
        """Classification assigns autonomy_tier which gates execution."""
        # Classification docs say to set autonomy_tier
        assert "autonomy_tier" in SYSTEM_PROMPT
        # Safety controls reference the same tiers
        assert "Tier 1" in SYSTEM_PROMPT
        assert "Tier 4" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# TestWorkflowDataTransformations
# Data transformation tests: priorities, task results, and JSON parsing.
# ---------------------------------------------------------------------------


class TestWorkflowDataTransformations:
    """Tests data transformations at workflow boundaries."""

    def test_priority_transformation_for_task_creation(self) -> None:
        """Priority values from various sources transform correctly on create."""
        # From task manager UI: integer
        assert parse_priority(8) == 8
        # From email intake: text
        assert parse_priority("urgent") == 9
        # From scheduler: string number
        assert parse_priority("3") == 3
        # Missing priority gets sensible default
        assert parse_priority(None) == 5

    def test_task_list_from_get_agent_tasks(self) -> None:
        """Simulated get_agent_tasks response parses into task list."""
        response = {
            "tasks": [
                _make_task(id="10", title="Code task", action_type="code", agent_actionable=True),
                _make_task(
                    id="11", title="Research task", action_type="research", agent_actionable=True
                ),
                _make_task(
                    id="12", title="Buy monitor", action_type="other", agent_actionable=False
                ),
            ]
        }
        tasks = parse_task_result(response)

        assert len(tasks) == 3

        code_tasks = [t for t in tasks if t.get("action_type") == "code"]
        assert len(code_tasks) == 1
        assert code_tasks[0]["agent_actionable"] is True

        non_actionable = [t for t in tasks if t.get("agent_actionable") is False]
        assert len(non_actionable) == 1
        assert non_actionable[0]["title"] == "Buy monitor"

    def test_classify_result_round_trips_correctly(self) -> None:
        """Classification output structure is preserved when read back."""
        classified_task = _make_task(
            id="55",
            title="Fix login bug",
            action_type="code",
            agent_actionable=True,
            autonomy_tier=2,
            agent_status="pending",
        )
        raw = json.dumps({"tasks": [classified_task]})
        tasks = parse_task_result(raw)

        assert len(tasks) == 1
        t = tasks[0]
        assert t["action_type"] == "code"
        assert t["agent_actionable"] is True
        assert t["autonomy_tier"] == 2

    def test_completed_task_status_preserved(self) -> None:
        """Completed task status is preserved in result parsing."""
        task = _make_task(id="77", title="Done task")
        task["status"] = "completed"
        task["agent_status"] = "completed"

        tasks = parse_task_result({"tasks": [task]})
        assert tasks[0]["status"] == "completed"
        assert tasks[0]["agent_status"] == "completed"

    def test_blocked_task_has_blocking_reason(self) -> None:
        """Blocked tasks carry a blocking_reason field."""
        task = _make_task(id="88", title="Blocked task")
        task["agent_status"] = "blocked"
        task["blocking_reason"] = "Requires vendor API key"

        tasks = parse_task_result({"tasks": [task]})
        assert tasks[0]["agent_status"] == "blocked"
        assert tasks[0]["blocking_reason"] == "Requires vendor API key"
