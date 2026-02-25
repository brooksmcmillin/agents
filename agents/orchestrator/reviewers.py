"""Review gates for the orchestrator.

Review agents are targeted LLM calls (not full conversational agents) that
analyze diffs and return structured verdicts. The orchestrator invokes them
at the REVIEW phase and uses the results to decide whether to proceed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from anthropic import AsyncAnthropic

from .models import (
    OrchestratorConfig,
    Task,
    resolve_model,
)
from .prompts import CODE_REVIEW_SYSTEM_PROMPT, SECURITY_REVIEW_SYSTEM_PROMPT


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ReviewVerdict(str, Enum):
    """Outcome of a review gate."""

    PASSED = "passed"
    FAILED = "failed"
    NEEDS_CHANGES = "needs_changes"


@dataclass
class ReviewIssue:
    """A specific issue found during review."""

    title: str
    description: str
    severity: str = "medium"  # low, medium, high, critical
    file_path: str | None = None
    line_number: int | None = None
    suggestion: str | None = None


@dataclass
class ReviewResult:
    """Result from a review agent."""

    reviewer: str
    verdict: ReviewVerdict
    summary: str
    issues: list[ReviewIssue] = field(default_factory=list)
    raw_output: str = ""
    diff_truncated: bool = False
    reviewed_at: datetime = field(default_factory=_utcnow)


logger = logging.getLogger(__name__)


async def run_code_review(
    task: Task,
    diff: str,
    config: OrchestratorConfig,
    api_key: str | None = None,
) -> ReviewResult:
    """Run code review on the worker's output.

    Args:
        task: The task that was executed.
        diff: Git diff of the changes.
        config: Orchestrator configuration.
        api_key: Anthropic API key.

    Returns:
        ReviewResult with verdict and issues.
    """
    return await _run_review(
        reviewer_name="code-review",
        system_prompt=CODE_REVIEW_SYSTEM_PROMPT,
        task=task,
        diff=diff,
        model=config.planner_model,
        api_key=api_key,
    )


async def run_security_review(
    task: Task,
    diff: str,
    config: OrchestratorConfig,
    api_key: str | None = None,
) -> ReviewResult:
    """Run security review on the worker's output.

    Args:
        task: The task that was executed.
        diff: Git diff of the changes.
        config: Orchestrator configuration.
        api_key: Anthropic API key.

    Returns:
        ReviewResult with verdict and issues.
    """
    return await _run_review(
        reviewer_name="security-review",
        system_prompt=SECURITY_REVIEW_SYSTEM_PROMPT,
        task=task,
        diff=diff,
        model=config.planner_model,
        api_key=api_key,
    )


def _truncate_at_line_boundary(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate text at a line boundary to avoid cutting mid-line or mid-hunk.

    Args:
        text: The text to potentially truncate.
        max_chars: Maximum character count.

    Returns:
        Tuple of (truncated_text, was_truncated).
    """
    if len(text) <= max_chars:
        return text, False

    # Find the last newline before the limit
    cut_point = text.rfind("\n", 0, max_chars)
    if cut_point == -1:
        # No newline found; fall back to hard cut
        cut_point = max_chars

    return text[:cut_point], True


async def _run_review(
    reviewer_name: str,
    system_prompt: str,
    task: Task,
    diff: str,
    model: str = "sonnet",
    api_key: str | None = None,
) -> ReviewResult:
    """Run a review agent on a diff.

    Makes a single LLM call with the review prompt and parses the
    structured JSON response.

    Args:
        reviewer_name: Name of the reviewer for logging.
        system_prompt: System prompt for the reviewer.
        task: The task being reviewed.
        diff: Git diff to review.
        model: Claude model to use.
        api_key: Anthropic API key.

    Returns:
        ReviewResult with verdict and issues.
    """
    if not diff.strip():
        logger.warning(f"{reviewer_name}: No diff to review for task {task.id}")
        return ReviewResult(
            reviewer=reviewer_name,
            verdict=ReviewVerdict.PASSED,
            summary="No changes to review.",
        )

    # Truncate at line boundary to avoid cutting mid-hunk
    max_diff_chars = 50000
    diff, truncated = _truncate_at_line_boundary(diff, max_diff_chars)

    user_message = (
        f"## Task\n{task.title}\n\n"
        f"## Description\n{task.description}\n\n"
        f"## Diff\n```diff\n{diff}\n```"
    )
    if truncated:
        user_message += (
            "\n\n(Note: diff was truncated at a line boundary due to size. "
            "Review what is shown; further changes exist beyond the cutoff.)"
        )

    logger.info(f"Running {reviewer_name} for task {task.id}")

    model_id = resolve_model(model)

    client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
    try:
        response = await client.messages.create(
            model=model_id,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = "".join(getattr(block, "text", "") for block in response.content)

        result = _parse_review_result(reviewer_name, raw_text)
        result.diff_truncated = truncated
        return result

    except Exception as e:
        logger.error(f"{reviewer_name} failed for task {task.id}: {e}")
        return ReviewResult(
            reviewer=reviewer_name,
            verdict=ReviewVerdict.FAILED,
            summary=f"Review failed with error: {e}",
            raw_output=str(e),
        )
    finally:
        await client.close()


def _parse_review_result(reviewer_name: str, raw_text: str) -> ReviewResult:
    """Parse LLM review response into a ReviewResult.

    Args:
        reviewer_name: Name of the reviewer.
        raw_text: Raw LLM response.

    Returns:
        ReviewResult parsed from the response.
    """
    from shared.json_parsing import strip_markdown_fences

    text = strip_markdown_fences(raw_text)

    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse {reviewer_name} response: {text[:200]}")
        return ReviewResult(
            reviewer=reviewer_name,
            verdict=ReviewVerdict.NEEDS_CHANGES,
            summary=f"Could not parse review response. Raw: {text[:500]}",
            raw_output=raw_text,
        )

    # Parse verdict
    verdict_str = data.get("verdict", "needs_changes")
    try:
        verdict = ReviewVerdict(verdict_str)
    except ValueError:
        verdict = ReviewVerdict.NEEDS_CHANGES

    # Parse issues
    issues: list[ReviewIssue] = []
    for issue_data in data.get("issues", []):
        if not isinstance(issue_data, dict):
            continue
        issues.append(
            ReviewIssue(
                title=issue_data.get("title", "Unknown issue"),
                description=issue_data.get("description", ""),
                severity=issue_data.get("severity", "medium"),
                file_path=issue_data.get("file_path"),
                line_number=issue_data.get("line_number"),
                suggestion=issue_data.get("suggestion"),
            )
        )

    return ReviewResult(
        reviewer=reviewer_name,
        verdict=verdict,
        summary=data.get("summary", ""),
        issues=issues,
        raw_output=raw_text,
    )
