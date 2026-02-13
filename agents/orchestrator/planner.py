"""Task planner that uses an LLM to decompose tasks into subtasks.

The planner is invoked by the orchestrator state machine at the PLAN phase.
It makes a single LLM call to decompose a parent task into concrete subtasks.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from anthropic import AsyncAnthropic

from .models import AutonomyTier, Task
from .prompts import PLANNER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class PlanningError(Exception):
    """Raised when the planner fails to produce valid subtasks."""


async def plan_task(
    task: Task,
    *,
    model: str = "sonnet",
    max_subtasks: int = 6,
    api_key: str | None = None,
) -> list[Task]:
    """Decompose a task into subtasks using an LLM.

    Makes a single Claude API call with the planner prompt. Parses the
    structured JSON response into Task objects linked to the parent.

    Args:
        task: The parent task to decompose.
        model: Claude model to use for planning (short name or full ID).
        max_subtasks: Maximum number of subtasks to generate.
        api_key: Anthropic API key (defaults to env var).

    Returns:
        List of subtask Task objects with parent_id set.

    Raises:
        PlanningError: If the LLM response cannot be parsed as valid subtasks.
    """
    client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    system_prompt = PLANNER_SYSTEM_PROMPT.format(max_subtasks=max_subtasks)

    user_message = (
        f"Task: {task.title}\n\n"
        f"Description: {task.description}\n\n"
        f"Category: {task.category}\n"
        f"Priority: {task.priority}\n"
        f"Autonomy Tier: {task.autonomy_tier} "
        f"({AutonomyTier(task.autonomy_tier).name})\n"
        f"Tags: {', '.join(task.tags) if task.tags else 'none'}"
    )

    if task.metadata:
        user_message += f"\n\nAdditional context:\n{json.dumps(task.metadata, indent=2)}"

    logger.info(f"Planning task {task.id}: {task.title}")

    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    # Extract text from response
    raw_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            raw_text += block.text

    subtasks = _parse_subtasks(raw_text, parent=task)

    logger.info(f"Planned {len(subtasks)} subtasks for task {task.id}")
    return subtasks


def _parse_subtasks(raw_text: str, parent: Task) -> list[Task]:
    """Parse LLM response into Task objects.

    Handles JSON extraction from responses that may contain markdown
    code fences or extra text.

    Args:
        raw_text: Raw LLM response text.
        parent: Parent task to link subtasks to.

    Returns:
        List of Task objects.

    Raises:
        PlanningError: If the response cannot be parsed as valid JSON subtasks.
    """
    # Strip markdown code fences if present
    text = raw_text.strip()
    if text.startswith("```"):
        # Remove opening fence (possibly with language tag)
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        items: list[dict[str, Any]] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanningError(
            f"LLM returned unparseable response (not valid JSON). "
            f"First 200 chars: {text[:200]}"
        ) from exc

    if not isinstance(items, list):
        items = [items]

    if not items:
        raise PlanningError("LLM returned an empty subtask list")

    subtasks: list[Task] = []
    for item in items:
        if not isinstance(item, dict):
            logger.warning(f"Skipping non-dict subtask item: {item!r}")
            continue

        tier_value = item.get("autonomy_tier", parent.autonomy_tier)
        try:
            tier = AutonomyTier(tier_value)
        except ValueError:
            tier = parent.autonomy_tier

        subtask = Task(
            title=item.get("title", "Untitled subtask"),
            description=item.get("description", ""),
            parent_id=parent.id,
            priority=item.get("priority", parent.priority),
            tags=item.get("tags", []),
            autonomy_tier=tier,
            category=parent.category,
            depth=parent.depth + 1,
        )
        subtasks.append(subtask)

    if not subtasks:
        raise PlanningError("No valid subtasks could be parsed from LLM response")

    return subtasks
