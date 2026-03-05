"""PollingAgent — base class for agents that poll for work items and process them.

Extracts the general-purpose pattern from PR Shepherd into a reusable base:

    poll -> diagnose -> act -> (verify) -> escalate or complete

Subclasses implement the abstract methods to define their specific data source,
diagnosis logic, action steps, and escalation rules.

Example usage::

    class DependencyUpdater(PollingAgent[DepWorkItem, DepDiagnosis, DepResult]):
        async def poll(self) -> list[DepWorkItem]:
            return await check_outdated_deps()

        async def diagnose(self, item: DepWorkItem) -> DepDiagnosis:
            return DepDiagnosis(outdated=True, current="1.0", latest="2.0")

        async def act(self, item: DepWorkItem, diagnosis: DepDiagnosis) -> DepResult:
            return await attempt_upgrade(item, diagnosis)

        async def should_escalate(self, item: DepWorkItem, result: DepResult) -> bool:
            return not result.success

        async def escalate(self, item: DepWorkItem, result: DepResult) -> None:
            await notify_maintainer(item, result)
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

logger = logging.getLogger(__name__)


class WorkItemStatus(str, Enum):
    """Generic lifecycle status for a polled work item."""

    DISCOVERED = "discovered"
    DIAGNOSING = "diagnosing"
    ACTING = "acting"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class PollingAgentConfig:
    """Base configuration for any polling agent.

    Subclasses can extend this with additional fields specific to their
    domain (e.g. repos list, label filters, merge method).
    """

    poll_interval: int = 60  # seconds between poll cycles
    max_retries: int = 3  # max action attempts per work item
    dry_run: bool = False
    max_concurrent_items: int = 5  # max items to process in parallel


@dataclass
class ProcessingRecord:
    """Tracks processing state for a single work item within a poll cycle."""

    item_id: str
    status: WorkItemStatus = WorkItemStatus.DISCOVERED
    attempt: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    error: str | None = None


class PollingAgent[WorkItemT, DiagnosisT, ActionResultT](ABC):
    """Base class for agents that poll a data source and process work items.

    The processing pipeline for each work item is:

    1. **poll** — discover work items from a data source
    2. **get_item_id** — extract a unique identifier for tracking
    3. **diagnose** — analyze the work item to determine what action is needed
    4. **act** — perform the corrective/processing action
    5. **should_escalate** — decide if the result requires escalation
    6. **escalate** — handle escalation (notify, comment, create issue, etc.)

    Subclasses MUST implement all abstract methods. The base class handles:
    - Poll loop timing
    - Retry tracking
    - Error handling and logging
    - Dry-run support (skips act/escalate when config.dry_run is True)
    """

    def __init__(self, config: PollingAgentConfig) -> None:
        self.config = config
        self._running = False

    async def run(self) -> None:
        """Main loop: poll, process, sleep, repeat.

        Runs indefinitely until cancelled or ``stop()`` is called.
        """
        self._running = True
        logger.info(
            f"{self.__class__.__name__} starting — "
            f"poll_interval={self.config.poll_interval}s, "
            f"max_retries={self.config.max_retries}, "
            f"dry_run={self.config.dry_run}"
        )
        while self._running:
            try:
                await self.run_once()
            except Exception:
                logger.exception(f"{self.__class__.__name__}: unhandled error in poll cycle")
            logger.info(f"Sleeping {self.config.poll_interval}s before next poll")
            await asyncio.sleep(self.config.poll_interval)

    def stop(self) -> None:
        """Signal the polling loop to stop after the current cycle."""
        self._running = False

    async def run_once(self) -> list[ProcessingRecord]:
        """Execute a single poll-and-process cycle.

        Returns a list of ``ProcessingRecord`` objects describing what happened.
        """
        items = await self.poll()
        logger.info(f"{self.__class__.__name__}: polled {len(items)} work item(s)")

        records: list[ProcessingRecord] = []
        for item in items:
            item_id = self.get_item_id(item)
            record = ProcessingRecord(item_id=item_id)

            try:
                await self._process_item(item, record)
            except Exception:
                logger.exception(f"{self.__class__.__name__}: unhandled error processing {item_id}")
                record.status = WorkItemStatus.FAILED
                record.error = "unhandled exception"

            record.completed_at = datetime.now(UTC)
            records.append(record)

        return records

    async def _process_item(self, item: WorkItemT, record: ProcessingRecord) -> None:
        """Process a single work item through the full pipeline."""
        item_id = record.item_id

        # 1. Diagnose
        record.status = WorkItemStatus.DIAGNOSING
        diagnosis = await self.diagnose(item)

        if await self.should_skip(item, diagnosis):
            record.status = WorkItemStatus.SKIPPED
            logger.info(f"{item_id}: skipped after diagnosis")
            return

        # 2. Check retry budget
        record.attempt = await self.get_attempt_count(item) + 1
        if record.attempt > self.config.max_retries:
            logger.warning(
                f"{item_id}: max retries ({self.config.max_retries}) exceeded, escalating"
            )
            record.status = WorkItemStatus.ESCALATED
            if not self.config.dry_run:
                # Create a "max retries exceeded" result for escalation
                result = await self.on_max_retries_exceeded(item, diagnosis)
                await self.escalate(item, result)
            return

        # 3. Act
        record.status = WorkItemStatus.ACTING
        if self.config.dry_run:
            logger.info(f"[dry-run] Would act on {item_id} (attempt #{record.attempt})")
            return

        result = await self.act(item, diagnosis)

        # 4. Check for escalation
        if await self.should_escalate(item, result):
            record.status = WorkItemStatus.ESCALATED
            await self.escalate(item, result)
        else:
            record.status = WorkItemStatus.COMPLETED
            logger.info(f"{item_id}: completed successfully")

    # ── Abstract methods that subclasses MUST implement ──────────────

    @abstractmethod
    async def poll(self) -> list[WorkItemT]:
        """Fetch work items from the data source.

        Called once per poll cycle. Should return all items that need
        processing (the base class handles deduplication and retry tracking).
        """

    @abstractmethod
    def get_item_id(self, item: WorkItemT) -> str:
        """Return a unique string identifier for a work item.

        Used for logging and tracking. Should be stable across poll cycles
        (e.g. ``"owner/repo#123"`` for a PR).
        """

    @abstractmethod
    async def diagnose(self, item: WorkItemT) -> DiagnosisT:
        """Analyze a work item to determine what action is needed.

        For a PR shepherd, this checks CI status. For a dependency updater,
        this checks which deps are outdated. For a log monitor, this
        classifies anomalies.
        """

    @abstractmethod
    async def act(self, item: WorkItemT, diagnosis: DiagnosisT) -> ActionResultT:
        """Take action on a work item based on its diagnosis.

        For a PR shepherd, this runs Claude Code to fix CI. For a dependency
        updater, this attempts an upgrade and runs tests.

        Should return a result object that ``should_escalate`` can inspect.
        """

    @abstractmethod
    async def should_escalate(self, item: WorkItemT, result: ActionResultT) -> bool:
        """Decide whether the action result requires escalation.

        Return True to trigger ``escalate()``. Called after every ``act()``.
        """

    @abstractmethod
    async def escalate(self, item: WorkItemT, result: ActionResultT) -> None:
        """Handle escalation for a work item.

        Typical actions: post a comment, send a notification, create an issue,
        or alert a human.
        """

    # ── Optional hooks that subclasses CAN override ──────────────────

    async def should_skip(self, item: WorkItemT, diagnosis: DiagnosisT) -> bool:
        """Return True to skip processing this item after diagnosis.

        Override this to filter out items that don't need action (e.g. a PR
        whose checks are still pending, or a dependency that's already
        up-to-date).

        Default: never skip.
        """
        return False

    async def get_attempt_count(self, item: WorkItemT) -> int:
        """Return how many times this item has been acted on previously.

        Override to implement persistent retry tracking (e.g. counting
        comments on a PR, reading from a database). The default returns 0,
        meaning every poll cycle treats the item as a first attempt.
        """
        return 0

    async def on_max_retries_exceeded(
        self, item: WorkItemT, diagnosis: DiagnosisT
    ) -> ActionResultT:
        """Create an ActionResult to pass to ``escalate()`` when max retries are exceeded.

        Subclasses should override this to provide a meaningful result object
        for the escalation handler. The default raises NotImplementedError
        because the result type is generic and cannot be constructed here.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement on_max_retries_exceeded() "
            f"or handle max retries in should_escalate()"
        )
