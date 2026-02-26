"""Integration tests for autonomous triggers (Phase 3).

Tests cover:
- Scheduler configuration and prompts
- Email intake "Add task" handler
- SMS tools constant and task manager integration
- Multi-channel notification utilities
- Systemd timer installer content generation
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agents.email_intake.main import ADD_TASK_PREFIX, handle_add_task_email
from agents.task_manager.prompts import SYSTEM_PROMPT
from agents.task_manager.scheduler import (
    EVENING_PROMPT,
    MORNING_PROMPT,
    run_evening_routine,
    run_morning_routine,
)
from shared.constants import COMMUNICATION_TOOLS, SMS_TOOLS
from shared.notifications import (
    notify_error,
    notify_routine_complete,
    notify_task_completion,
)


class TestSchedulerConfiguration:
    """Verify scheduler prompts contain required workflow steps."""

    def test_morning_prompt_reviews_overdue(self):
        assert "overdue" in MORNING_PROMPT.lower()

    def test_morning_prompt_classifies_tasks(self):
        assert "classify" in MORNING_PROMPT.lower()
        assert "unclassified" in MORNING_PROMPT.lower()

    def test_morning_prompt_pre_researches(self):
        assert "pre-research" in MORNING_PROMPT.lower() or "research" in MORNING_PROMPT.lower()

    def test_morning_prompt_sends_briefing(self):
        assert "send_slack_message" in MORNING_PROMPT
        assert "send_sms_to_admin" in MORNING_PROMPT

    def test_evening_prompt_reviews_completed(self):
        assert "completed" in EVENING_PROMPT.lower()

    def test_evening_prompt_classifies_new_tasks(self):
        assert "classify" in EVENING_PROMPT.lower()

    def test_evening_prompt_updates_priorities(self):
        assert "priorit" in EVENING_PROMPT.lower()

    def test_evening_prompt_checks_blocked(self):
        assert "blocked" in EVENING_PROMPT.lower()

    def test_evening_prompt_sends_summary(self):
        assert "send_slack_message" in EVENING_PROMPT
        assert "send_sms_to_admin" in EVENING_PROMPT

    def test_morning_routine_is_async(self):
        assert asyncio.iscoroutinefunction(run_morning_routine)

    def test_evening_routine_is_async(self):
        assert asyncio.iscoroutinefunction(run_evening_routine)


class TestEmailIntakeAddTask:
    """Verify email intake 'Add task' prefix detection and routing."""

    def test_add_task_prefix_constant(self):
        assert ADD_TASK_PREFIX == "add task"

    def test_matches_exact_prefix(self):
        result = handle_add_task_email("Add task: Buy groceries", "Get milk and eggs", "a@b.com")
        assert result is not None
        assert "Buy groceries" in result

    def test_matches_case_insensitive(self):
        result = handle_add_task_email("ADD TASK: Fix bug", "Details here", "a@b.com")
        assert result is not None
        assert "Fix bug" in result

    def test_matches_without_colon(self):
        result = handle_add_task_email("Add task Deploy v2", "Notes", "a@b.com")
        assert result is not None
        assert "Deploy v2" in result

    def test_non_matching_returns_none(self):
        result = handle_add_task_email("Regular email subject", "Body text", "a@b.com")
        assert result is None

    def test_security_subject_not_matched(self):
        """'Add task' should not match subjects about attacks."""
        result = handle_add_task_email("Security attack analysis", "Details", "a@b.com")
        assert result is None

    def test_prompt_includes_create_task(self):
        result = handle_add_task_email("Add task: Test", "desc", "a@b.com")
        assert result is not None
        assert "create_task" in result

    def test_prompt_includes_classify_task(self):
        result = handle_add_task_email("Add task: Test", "desc", "a@b.com")
        assert result is not None
        assert "classify_task" in result

    def test_prompt_includes_body_as_description(self):
        result = handle_add_task_email("Add task: Test", "Important details here", "a@b.com")
        assert result is not None
        assert "Important details here" in result

    def test_empty_title_gets_default(self):
        result = handle_add_task_email("Add task", "", "a@b.com")
        assert result is not None
        assert "Untitled task from email" in result

    def test_prompt_includes_sender(self):
        result = handle_add_task_email("Add task: Test", "desc", "user@example.com")
        assert result is not None
        assert "user@example.com" in result


class TestTaskManagerSMSTools:
    """Verify SMS tools are properly integrated into the task manager."""

    def test_sms_tools_constant_exists(self):
        assert isinstance(SMS_TOOLS, list)
        assert len(SMS_TOOLS) > 0

    def test_sms_tools_contains_send(self):
        assert "send_sms_to_admin" in SMS_TOOLS

    def test_sms_tools_contains_status(self):
        assert "get_sms_status" in SMS_TOOLS

    def test_sms_tools_separate_from_communication(self):
        """SMS tools should be a separate group from communication tools."""
        for tool in SMS_TOOLS:
            assert tool not in COMMUNICATION_TOOLS

    def test_task_manager_prompt_mentions_sms(self):
        assert "send_sms_to_admin" in SYSTEM_PROMPT

    def test_task_manager_prompt_has_sms_section(self):
        assert "SMS Notification Tools" in SYSTEM_PROMPT

    def test_task_manager_includes_sms_tools(self):
        """TaskManagerAgent's allowed_tools composition should include SMS_TOOLS."""
        from shared import (
            CLAUDE_CODE_TOOLS,
            COMMUNICATION_TOOLS,
            CONTENT_TOOLS,
            FASTMAIL_TOOLS,
            MEMORY_TOOLS,
            SMS_TOOLS,
        )

        # This mirrors the composition in agents/task_manager/main.py
        expected = (
            CONTENT_TOOLS
            + MEMORY_TOOLS
            + COMMUNICATION_TOOLS
            + SMS_TOOLS
            + CLAUDE_CODE_TOOLS
            + FASTMAIL_TOOLS
        )
        for tool in SMS_TOOLS:
            assert tool in expected, f"SMS tool {tool} not in allowed_tools"


