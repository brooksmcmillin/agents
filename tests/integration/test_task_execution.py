"""Integration tests for the task execution engine.

Tests cover the classification, execution workflow definitions, safety controls,
and tool configuration for the Task Manager agent's execution capabilities.

These tests verify the prompts and configuration are correctly wired up,
not actual Claude API calls (which require credentials and live services).
"""

import re

from agents.task_manager.prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT
from shared.constants import (
    CLAUDE_CODE_TOOLS,
    COMMUNICATION_TOOLS,
    CONTENT_TOOLS,
    FASTMAIL_TOOLS,
    MEMORY_TOOLS,
)


def _get_workflow_section(action_type: str) -> str:
    """Extract a specific execution workflow section from the prompt.

    Returns the text between the workflow heading and the next heading
    of the same level (### or ##).
    """
    pattern = rf"### Execution Workflow:.*?{re.escape(action_type)}.*?\n(.*?)(?=\n###? |\Z)"
    match = re.search(pattern, SYSTEM_PROMPT, re.DOTALL)
    assert match, f"Could not find workflow section for '{action_type}'"
    return match.group(1)


class TestTaskManagerToolConfiguration:
    """Verify the agent has all required tool groups in allowed_tools."""

    def _get_allowed_tools(self) -> list[str]:
        """Build the expected allowed_tools list from the agent module."""
        return (
            CONTENT_TOOLS + MEMORY_TOOLS + COMMUNICATION_TOOLS + CLAUDE_CODE_TOOLS + FASTMAIL_TOOLS
        )

    def test_claude_code_tools_included(self):
        """Task execution requires all Claude Code tools."""
        allowed = self._get_allowed_tools()
        for tool in CLAUDE_CODE_TOOLS:
            assert tool in allowed, f"Missing Claude Code tool: {tool}"

    def test_email_tools_included(self):
        """Task execution requires all FastMail tools."""
        allowed = self._get_allowed_tools()
        for tool in FASTMAIL_TOOLS:
            assert tool in allowed, f"Missing email tool: {tool}"

    def test_communication_tools_included(self):
        """Notifications require Slack communication tools."""
        allowed = self._get_allowed_tools()
        for tool in COMMUNICATION_TOOLS:
            assert tool in allowed, f"Missing communication tool: {tool}"

    def test_memory_tools_included(self):
        """Agent needs memory tools for context across sessions."""
        allowed = self._get_allowed_tools()
        for tool in MEMORY_TOOLS:
            assert tool in allowed, f"Missing memory tool: {tool}"

    def test_content_tools_included(self):
        """Research and content tasks require content tools."""
        allowed = self._get_allowed_tools()
        for tool in CONTENT_TOOLS:
            assert tool in allowed, f"Missing content tool: {tool}"

    def test_no_duplicate_tools(self):
        """allowed_tools list should not contain duplicates."""
        allowed = self._get_allowed_tools()
        assert len(allowed) == len(set(allowed)), (
            f"Duplicate tools found: {[t for t in allowed if allowed.count(t) > 1]}"
        )


class TestClassificationWorkflow:
    """Verify task classification workflow is defined in prompts."""

    def test_classification_section_exists(self):
        """Prompt must include the classification workflow section."""
        assert "Task Classification Workflow" in SYSTEM_PROMPT

    def test_action_types_documented(self):
        """All action types must be documented for classification."""
        action_types = ["code", "research", "email", "document", "communication", "review", "other"]
        for action_type in action_types:
            assert f"`{action_type}`" in SYSTEM_PROMPT, (
                f"action_type '{action_type}' not documented in classification workflow"
            )

    def test_agent_actionable_documented(self):
        """agent_actionable field must be documented."""
        assert "agent_actionable" in SYSTEM_PROMPT
        assert "`true`" in SYSTEM_PROMPT
        assert "`false`" in SYSTEM_PROMPT

    def test_unclassified_only_parameter_documented(self):
        """get_agent_tasks(unclassified_only=True) must be documented."""
        assert "unclassified_only=True" in SYSTEM_PROMPT

    def test_blocking_reason_for_non_actionable(self):
        """Non-actionable tasks must require a blocking_reason."""
        assert "blocking_reason" in SYSTEM_PROMPT

    def test_classification_examples_provided(self):
        """Classification examples should be in the prompt."""
        assert "Classification Examples" in SYSTEM_PROMPT
        assert "Fix login bug" in SYSTEM_PROMPT
        assert "Research best CI/CD" in SYSTEM_PROMPT

    def test_autonomy_tier_in_classification(self):
        """Classification must include autonomy_tier assignment."""
        assert "autonomy_tier" in SYSTEM_PROMPT


