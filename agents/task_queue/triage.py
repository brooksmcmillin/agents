"""LLM-powered task triage for the task queue runner.

Makes single Anthropic API calls to classify tasks as executable,
research-only, or not actionable.
"""

from __future__ import annotations

import json
import logging
import os

from anthropic import AsyncAnthropic

from .models import TriageResult, TriageVerdict, resolve_model
from .prompts import DEPENDENCY_DETECTION_PROMPT, TRIAGE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def triage_task(
    task: dict,
    available_tools: list[str],
    accumulated_context: str,
    model: str = "haiku",
    api_key: str | None = None,
) -> TriageResult:
    """Triage a single task using an LLM call.

    Args:
        task: Task dict from MCP (has id, title, description, etc.).
        available_tools: List of available MCP tool names for context.
        accumulated_context: Related context from previously processed tasks.
        model: Claude model to use.
        api_key: Anthropic API key (defaults to env var).

    Returns:
        TriageResult with verdict, confidence, and classification details.
    """
    client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
    try:
        user_message = _build_triage_user_message(task, available_tools, accumulated_context)

        logger.info(f"Triaging task {task.get('id')}: {task.get('title', '')[:60]}")

        response = await client.messages.create(
            model=resolve_model(model),
            max_tokens=2048,
            system=TRIAGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = "".join(getattr(block, "text", "") for block in response.content)
        result = _parse_triage_result(raw_text)

        logger.info(
            f"Triage result for {task.get('id')}: "
            f"{result.verdict.value} (confidence={result.confidence:.0%})"
        )
        return result

    except Exception as e:
        logger.error(f"Triage failed for task {task.get('id')}: {e}")
        return TriageResult(
            verdict=TriageVerdict.NOT_ACTIONABLE,
            confidence=0.0,
            reasoning=f"Triage failed: {e}",
            blocking_reason=f"Triage error: {e}",
        )
    finally:
        await client.close()


async def detect_dependencies(
    tasks: list[dict],
    model: str = "haiku",
    api_key: str | None = None,
) -> list[dict]:
    """Detect dependency relationships across a set of tasks.

    Args:
        tasks: List of task dicts.
        model: Claude model to use.
        api_key: Anthropic API key.

    Returns:
        List of dicts with task_id, depends_on, reason fields.
    """
    if len(tasks) < 2:
        return []

    client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
    try:
        task_descriptions = []
        for t in tasks:
            task_descriptions.append(
                f"- {t.get('id')}: {t.get('title', '')} ({t.get('description', '')[:100]})"
            )
        user_message = "Tasks:\n" + "\n".join(task_descriptions)

        response = await client.messages.create(
            model=resolve_model(model),
            max_tokens=1024,
            system=DEPENDENCY_DETECTION_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = "".join(getattr(block, "text", "") for block in response.content)
        parsed = _strip_and_parse_json(raw_text)
        if isinstance(parsed, list):
            return parsed
        return []

    except Exception as e:
        logger.error(f"Dependency detection failed: {e}")
        return []
    finally:
        await client.close()


def _build_triage_user_message(
    task: dict,
    tools: list[str],
    context: str,
) -> str:
    """Build the user message for triage LLM call."""
    parts = [
        f"Task ID: {task.get('id', 'unknown')}",
        f"Title: {task.get('title', 'Untitled')}",
        f"Description: {task.get('description', 'No description')}",
        f"Priority: {task.get('priority', 'medium')}",
        f"Category: {task.get('category', 'uncategorized')}",
        f"Due date: {task.get('due_date', 'none')}",
        f"Tags: {', '.join(task.get('tags', [])) or 'none'}",
    ]

    # Include existing classification if present
    action_type = task.get("action_type")
    if action_type:
        parts.append(f"Action type (pre-classified): {action_type}")

    autonomy_tier = task.get("autonomy_tier")
    if autonomy_tier:
        parts.append(f"Autonomy tier (pre-classified): {autonomy_tier}")

    agent_notes = task.get("agent_notes")
    if agent_notes:
        parts.append(f"\nExisting agent notes:\n{agent_notes[:500]}")

    if tools:
        parts.append(f"\nAvailable tools: {', '.join(tools[:30])}")

    if context:
        parts.append(f"\nContext from related tasks:\n{context[:1000]}")

    return "\n".join(parts)


def _parse_triage_result(raw_text: str) -> TriageResult:
    """Parse LLM response into a TriageResult.

    Handles markdown fences, validates fields, and clamps values.
    Falls back to NOT_ACTIONABLE on any parse error.
    """
    parsed = _strip_and_parse_json(raw_text)
    if not isinstance(parsed, dict):
        logger.warning(f"Triage response was not a JSON object: {raw_text[:200]}")
        return TriageResult(
            verdict=TriageVerdict.NOT_ACTIONABLE,
            confidence=0.0,
            reasoning="Failed to parse triage response as JSON",
            blocking_reason="Unparseable triage response",
        )

    # Parse verdict
    verdict_str = parsed.get("verdict", "not_actionable")
    try:
        verdict = TriageVerdict(verdict_str)
    except ValueError:
        verdict = TriageVerdict.NOT_ACTIONABLE

    # Parse confidence (clamp to 0-1)
    confidence = parsed.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = max(0.0, min(1.0, float(confidence)))

    # Parse optional fields
    estimated_hours = parsed.get("estimated_hours")
    if estimated_hours is not None:
        try:
            estimated_hours = float(estimated_hours)
        except (ValueError, TypeError):
            estimated_hours = None

    autonomy_tier = parsed.get("suggested_autonomy_tier")
    if autonomy_tier is not None:
        try:
            autonomy_tier = int(autonomy_tier)
            autonomy_tier = max(1, min(4, autonomy_tier))
        except (ValueError, TypeError):
            autonomy_tier = None

    return TriageResult(
        verdict=verdict,
        confidence=confidence,
        reasoning=parsed.get("reasoning", ""),
        estimated_hours=estimated_hours,
        suggested_action_type=parsed.get("suggested_action_type"),
        suggested_autonomy_tier=autonomy_tier,
        suggested_dependencies=parsed.get("suggested_dependencies", []),
        pre_research_queries=parsed.get("pre_research_queries", []),
        blocking_reason=parsed.get("blocking_reason"),
    )


def _strip_and_parse_json(text: str) -> dict | list | None:
    """Extract and parse JSON from LLM response text.

    Handles markdown fences, leading/trailing text, and extracts
    the first complete JSON object or array found.
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences
    if "```" in text:
        # Extract content between first ``` and last ```
        parts = text.split("```")
        if len(parts) >= 3:
            # parts[1] is the content inside fences (may have "json\n" prefix)
            inner = parts[1]
            if inner.startswith(("json", "JSON")):
                inner = inner[4:]
            inner = inner.strip()
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                pass

    # Find first { ... } or [ ... ] by scanning for balanced braces
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        # Find the matching closing brace by counting depth
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    return None
