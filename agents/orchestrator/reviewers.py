"""Review gates for the orchestrator.

Review agents are targeted LLM calls (not full conversational agents) that
analyze diffs and return structured verdicts. The orchestrator invokes them
at the REVIEW phase and uses the results to decide whether to proceed.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from anthropic import AsyncAnthropic

from .models import (
    OrchestratorConfig,
    ReviewIssue,
    ReviewResult,
    ReviewVerdict,
    Task,
)
from .prompts import CODE_REVIEW_SYSTEM_PROMPT, SECURITY_REVIEW_SYSTEM_PROMPT

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
        model=config.review_model,
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
        model=config.review_model,
        api_key=api_key,
    )


async def _run_review(
    reviewer_name: str,
    system_prompt: str,
    task: Task,
    diff: str,
    model: str = "claude-sonnet-4-5-20250929",
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

    client = AsyncAnthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    # Truncate very large diffs to stay within context limits
    max_diff_chars = 50000
    truncated = False
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars]
        truncated = True

    user_message = (
        f"## Task\n{task.title}\n\n"
        f"## Description\n{task.description}\n\n"
        f"## Diff\n```diff\n{diff}\n```"
    )
    if truncated:
        user_message += "\n\n(Note: diff was truncated due to size)"

    logger.info(f"Running {reviewer_name} for task {task.id}")

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        return _parse_review_result(reviewer_name, raw_text)

    except Exception as e:
        logger.error(f"{reviewer_name} failed for task {task.id}: {e}")
        return ReviewResult(
            reviewer=reviewer_name,
            verdict=ReviewVerdict.FAILED,
            summary=f"Review failed with error: {e}",
            raw_output=str(e),
        )


def _parse_review_result(reviewer_name: str, raw_text: str) -> ReviewResult:
    """Parse LLM review response into a ReviewResult.

    Args:
        reviewer_name: Name of the reviewer.
        raw_text: Raw LLM response.

    Returns:
        ReviewResult parsed from the response.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

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
