"""Unit tests for the evaluation framework.

These tests validate the framework's data models, scorers, and dataset loading
without calling the Anthropic API.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.evaluations.models import EvalCase, EvalResult, EvalRun, load_dataset
from tests.evaluations.runner import DATASETS_DIR, _load_prompts_module
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
        case = EvalCase.from_dict(
            {
                "input": "remember blue",
                "expected": "save memory",
                "tags": ["memory"],
                "expected_tools": ["save_memory"],
                "expected_keywords": ["blue", "saved"],
                "max_tokens": 100,
            }
        )
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
            '{"input": "hi", "expected": "greet"}\n{"input": "bye", "expected": "farewell"}\n'
        )
        cases = load_dataset(dataset)
        assert len(cases) == 2
        assert cases[0].input == "hi"
        assert cases[1].input == "bye"

    def test_load_skips_blank_lines(self, tmp_path: Path):
        dataset = tmp_path / "test.jsonl"
        dataset.write_text(
            '{"input": "hi", "expected": "greet"}\n\n{"input": "bye", "expected": "farewell"}\n'
        )
        cases = load_dataset(dataset)
        assert len(cases) == 2

    def test_load_skips_comments(self, tmp_path: Path):
        dataset = tmp_path / "test.jsonl"
        dataset.write_text('# This is a comment\n{"input": "hi", "expected": "greet"}\n')
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
            case=case,
            response="ok",
            score=score,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
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
            input="test",
            expected="test",
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


# ── Dataset validation ───────────────────────────────────────────────


class TestAllDatasets:
    """Verify all JSONL dataset files are valid and well-formed."""

    @pytest.mark.parametrize(
        "agent_name",
        [
            "chatbot",
            "business",
            "security",
            "code-analysis",
            "log-analysis",
            "events",
            "pr",
            "red-team",
            "tasks",
            "security-audit",
            "sysadmin",
            "web-analysis",
            "website-tester",
        ],
    )
    def test_dataset_loads_and_has_cases(self, agent_name: str):
        path = DATASETS_DIR / f"{agent_name}.jsonl"
        assert path.exists(), f"Dataset missing for {agent_name}"
        cases = load_dataset(path)
        assert len(cases) >= 5, f"Dataset for {agent_name} should have at least 5 cases"

    @pytest.mark.parametrize(
        "agent_name",
        [
            "chatbot",
            "business",
            "security",
            "code-analysis",
            "log-analysis",
            "events",
            "pr",
            "red-team",
            "tasks",
            "security-audit",
            "sysadmin",
            "web-analysis",
            "website-tester",
        ],
    )
    def test_dataset_cases_have_required_fields(self, agent_name: str):
        path = DATASETS_DIR / f"{agent_name}.jsonl"
        cases = load_dataset(path)
        for case in cases:
            assert case.input, f"Case in {agent_name} must have non-empty input"
            assert case.expected, f"Case in {agent_name} must have non-empty expected"
            assert isinstance(case.tags, list), f"Tags must be a list in {agent_name}"

    @pytest.mark.parametrize(
        "agent_name",
        [
            "chatbot",
            "business",
            "security",
            "code-analysis",
            "log-analysis",
            "events",
            "pr",
            "red-team",
            "tasks",
            "security-audit",
            "sysadmin",
            "web-analysis",
            "website-tester",
        ],
    )
    def test_dataset_cases_have_tags(self, agent_name: str):
        """Every case should have at least one tag for filtering."""
        path = DATASETS_DIR / f"{agent_name}.jsonl"
        cases = load_dataset(path)
        for case in cases:
            label = case.input[:40] + ("..." if len(case.input) > 40 else "")
            assert len(case.tags) >= 1, (
                f"Case '{label}' in {agent_name} should have at least one tag"
            )


# ── Dataset coverage ─────────────────────────────────────────────────


class TestDatasetCoverage:
    """Ensure every registered agent has a corresponding eval dataset."""

    # Agents that are background services (no interactive prompt) and don't need eval datasets.
    EXCLUDED_AGENTS: set[str] = set()

    def test_every_agent_has_dataset(self):
        """Fail if a registered agent has no JSONL dataset file."""
        from shared.registry import build_agent_registry

        registry = build_agent_registry()
        missing = []
        for agent_name in sorted(registry):
            if agent_name in self.EXCLUDED_AGENTS:
                continue
            path = DATASETS_DIR / f"{agent_name}.jsonl"
            if not path.exists():
                missing.append(agent_name)

        assert not missing, (
            f"Agents missing eval datasets: {', '.join(missing)}. "
            f"Create tests/evaluations/datasets/<name>.jsonl for each."
        )


# ── Prompt variants ──────────────────────────────────────────────────


class TestPromptVariants:
    def test_business_variants_exist(self):
        from agents.business_advisor.prompts import PROMPT_VARIANTS

        assert "concise" in PROMPT_VARIANTS
        assert "no-guardrails" in PROMPT_VARIANTS

    def test_business_variants_are_nonempty_strings(self):
        from agents.business_advisor.prompts import PROMPT_VARIANTS

        for name, prompt in PROMPT_VARIANTS.items():
            assert isinstance(prompt, str), f"Variant {name} must be a string"
            assert len(prompt) > 100, f"Variant {name} seems too short"

    def test_load_prompts_module_business(self):
        mod = _load_prompts_module("business")
        assert mod is not None
        assert hasattr(mod, "PROMPT_VARIANTS")

    def test_load_prompts_module_unknown_returns_none(self):
        mod = _load_prompts_module("nonexistent-agent-xyz")
        assert mod is None


# ── Langfuse integration ─────────────────────────────────────────────


class TestLangfuseIntegration:
    def test_get_last_trace_id_initially_none(self):
        from agent_framework.observability.langfuse_integration import get_last_trace_id

        # When no trace has been created, should return None (or whatever the current state is)
        # This just verifies the function is importable and callable
        result = get_last_trace_id()
        assert result is None or isinstance(result, str)

    def test_push_langfuse_score_noop_without_langfuse(self):
        """Score push should silently do nothing when Langfuse is not configured."""
        from tests.evaluations.runner import _push_langfuse_score

        case = EvalCase(input="test", expected="test", tags=["basic"])
        result = EvalResult(
            case=case,
            response="ok",
            score=4.0,
            score_details={"llm_judge": 4.0},
        )
        # Should not raise even when Langfuse is not available
        _push_langfuse_score(result, "default", "test.jsonl")

    @patch("tests.evaluations.runner._get_langfuse_client")
    @patch("tests.evaluations.runner.json.dumps", return_value="{}")
    def test_push_langfuse_score_calls_langfuse(self, mock_dumps, mock_get_client):
        """When Langfuse is available and trace_id exists, score should be pushed."""
        from tests.evaluations.runner import _push_langfuse_score

        mock_langfuse = MagicMock()
        mock_get_client.return_value = mock_langfuse

        case = EvalCase(input="test", expected="test", tags=["basic"])
        result = EvalResult(
            case=case,
            response="ok",
            score=4.0,
            score_details={"llm_judge": 4.0},
        )

        with patch(
            "agent_framework.observability.langfuse_integration._last_trace_id",
            "trace-123",
        ):
            _push_langfuse_score(result, "default", "test.jsonl")

        mock_langfuse.score.assert_called_once()
        call_kwargs = mock_langfuse.score.call_args[1]
        assert call_kwargs["trace_id"] == "trace-123"
        assert call_kwargs["name"] == "eval_score"
        assert call_kwargs["value"] == 4.0
        mock_dumps.assert_called_once()
