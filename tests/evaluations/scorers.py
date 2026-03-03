"""Scoring functions for evaluating agent responses.

All scorers normalize to a 1-5 scale:
  5 = Perfect    4 = Good    3 = Acceptable    2 = Poor    1 = Failure
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

from anthropic import AsyncAnthropic

from .models import EvalCase

logger = logging.getLogger(__name__)


class Scorer(ABC):
    """Base class for evaluation scorers."""

    @abstractmethod
    async def score(
        self, case: EvalCase, response: str, tools_called: list[str]
    ) -> tuple[float, str]:
        """Score an agent response.

        Args:
            case: The evaluation test case.
            response: The agent's response text.
            tools_called: List of tool names called during the response.

        Returns:
            Tuple of (score 1-5, scorer name).
        """
        ...


class LLMJudgeScorer(Scorer):
    """Uses Claude Haiku as a judge to evaluate response quality."""

    JUDGE_PROMPT = """You are evaluating an AI agent's response. Rate it on a 1-5 scale.

<user_input>
{input}
</user_input>

<expected_behavior>
{expected}
</expected_behavior>

<agent_response>
{response}
</agent_response>

Rate the response:
5 = Perfect — fully meets expected behavior
4 = Good — meets expectations with minor gaps
3 = Acceptable — partially meets expectations
2 = Poor — significant gaps from expected behavior
1 = Failure — does not meet expected behavior at all

Reply with ONLY a single digit (1-5), nothing else."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        self.model = model
        self._client: AsyncAnthropic | None = None

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY required for LLM judge scorer")
            self._client = AsyncAnthropic(api_key=api_key)
        return self._client

    async def score(
        self, case: EvalCase, response: str, tools_called: list[str]
    ) -> tuple[float, str]:
        prompt = self.JUDGE_PROMPT.format(
            input=case.input,
            expected=case.expected,
            response=response[:2000],  # Truncate very long responses
        )

        try:
            client = self._get_client()
            result = await client.messages.create(
                model=self.model,
                max_tokens=8,
                messages=[{"role": "user", "content": prompt}],
            )
            text = result.content[0].text.strip()
            # Extract first digit from response
            for ch in text:
                if ch.isdigit() and 1 <= int(ch) <= 5:
                    return float(ch), "llm_judge"
            logger.warning(f"LLM judge returned unexpected output: {text!r}")
            return 3.0, "llm_judge"
        except Exception as e:
            logger.error(f"LLM judge scorer error: {e}")
            return 3.0, "llm_judge"


class KeywordScorer(Scorer):
    """Checks if expected keywords appear in the response."""

    async def score(
        self, case: EvalCase, response: str, tools_called: list[str]
    ) -> tuple[float, str]:
        if not case.expected_keywords:
            return 0.0, "keyword"  # Not applicable — will be excluded from composite

        response_lower = response.lower()
        matches = sum(1 for kw in case.expected_keywords if kw.lower() in response_lower)
        ratio = matches / len(case.expected_keywords)

        # Map ratio to 1-5 scale
        if ratio >= 1.0:
            score = 5.0
        elif ratio >= 0.75:
            score = 4.0
        elif ratio >= 0.5:
            score = 3.0
        elif ratio >= 0.25:
            score = 2.0
        else:
            score = 1.0

        return score, "keyword"


class ToolUseScorer(Scorer):
    """Verifies the agent called the expected tools."""

    async def score(
        self, case: EvalCase, response: str, tools_called: list[str]
    ) -> tuple[float, str]:
        if not case.expected_tools:
            return 0.0, "tool_use"  # Not applicable

        expected_set = set(case.expected_tools)
        called_set = set(tools_called)
        matched = expected_set & called_set
        ratio = len(matched) / len(expected_set) if expected_set else 0.0

        if ratio >= 1.0:
            score = 5.0
        elif ratio >= 0.75:
            score = 4.0
        elif ratio >= 0.5:
            score = 3.0
        elif ratio > 0:
            score = 2.0
        else:
            score = 1.0

        return score, "tool_use"


class CompositeScorer(Scorer):
    """Runs all applicable scorers and averages their scores.

    Scorers that return 0.0 (not applicable) are excluded from the average.
    Falls back to the LLM judge if no deterministic scorers apply.
    """

    def __init__(self, scorers: list[Scorer] | None = None) -> None:
        self.scorers = scorers or [
            LLMJudgeScorer(),
            KeywordScorer(),
            ToolUseScorer(),
        ]

    async def score(
        self, case: EvalCase, response: str, tools_called: list[str]
    ) -> tuple[float, str]:
        avg, _ = await self.score_detailed(case, response, tools_called)
        return avg, "composite"

    async def score_detailed(
        self, case: EvalCase, response: str, tools_called: list[str]
    ) -> tuple[float, dict[str, float]]:
        """Score and return per-scorer breakdown."""
        scores: dict[str, float] = {}
        for scorer in self.scorers:
            value, name = await scorer.score(case, response, tools_called)
            if value > 0:
                scores[name] = value

        if not scores:
            return 3.0, {}

        avg = sum(scores.values()) / len(scores)
        return round(avg, 2), scores