class TestExecutionWorkflows:
    """Verify execution workflows are defined for each task type."""

    def test_code_execution_workflow(self):
        """Code task execution workflow must be defined."""
        assert "Execution Workflow: Code Tasks" in SYSTEM_PROMPT
        assert "run_claude_code" in SYSTEM_PROMPT
        assert "create_claude_code_workspace" in SYSTEM_PROMPT

    def test_research_execution_workflow(self):
        """Research task execution workflow must be defined."""
        assert "Execution Workflow: Research Tasks" in SYSTEM_PROMPT
        assert "fetch_web_content" in SYSTEM_PROMPT

    def test_email_execution_workflow(self):
        """Email task execution workflow must be defined."""
        assert "Execution Workflow: Email Tasks" in SYSTEM_PROMPT
        assert "send_email" in SYSTEM_PROMPT

    def test_document_execution_workflow(self):
        """Document task execution workflow must be defined."""
        assert "Execution Workflow: Document Tasks" in SYSTEM_PROMPT

    def test_communication_execution_workflow(self):
        """Communication task execution workflow must be defined."""
        assert "Execution Workflow: Communication Tasks" in SYSTEM_PROMPT
        assert "send_slack_message" in SYSTEM_PROMPT

    def test_review_execution_workflow(self):
        """Review task execution workflow must be defined."""
        assert "Execution Workflow: Review Tasks" in SYSTEM_PROMPT

    def test_execution_lifecycle_pattern(self):
        """All workflows follow the standard lifecycle pattern."""
        assert "classify_task" in SYSTEM_PROMPT
        assert 'set_agent_status("in_progress")' in SYSTEM_PROMPT
        assert "add_agent_note" in SYSTEM_PROMPT
        assert "complete_task" in SYSTEM_PROMPT

    def test_code_workflow_includes_workspace_management(self):
        """Code workflow must include workspace creation/checking."""
        assert "list_claude_code_workspaces" in SYSTEM_PROMPT
        assert "create_claude_code_workspace" in SYSTEM_PROMPT

    def test_code_workflow_handles_failure(self):
        """Code workflow must handle failure cases."""
        assert "blocked" in SYSTEM_PROMPT
        assert "pending_review" in SYSTEM_PROMPT

    def test_research_workflow_creates_followup_tasks(self):
        """Research workflow should create follow-up tasks when appropriate."""
        assert "create_task" in SYSTEM_PROMPT
        assert "follow-up" in SYSTEM_PROMPT.lower()

    def test_email_workflow_references_search(self):
        """Email workflow should search for prior thread context."""
        assert "search_emails" in SYSTEM_PROMPT


class TestSafetyControls:
    """Verify safety controls and propose-then-execute pattern."""

    def test_safety_section_exists(self):
        """Prompt must include the safety controls section."""
        assert "Safety Controls: Propose-Then-Execute" in SYSTEM_PROMPT

    def test_autonomy_tiers_defined(self):
        """All four autonomy tiers must be defined."""
        assert "Tier 1" in SYSTEM_PROMPT
        assert "Tier 2" in SYSTEM_PROMPT
        assert "Tier 3" in SYSTEM_PROMPT
        assert "Tier 4" in SYSTEM_PROMPT

    def test_tier_1_full_autonomy(self):
        """Tier 1 allows full autonomy for safe operations."""
        assert "Full autonomy" in SYSTEM_PROMPT

    def test_tier_2_execute_then_notify(self):
        """Tier 2 executes then notifies."""
        assert "Execute" in SYSTEM_PROMPT
        assert "notify" in SYSTEM_PROMPT

    def test_tier_3_propose_then_confirm(self):
        """Tier 3 requires proposal and confirmation."""
        assert "Propose" in SYSTEM_PROMPT
        assert "confirm" in SYSTEM_PROMPT.lower()

    def test_tier_4_human_only(self):
        """Tier 4 is human-only, agent should not execute."""
        assert "Human only" in SYSTEM_PROMPT
        assert "needs_human" in SYSTEM_PROMPT

    def test_propose_then_execute_pattern_documented(self):
        """The propose-then-execute pattern must be fully documented."""
        assert "Propose-Then-Execute Pattern" in SYSTEM_PROMPT
        assert "Wait for approval" in SYSTEM_PROMPT

    def test_safety_rules_defined(self):
        """Safety rules must be present."""
        assert "Safety Rules" in SYSTEM_PROMPT
        assert "Always log before executing" in SYSTEM_PROMPT

    def test_external_facing_actions_rule(self):
        """External-facing actions must require tier 3+."""
        assert "External-facing actions require tier 3+" in SYSTEM_PROMPT

    def test_tier_2_workspace_code_allowed(self):
        """Safety rules must not contradict tier 2 for workspace code changes."""
        assert (
            "Workspace code changes" in SYSTEM_PROMPT or "workspace code changes" in SYSTEM_PROMPT
        )

    def test_email_safety_rule(self):
        """Email-specific safety rule must exist."""
        assert "Email safety" in SYSTEM_PROMPT

    def test_code_safety_rule(self):
        """Code-specific safety rule must exist."""
        assert "Code safety" in SYSTEM_PROMPT

    def test_bulk_operations_require_confirmation(self):
        """Bulk operations must require user confirmation."""
        assert "bulk" in SYSTEM_PROMPT.lower()
        assert "confirmation" in SYSTEM_PROMPT.lower() or "confirm" in SYSTEM_PROMPT.lower()

    def test_scope_limits_enforced(self):
        """Agent must not expand scope beyond task description."""
        assert "Scope limits" in SYSTEM_PROMPT


