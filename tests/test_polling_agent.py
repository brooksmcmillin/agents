"""Tests for the PollingAgent base class."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from agent_framework.core.polling_agent import (
    PollingAgent,
    PollingAgentConfig,
    ProcessingRecord,
    WorkItemStatus,
)

# ── Test fixtures: concrete implementation for testing ───────────────


@dataclass
class FakeWorkItem:
    item_id: str
    needs_action: bool = True
    should_fail: bool = False
    previous_attempts: int = 0


@dataclass
class FakeDiagnosis:
    actionable: bool = True
    detail: str = ""


@dataclass
class FakeResult:
    success: bool = True
    message: str = ""


class FakePollingAgent(PollingAgent[FakeWorkItem, FakeDiagnosis, FakeResult]):
    """Concrete PollingAgent for testing."""

    def __init__(
        self,
        config: PollingAgentConfig,
        items: list[FakeWorkItem] | None = None,
    ) -> None:
        super().__init__(config)
        self.items_to_return = items or []
        self.diagnosed: list[str] = []
        self.acted_on: list[str] = []
        self.escalated_items: list[str] = []
        self.skipped_items: list[str] = []

    async def poll(self) -> list[FakeWorkItem]:
        return self.items_to_return

    def get_item_id(self, item: FakeWorkItem) -> str:
        return item.item_id

    async def diagnose(self, item: FakeWorkItem) -> FakeDiagnosis:
        self.diagnosed.append(item.item_id)
        return FakeDiagnosis(actionable=item.needs_action)

    async def should_skip(self, item: FakeWorkItem, diagnosis: FakeDiagnosis) -> bool:
        if not diagnosis.actionable:
            self.skipped_items.append(item.item_id)
            return True
        return False

    async def get_attempt_count(self, item: FakeWorkItem) -> int:
        return item.previous_attempts

    async def act(self, item: FakeWorkItem, diagnosis: FakeDiagnosis) -> FakeResult:
        self.acted_on.append(item.item_id)
        if item.should_fail:
            return FakeResult(success=False, message="action failed")
        return FakeResult(success=True)

    async def should_escalate(self, item: FakeWorkItem, result: FakeResult) -> bool:
        return not result.success

    async def escalate(self, item: FakeWorkItem, result: FakeResult) -> None:
        self.escalated_items.append(item.item_id)

    async def on_max_retries_exceeded(
        self, item: FakeWorkItem, diagnosis: FakeDiagnosis
    ) -> FakeResult:
        return FakeResult(success=False, message="max retries exceeded")


# ── Tests ────────────────────────────────────────────────────────────


class TestPollingAgentConfig:
    def test_defaults(self) -> None:
        config = PollingAgentConfig()
        assert config.poll_interval == 60
        assert config.max_retries == 3
        assert config.dry_run is False
        assert config.max_concurrent_items == 5

    def test_custom_values(self) -> None:
        config = PollingAgentConfig(poll_interval=120, max_retries=5, dry_run=True)
        assert config.poll_interval == 120
        assert config.max_retries == 5
        assert config.dry_run is True


class TestPollingAgentRunOnce:
    @pytest.mark.asyncio
    async def test_empty_poll(self) -> None:
        agent = FakePollingAgent(PollingAgentConfig(), items=[])
        records = await agent.run_once()
        assert records == []

    @pytest.mark.asyncio
    async def test_single_item_success(self) -> None:
        item = FakeWorkItem(item_id="test-1")
        agent = FakePollingAgent(PollingAgentConfig(), items=[item])
        records = await agent.run_once()

        assert len(records) == 1
        assert records[0].item_id == "test-1"
        assert records[0].status == WorkItemStatus.COMPLETED
        assert "test-1" in agent.diagnosed
        assert "test-1" in agent.acted_on
        assert "test-1" not in agent.escalated_items

    @pytest.mark.asyncio
    async def test_multiple_items(self) -> None:
        items = [
            FakeWorkItem(item_id="a"),
            FakeWorkItem(item_id="b"),
            FakeWorkItem(item_id="c"),
        ]
        agent = FakePollingAgent(PollingAgentConfig(), items=items)
        records = await agent.run_once()

        assert len(records) == 3
        assert all(r.status == WorkItemStatus.COMPLETED for r in records)
        assert agent.acted_on == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_skip_item(self) -> None:
        item = FakeWorkItem(item_id="skip-me", needs_action=False)
        agent = FakePollingAgent(PollingAgentConfig(), items=[item])
        records = await agent.run_once()

        assert len(records) == 1
        assert records[0].status == WorkItemStatus.SKIPPED
        assert "skip-me" in agent.diagnosed
        assert "skip-me" in agent.skipped_items
        assert "skip-me" not in agent.acted_on

    @pytest.mark.asyncio
    async def test_escalation_on_failure(self) -> None:
        item = FakeWorkItem(item_id="fail-1", should_fail=True)
        agent = FakePollingAgent(PollingAgentConfig(), items=[item])
        records = await agent.run_once()

        assert len(records) == 1
        assert records[0].status == WorkItemStatus.ESCALATED
        assert "fail-1" in agent.acted_on
        assert "fail-1" in agent.escalated_items

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self) -> None:
        item = FakeWorkItem(item_id="retry-exceeded", previous_attempts=5)
        config = PollingAgentConfig(max_retries=3)
        agent = FakePollingAgent(config, items=[item])
        records = await agent.run_once()

        assert len(records) == 1
        assert records[0].status == WorkItemStatus.ESCALATED
        assert "retry-exceeded" not in agent.acted_on
        assert "retry-exceeded" in agent.escalated_items

    @pytest.mark.asyncio
    async def test_dry_run_skips_action(self) -> None:
        item = FakeWorkItem(item_id="dry-1")
        config = PollingAgentConfig(dry_run=True)
        agent = FakePollingAgent(config, items=[item])
        records = await agent.run_once()

        assert len(records) == 1
        # In dry_run mode, item is not acted on
        assert "dry-1" not in agent.acted_on
        assert "dry-1" not in agent.escalated_items

    @pytest.mark.asyncio
    async def test_dry_run_also_skips_max_retry_escalation(self) -> None:
        item = FakeWorkItem(item_id="dry-retry", previous_attempts=10)
        config = PollingAgentConfig(dry_run=True, max_retries=3)
        agent = FakePollingAgent(config, items=[item])
        records = await agent.run_once()

        assert len(records) == 1
        assert records[0].status == WorkItemStatus.ESCALATED
        # Escalation is still skipped in dry_run mode
        assert "dry-retry" not in agent.escalated_items


class TestPollingAgentLifecycle:
    @pytest.mark.asyncio
    async def test_stop_stops_run_loop(self) -> None:
        agent = FakePollingAgent(PollingAgentConfig(poll_interval=0), items=[])
        # Start run in background, stop after a short delay
        task = asyncio.create_task(agent.run())
        await asyncio.sleep(0.05)
        agent.stop()
        # Give it time to exit
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except TimeoutError:
            task.cancel()
            pytest.fail("run() did not stop after stop() was called")

    @pytest.mark.asyncio
    async def test_processing_record_timestamps(self) -> None:
        item = FakeWorkItem(item_id="ts-1")
        agent = FakePollingAgent(PollingAgentConfig(), items=[item])
        records = await agent.run_once()

        assert records[0].started_at is not None
        assert records[0].completed_at is not None
        assert records[0].completed_at >= records[0].started_at

    @pytest.mark.asyncio
    async def test_attempt_tracking(self) -> None:
        item = FakeWorkItem(item_id="attempt-1", previous_attempts=2)
        config = PollingAgentConfig(max_retries=5)
        agent = FakePollingAgent(config, items=[item])
        records = await agent.run_once()

        assert records[0].attempt == 3  # previous 2 + 1
        assert records[0].status == WorkItemStatus.COMPLETED


class TestPollingAgentErrorHandling:
    @pytest.mark.asyncio
    async def test_diagnose_exception_marks_failed(self) -> None:
        """If diagnose() raises, the item should be marked FAILED."""

        class BrokenDiagnoseAgent(FakePollingAgent):
            async def diagnose(self, item: FakeWorkItem) -> FakeDiagnosis:
                raise RuntimeError("diagnose exploded")

        item = FakeWorkItem(item_id="broken-1")
        agent = BrokenDiagnoseAgent(PollingAgentConfig(), items=[item])
        records = await agent.run_once()

        assert len(records) == 1
        assert records[0].status == WorkItemStatus.FAILED
        assert records[0].error == "unhandled exception"

    @pytest.mark.asyncio
    async def test_act_exception_marks_failed(self) -> None:
        """If act() raises, the item should be marked FAILED."""

        class BrokenActAgent(FakePollingAgent):
            async def act(self, item: FakeWorkItem, diagnosis: FakeDiagnosis) -> FakeResult:
                raise RuntimeError("act exploded")

        item = FakeWorkItem(item_id="broken-2")
        agent = BrokenActAgent(PollingAgentConfig(), items=[item])
        records = await agent.run_once()

        assert len(records) == 1
        assert records[0].status == WorkItemStatus.FAILED

    @pytest.mark.asyncio
    async def test_escalate_exception_marks_failed(self) -> None:
        """If escalate() raises, the item should be marked FAILED."""

        class BrokenEscalateAgent(FakePollingAgent):
            async def escalate(self, item: FakeWorkItem, result: FakeResult) -> None:
                raise RuntimeError("escalate exploded")

        item = FakeWorkItem(item_id="broken-3", should_fail=True)
        agent = BrokenEscalateAgent(PollingAgentConfig(), items=[item])
        records = await agent.run_once()

        assert len(records) == 1
        assert records[0].status == WorkItemStatus.FAILED

    @pytest.mark.asyncio
    async def test_mixed_success_and_failure(self) -> None:
        """One failing item should not prevent processing others."""
        items = [
            FakeWorkItem(item_id="ok-1"),
            FakeWorkItem(item_id="fail-1", should_fail=True),
            FakeWorkItem(item_id="ok-2"),
        ]
        agent = FakePollingAgent(PollingAgentConfig(), items=items)
        records = await agent.run_once()

        assert len(records) == 3
        assert records[0].status == WorkItemStatus.COMPLETED
        assert records[1].status == WorkItemStatus.ESCALATED
        assert records[2].status == WorkItemStatus.COMPLETED


class TestWorkItemStatus:
    def test_status_values(self) -> None:
        assert WorkItemStatus.DISCOVERED == "discovered"
        assert WorkItemStatus.COMPLETED == "completed"
        assert WorkItemStatus.ESCALATED == "escalated"
        assert WorkItemStatus.SKIPPED == "skipped"
        assert WorkItemStatus.FAILED == "failed"


class TestProcessingRecord:
    def test_defaults(self) -> None:
        record = ProcessingRecord(item_id="test")
        assert record.item_id == "test"
        assert record.status == WorkItemStatus.DISCOVERED
        assert record.attempt == 0
        assert record.completed_at is None
        assert record.error is None
