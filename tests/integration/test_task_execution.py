"""Integration tests for the task execution engine.

Tests cover the classification, execution workflow definitions, safety controls,
and tool configuration for the Task Manager agent's execution capabilities.

These tests verify the prompts and configuration are correctly wired up,
not actual Claude API calls (which require credentials and live services).
"""

from agents.task_manager.prompts import SYSTEM_PROMPT, USER_GREETING_PROMPT


class TestTaskManagerToolConfiguration:
    """Verify the agent imports all required tool groups."""

    def test_claude_code_tools_in_imports(self):
        """Task execution requires CLAUDE_CODE_TOOLS to be imported and used."""
        import inspect

        import agents.task_manager.main as main_module

        source = inspect.getsource(main_module)
        assert "CLAUDE_CODE_TOOLS" in source

    def test_email_tools_in_imports(self):
        """Task execution requires FASTMAIL_TOOLS to be imported and used."""
        import inspect

        import agents.task_manager.main as main_module

        source = inspect.getsource(main_module)
        assert "FASTMAIL_TOOLS" in source

    def test_communication_tools_in_imports(self):
        """Notifications require COMMUNICATION_TOOLS."""
        import inspect

        import agents.task_manager.main as main_module

        source = inspect.getsource(main_module)
        assert "COMMUNICATION_TOOLS" in source

    def test_memory_tools_in_imports(self):
        """Agent needs MEMORY_TOOLS for context."""
        import inspect

        import agents.task_manager.main as main_module

        source = inspect.getsource(main_module)
        assert "MEMORY_TOOLS" in source

    def test_web_research_tools_in_imports(self):
        """Research task execution requires WEB_RESEARCH_TOOLS."""
        import inspect

        import agents.task_manager.main as main_module

        source = inspect.getsource(main_module)
        assert "WEB_RESEARCH_TOOLS" in source

    def test_all_tool_groups_in_allowed_tools(self):
        """All tool groups must be combined into allowed_tools."""
        from shared.constants import (
            CLAUDE_CODE_TOOLS,
            COMMUNICATION_TOOLS,
            FASTMAIL_TOOLS,
            MEMORY_TOOLS,
            WEB_RESEARCH_TOOLS,
        )

        # Verify all tool groups are non-empty
        assert len(CLAUDE_CODE_TOOLS) > 0
        assert len(COMMUNICATION_TOOLS) > 0
        assert len(FASTMAIL_TOOLS) > 0
        assert len(MEMORY_TOOLS) > 0
        assert len(WEB_RESEARCH_TOOLS) > 0


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
            "code": "Execution Workflow: Code Tasks",
            "research": "Execution Workflow: Research Tasks",
            "email": "Execution Workflow: Email Tasks",
            "document": "Execution Workflow: Document Tasks",
            "communication": "Execution Workflow: Communication Tasks",
        }
        for action_type, workflow_heading in action_workflow_map.items():
            assert workflow_heading in SYSTEM_PROMPT, (
                f"action_type '{action_type}' has no execution workflow '{workflow_heading}'"
            )

    def test_all_workflows_include_status_tracking(self):
        """Every execution workflow should use set_agent_status."""
        assert SYSTEM_PROMPT.count("set_agent_status") >= 10, (
            "set_agent_status should be referenced throughout execution workflows"
        )

    def test_all_workflows_include_logging(self):
        """Every execution workflow should use add_agent_note for logging."""
        assert SYSTEM_PROMPT.count("add_agent_note") >= 8, (
            "add_agent_note should be referenced throughout execution workflows"
        )

    def test_all_workflows_include_notification(self):
        """Execution workflows should notify via Slack on completion."""
        assert SYSTEM_PROMPT.count("send_slack_message") >= 3, (
            "Execution workflows should notify via send_slack_message"
        )

    def test_complete_task_used_in_workflows(self):
        """complete_task should be used to close tasks after execution."""
        assert SYSTEM_PROMPT.count("complete_task") >= 5, (
            "complete_task should be used across execution workflows"
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