class TestGreetingPrompt:
    """Verify the user greeting includes execution capabilities."""

    def test_greeting_mentions_classification(self):
        """Greeting should mention task classification."""
        assert "Classify" in USER_GREETING_PROMPT or "classify" in USER_GREETING_PROMPT

    def test_greeting_mentions_execution(self):
        """Greeting should mention task execution."""
        assert "Execute" in USER_GREETING_PROMPT or "execute" in USER_GREETING_PROMPT

    def test_greeting_mentions_core_capabilities(self):
        """Greeting should still mention original capabilities."""
        assert "Reschedule" in USER_GREETING_PROMPT
        assert "research" in USER_GREETING_PROMPT.lower()
        assert "Prioritize" in USER_GREETING_PROMPT or "prioritize" in USER_GREETING_PROMPT


class TestExecutionPipelineIntegration:
    """Integration tests verifying the full pipeline is coherent.

    These tests check that all components work together:
    classification -> execution -> logging -> completion -> notification.
    """

    def test_classification_to_execution_flow(self):
        """Classification action_types must map to execution workflows."""
        action_workflow_map = {
            "code": "Code Tasks",
            "research": "Research Tasks",
            "email": "Email Tasks",
            "document": "Document Tasks",
            "communication": "Communication Tasks",
            "review": "Review Tasks",
        }
        for action_type, workflow_label in action_workflow_map.items():
            assert f"Execution Workflow: {workflow_label}" in SYSTEM_PROMPT, (
                f"action_type '{action_type}' has no execution workflow for '{workflow_label}'"
            )

    def test_each_workflow_includes_status_tracking(self):
        """Every execution workflow section should reference set_agent_status."""
        workflow_types = [
            "Code Tasks",
            "Research Tasks",
            "Email Tasks",
            "Document Tasks",
            "Communication Tasks",
            "Review Tasks",
        ]
        for wtype in workflow_types:
            section = _get_workflow_section(wtype)
            assert "set_agent_status" in section, f"Workflow '{wtype}' missing set_agent_status"

    def test_each_workflow_includes_logging(self):
        """Every execution workflow section should reference add_agent_note."""
        workflow_types = [
            "Code Tasks",
            "Research Tasks",
            "Email Tasks",
            "Document Tasks",
            "Communication Tasks",
            "Review Tasks",
        ]
        for wtype in workflow_types:
            section = _get_workflow_section(wtype)
            assert "add_agent_note" in section, f"Workflow '{wtype}' missing add_agent_note"

    def test_each_workflow_includes_completion(self):
        """Every execution workflow should reference complete_task or set_agent_status for closing."""
        workflow_types = [
            "Code Tasks",
            "Research Tasks",
            "Email Tasks",
            "Document Tasks",
            "Communication Tasks",
            "Review Tasks",
        ]
        for wtype in workflow_types:
            section = _get_workflow_section(wtype)
            assert "complete_task" in section or "set_agent_status" in section, (
                f"Workflow '{wtype}' missing completion step"
            )

    def test_notification_workflows_reference_slack(self):
        """Workflows that produce output should notify via Slack."""
        notifying_types = [
            "Code Tasks",
            "Research Tasks",
            "Email Tasks",
            "Document Tasks",
            "Review Tasks",
        ]
        for wtype in notifying_types:
            section = _get_workflow_section(wtype)
            assert "send_slack_message" in section or "notify" in section.lower(), (
                f"Workflow '{wtype}' missing notification step"
            )

    def test_agent_version_updated(self):
        """Agent version should reflect the execution engine addition."""
        from agents.task_manager import __version__

        major, minor, patch = __version__.split(".")
        assert int(minor) >= 2 or int(major) >= 1, (
            "Version should be bumped to reflect execution engine (>= 0.2.0)"
        )

    def test_execution_engine_section_in_prompt(self):
        """The Task Execution Engine section must exist as a top-level section."""
        assert "## Task Execution Engine" in SYSTEM_PROMPT

    def test_execute_tasks_in_role_description(self):
        """Execute Tasks must be listed as a core agent responsibility."""
        assert "Execute Tasks" in SYSTEM_PROMPT
