"""Unit tests for the evaluation framework.

These tests validate the framework's data models, scorers, and dataset loading
without calling the Anthropic API.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.evaluations.models import EvalCase, EvalResult, EvalRun, load_dataset
from tests.evaluations.scorers import (
    CompositeScorer,
    KeywordScorer,
    LLMJudgeScorer,
    ToolUseScorer,
)


# ── EvalCase ──────────────────────────────────────────────────────────


class TestEvalCase:
    def test_from_dict_minimal(self):
        case = EvalCase.from_dict({"input": "hello", "expected": "greet back"})
        assert case.input == "hello"
        assert case.expected == "greet back"
        assert case.tags == []
        assert case.expected_tools == []
        assert case.expected_keywords == []
        assert case.max_tokens is None

    def test_from_dict_full(self):
        case = EvalCase.from_dict({
            "input": "remember blue",
            "expected": "save memory",
            "tags": ["memory"],
            "expected_tools": ["save_memory"],
            "expected_keywords": ["blue", "saved"],
            "max_tokens": 100,
        })
        assert case.tags == ["memory"]
        assert case.expected_tools == ["save_memory"]
        assert case.expected_keywords == ["blue", "saved"]
        assert case.max_tokens == 100

    def test_from_dict_missing_required_raises(self):
        with pytest.raises(KeyError):
            EvalCase.from_dict({"input": "hello"})


# ── Dataset loading ───────────────────────────────────────────────────


class TestLoadDataset:
    def test_load_valid_jsonl(self, tmp_path: Path):
        dataset = tmp_path / "test.jsonl"
        dataset.write_text(
            '{"input": "hi", "expected": "greet"}\n'
            '{"input": "bye", "expected": "farewell"}\n'
        )
        cases = load_dataset(dataset)
        assert len(cases) == 2
        assert cases[0].input == "hi"
        assert cases[1].input == "bye"

    def test_load_skips_blank_lines(self, tmp_path: Path):
        dataset = tmp_path / "test.jsonl"
        dataset.write_text(
            '{"input": "hi", "expected": "greet"}\n'
            "\n"
            '{"input": "bye", "expected": "farewell"}\n'
        )
        cases = load_dataset(dataset)
        assert len(cases) == 2

    def test_load_skips_comments(self, tmp_path: Path):
        dataset = tmp_path / "test.jsonl"
        dataset.write_text(
            "# This is a comment\n"
            '{"input": "hi", "expected": "greet"}\n'
        )
        cases = load_dataset(dataset)
        assert len(cases) == 1

    def test_load_invalid_json_raises(self, tmp_path: Path):
        dataset = tmp_path / "test.jsonl"
        dataset.write_text("not valid json\n")
        with pytest.raises(ValueError, match="invalid test case"):
            load_dataset(dataset)


# ── EvalResult ────────────────────────────────────────────────────────


class TestEvalResult:
    def test_to_dict(self):
        case = EvalCase(input="hi", expected="greet")
        result = EvalResult(
            case=case,
            response="Hello!",
            score=4.0,
            tools_called=["save_memory"],
            input_tokens=50,
            output_tokens=20,
            latency_ms=150.5,
        )
        d = result.to_dict()
        assert d["input"] == "hi"
        assert d["response"] == "Hello!"
        assert d["score"] == 4.0
        assert d["tools_called"] == ["save_memory"]


# ── EvalRun ───────────────────────────────────────────────────────────


class TestEvalRun:
    def _make_result(self, score: float, tokens_in: int = 10, tokens_out: int = 5) -> EvalResult:
        case = EvalCase(input="test", expected="test")
        return EvalResult(
            case=case, response="ok", score=score,
            input_tokens=tokens_in, output_tokens=tokens_out,
            latency_ms=100.0,
        )

    def test_avg_score(self):
        run = EvalRun(agent_name="test")
        run.results = [self._make_result(5.0), self._make_result(3.0)]
        assert run.avg_score == 4.0

    def test_avg_score_empty(self):
        run = EvalRun(agent_name="test")
        assert run.avg_score == 0.0

    def test_total_tokens(self):
        run = EvalRun(agent_name="test")
        run.results = [self._make_result(5.0, 100, 50), self._make_result(3.0, 200, 100)]
        assert run.total_tokens == 450

    def test_pass_rate(self):
        run = EvalRun(agent_name="test")
        run.results = [
            self._make_result(5.0),
            self._make_result(3.0),
            self._make_result(2.0),
            self._make_result(1.0),
        ]
        assert run.pass_rate == 0.5

    def test_summary(self):
        run = EvalRun(agent_name="chatbot", variant="default")
        run.results = [self._make_result(4.0)]
        s = run.summary()
        assert s["agent_name"] == "chatbot"
        assert s["num_cases"] == 1
        assert s["avg_score"] == 4.0

    def test_save_and_load(self, tmp_path: Path):
        run = EvalRun(agent_name="chatbot")
        run.results = [self._make_result(4.0)]
        path = run.save(tmp_path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["agent_name"] == "chatbot"
        assert len(data["results"]) == 1


# ── KeywordScorer ─────────────────────────────────────────────────────


class TestKeywordScorer:
    @pytest.fixture
    def scorer(self):
        return KeywordScorer()

    @pytest.mark.asyncio
    async def test_all_keywords_match(self, scorer):
        case = EvalCase(input="test", expected="test", expected_keywords=["hello", "world"])
        score, name = await scorer.score(case, "Hello World!", [])
        assert score == 5.0
        assert name == "keyword"

    @pytest.mark.asyncio
    async def test_no_keywords_match(self, scorer):
        case = EvalCase(input="test", expected="test", expected_keywords=["foo", "bar"])
        score, _ = await scorer.score(case, "completely different", [])
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_partial_match(self, scorer):
        case = EvalCase(input="test", expected="test", expected_keywords=["hello", "world"])
        score, _ = await scorer.score(case, "hello there", [])
        assert score == 3.0  # 50% match

    @pytest.mark.asyncio
    async def test_no_keywords_returns_zero(self, scorer):
        """Score of 0 means 'not applicable'."""
        case = EvalCase(input="test", expected="test")
        score, _ = await scorer.score(case, "anything", [])
        assert score == 0.0


# ── ToolUseScorer ─────────────────────────────────────────────────────


class TestToolUseScorer:
    @pytest.fixture
    def scorer(self):
        return ToolUseScorer()

    @pytest.mark.asyncio
    async def test_all_tools_called(self, scorer):
        case = EvalCase(input="test", expected="test", expected_tools=["save_memory"])
        score, name = await scorer.score(case, "done", ["save_memory"])
        assert score == 5.0
        assert name == "tool_use"

    @pytest.mark.asyncio
    async def test_no_tools_called(self, scorer):
        case = EvalCase(input="test", expected="test", expected_tools=["save_memory"])
        score, _ = await scorer.score(case, "done", [])
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_no_expected_tools_returns_zero(self, scorer):
        case = EvalCase(input="test", expected="test")
        score, _ = await scorer.score(case, "done", ["save_memory"])
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_partial_tools(self, scorer):
        case = EvalCase(
            input="test", expected="test",
            expected_tools=["save_memory", "get_memories"],
        )
        score, _ = await scorer.score(case, "done", ["save_memory"])
        assert score == 3.0  # 50% match


# ── LLMJudgeScorer ───────────────────────────────────────────────────


class TestLLMJudgeScorer:
    @pytest.mark.asyncio
    async def test_parses_score_from_llm(self):
        scorer = LLMJudgeScorer()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="4")]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        scorer._client = mock_client

        case = EvalCase(input="hi", expected="greet")
        score, name = await scorer.score(case, "Hello!", [])
        assert score == 4.0
        assert name == "llm_judge"

    @pytest.mark.asyncio
    async def test_handles_unexpected_llm_output(self):
        scorer = LLMJudgeScorer()

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="I think this is pretty good")]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        scorer._client = mock_client

        case = EvalCase(input="hi", expected="greet")
        score, _ = await scorer.score(case, "Hello!", [])
        assert score == 3.0  # Falls back to 3.0


# ── CompositeScorer ───────────────────────────────────────────────────


class TestCompositeScorer:
    @pytest.mark.asyncio
    async def test_averages_applicable_scorers(self):
        """Composite should average only scorers that return > 0."""
        mock_llm = AsyncMock(spec=LLMJudgeScorer)
        mock_llm.score = AsyncMock(return_value=(4.0, "llm_judge"))

        mock_keyword = AsyncMock(spec=KeywordScorer)
        mock_keyword.score = AsyncMock(return_value=(0.0, "keyword"))  # Not applicable

        scorer = CompositeScorer(scorers=[mock_llm, mock_keyword])
        case = EvalCase(input="hi", expected="greet")
        score, name = await scorer.score(case, "Hello!", [])
        assert score == 4.0  # Only LLM judge applies
        assert name == "composite"

    @pytest.mark.asyncio
    async def test_score_detailed_returns_breakdown(self):
        mock_llm = AsyncMock(spec=LLMJudgeScorer)
        mock_llm.score = AsyncMock(return_value=(4.0, "llm_judge"))

        mock_tool = AsyncMock(spec=ToolUseScorer)
        mock_tool.score = AsyncMock(return_value=(5.0, "tool_use"))

        scorer = CompositeScorer(scorers=[mock_llm, mock_tool])
        case = EvalCase(input="hi", expected="greet")
        score, details = await scorer.score_detailed(case, "Hello!", ["save_memory"])
        assert score == 4.5
        assert details == {"llm_judge": 4.0, "tool_use": 5.0}