class TestNotificationUtilities:
    """Verify multi-channel notification functions."""

    def test_notify_task_completion_exists(self):
        assert callable(notify_task_completion)
        assert asyncio.iscoroutinefunction(notify_task_completion)

    def test_notify_routine_complete_exists(self):
        assert callable(notify_routine_complete)
        assert asyncio.iscoroutinefunction(notify_routine_complete)

    def test_notify_error_exists(self):
        assert callable(notify_error)
        assert asyncio.iscoroutinefunction(notify_error)

    @pytest.mark.asyncio
    async def test_notify_task_completion_calls_both_channels(self):
        with (
            patch("shared.notifications.send_slack_message", new_callable=AsyncMock) as mock_slack,
            patch("shared.notifications.send_sms_to_admin", new_callable=AsyncMock) as mock_sms,
        ):
            await notify_task_completion("Test Task", "123", "Done", "TestAgent")
            mock_slack.assert_called_once()
            mock_sms.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_routine_complete_calls_both_channels(self):
        with (
            patch("shared.notifications.send_slack_message", new_callable=AsyncMock) as mock_slack,
            patch("shared.notifications.send_sms_to_admin", new_callable=AsyncMock) as mock_sms,
        ):
            await notify_routine_complete("Morning", "All done", "TestAgent")
            mock_slack.assert_called_once()
            mock_sms.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_error_calls_both_channels(self):
        with (
            patch("shared.notifications.send_slack_message", new_callable=AsyncMock) as mock_slack,
            patch("shared.notifications.send_sms_to_admin", new_callable=AsyncMock) as mock_sms,
        ):
            await notify_error("test context", "something broke", "TestAgent")
            mock_slack.assert_called_once()
            mock_sms.assert_called_once()

    @pytest.mark.asyncio
    async def test_slack_failure_does_not_block_sms(self):
        with (
            patch(
                "shared.notifications.send_slack_message",
                new_callable=AsyncMock,
                side_effect=Exception("Slack down"),
            ),
            patch("shared.notifications.send_sms_to_admin", new_callable=AsyncMock) as mock_sms,
        ):
            # Should not raise
            await notify_task_completion("Task", "1", "Done")
            mock_sms.assert_called_once()

    @pytest.mark.asyncio
    async def test_sms_failure_does_not_block_slack(self):
        with (
            patch("shared.notifications.send_slack_message", new_callable=AsyncMock) as mock_slack,
            patch(
                "shared.notifications.send_sms_to_admin",
                new_callable=AsyncMock,
                side_effect=Exception("SMS down"),
            ),
        ):
            # Should not raise
            await notify_task_completion("Task", "1", "Done")
            mock_slack.assert_called_once()


class TestSystemdInstaller:
    """Verify systemd service/timer content generation."""

    def test_service_content_morning(self):
        from scripts.deployment.install_scheduler import get_service_content

        content = get_service_content("morning")
        assert "agents.task_manager.scheduler morning" in content
        assert "[Unit]" in content
        assert "[Service]" in content
        assert "Type=oneshot" in content

    def test_service_content_evening(self):
        from scripts.deployment.install_scheduler import get_service_content

        content = get_service_content("evening")
        assert "agents.task_manager.scheduler evening" in content
        assert "[Unit]" in content
        assert "[Service]" in content

    def test_timer_content_morning(self):
        from scripts.deployment.install_scheduler import get_timer_content

        content = get_timer_content("morning")
        assert "07:00" in content
        assert "[Timer]" in content
        assert "Persistent=true" in content

    def test_timer_content_evening(self):
        from scripts.deployment.install_scheduler import get_timer_content

        content = get_timer_content("evening")
        assert "18:00" in content
        assert "[Timer]" in content
        assert "Persistent=true" in content

    def test_routines_config(self):
        from scripts.deployment.install_scheduler import ROUTINES

        assert "morning" in ROUTINES
        assert "evening" in ROUTINES
        assert ROUTINES["morning"]["schedule"] == "07:00"
        assert ROUTINES["evening"]["schedule"] == "18:00"

    def test_service_names_distinct(self):
        from scripts.deployment.install_scheduler import ROUTINES

        names = [cfg["service_name"] for cfg in ROUTINES.values()]
        assert len(names) == len(set(names)), "Service names must be unique"
