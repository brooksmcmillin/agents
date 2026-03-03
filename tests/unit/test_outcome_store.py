"""Tests for shared/outcome_store.py.

Covers save/retrieve/dedup outcomes, importance escalation,
feedback formatting, and pattern extraction.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from shared.outcome_store import (
    AGENT_NAME,
    TaskOutcome,
    _outcome_key,
    _pattern_key,
    _tags_for_pattern,
    _validate_outcome_data,
    get_failure_patterns,
    get_outcomes,
    get_relevant_feedback,
    save_fix_pattern,
    save_outcome,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _outcome(**overrides) -> TaskOutcome:
    """Create a TaskOutcome with sensible defaults."""
    defaults = {
        "task_id": "abc123",
        "task_title": "Fix the widget",
        "repo": "owner/repo",
        "pr_number": 42,
        "pr_url": "https://github.com/owner/repo/pull/42",
        "pr_status": "merged",
    }
    defaults.update(overrides)
    return TaskOutcome(**defaults)


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


class TestKeyGeneration:
    def test_outcome_key_with_pr(self) -> None:
        o = _outcome(repo="owner/repo", pr_number=42)
        assert _outcome_key(o) == "outcome/owner/repo#42"

    def test_outcome_key_without_pr(self) -> None:
        o = _outcome(pr_number=None, task_id="task123")
        assert _outcome_key(o) == "outcome/task123"

    def test_pattern_key_deterministic(self) -> None:
        k1 = _pattern_key("owner/repo", "ruff:E501")
        k2 = _pattern_key("owner/repo", "ruff:E501")
        assert k1 == k2
        assert k1.startswith("pattern/owner/repo/")

    def test_pattern_key_different_patterns(self) -> None:
        k1 = _pattern_key("owner/repo", "ruff:E501")
        k2 = _pattern_key("owner/repo", "ruff:F841")
        assert k1 != k2


# ---------------------------------------------------------------------------
# Tag derivation
# ---------------------------------------------------------------------------


class TestTagDerivation:
    def test_lint_tags(self) -> None:
        tags = _tags_for_pattern("ruff:E501")
        assert "ci" in tags
        assert "lint" in tags

    def test_test_tags(self) -> None:
        tags = _tags_for_pattern("pytest:test_auth.py::test_login")
        assert "ci" in tags
        assert "test" in tags

    def test_mypy_tags(self) -> None:
        tags = _tags_for_pattern("mypy:incompatible-type")
        assert "ci" in tags
        assert "type-check" in tags

    def test_import_tags(self) -> None:
        tags = _tags_for_pattern("import:ModuleNotFoundError")
        assert "ci" in tags
        assert "import" in tags

    def test_generic_tags(self) -> None:
        tags = _tags_for_pattern("some-unknown-pattern")
        assert tags == ["ci"]


# ---------------------------------------------------------------------------
# Outcome data validation
# ---------------------------------------------------------------------------


class TestValidateOutcomeData:
    def test_invalid_pr_status_replaced(self) -> None:
        data = {"pr_status": "malicious_value"}
        result = _validate_outcome_data(data)
        assert result["pr_status"] == "open"

    def test_valid_pr_status_preserved(self) -> None:
        for status in ("merged", "closed", "ci_failing", "open"):
            data = {"pr_status": status}
            result = _validate_outcome_data(data)
            assert result["pr_status"] == status

    def test_invalid_pr_url_cleared(self) -> None:
        data = {"pr_url": "https://evil.com/attack"}
        result = _validate_outcome_data(data)
        assert result["pr_url"] is None

    def test_valid_pr_url_preserved(self) -> None:
        url = "https://github.com/owner/repo/pull/42"
        data = {"pr_url": url}
        result = _validate_outcome_data(data)
        assert result["pr_url"] == url

    def test_non_list_patterns_replaced(self) -> None:
        data = {"failure_patterns": "not a list"}
        result = _validate_outcome_data(data)
        assert result["failure_patterns"] == []

    def test_pattern_strings_truncated(self) -> None:
        long_pattern = "x" * 300
        data = {"failure_patterns": [long_pattern]}
        result = _validate_outcome_data(data)
        assert len(result["failure_patterns"][0]) == 200

    def test_non_string_patterns_filtered(self) -> None:
        data = {"failure_patterns": ["valid", 123, None, "also_valid"]}
        result = _validate_outcome_data(data)
        assert result["failure_patterns"] == ["valid", "also_valid"]


# ---------------------------------------------------------------------------
# save_outcome
# ---------------------------------------------------------------------------


class TestSaveOutcome:
    @pytest.mark.asyncio
    async def test_save_new_outcome(self) -> None:
        """New outcome is saved to memory."""
        with (
            patch("shared.outcome_store.search_memories", new_callable=AsyncMock) as mock_search,
            patch("shared.outcome_store.save_memory", new_callable=AsyncMock) as mock_save,
        ):
            mock_search.return_value = {"memories": []}
            mock_save.return_value = {"status": "success"}

            o = _outcome(pr_status="merged")
            await save_outcome(o)

            mock_save.assert_called()
            call_kwargs = mock_save.call_args
            assert call_kwargs.kwargs["category"] == "task_outcome"
            assert call_kwargs.kwargs["agent_name"] == AGENT_NAME
            assert "merged" in call_kwargs.kwargs["tags"]

    @pytest.mark.asyncio
    async def test_skip_unchanged_outcome(self) -> None:
        """Outcome with unchanged status is not re-saved."""
        with (
            patch("shared.outcome_store.search_memories", new_callable=AsyncMock) as mock_search,
            patch("shared.outcome_store.save_memory", new_callable=AsyncMock) as mock_save,
        ):
            mock_search.return_value = {
                "memories": [
                    {
                        "key": "outcome/owner/repo#42",
                        "value": '{"pr_status": "merged"}',
                    }
                ]
            }

            o = _outcome(pr_status="merged")
            await save_outcome(o)

            # save_memory should not be called because status is unchanged
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_changed_outcome(self) -> None:
        """Outcome with changed status is saved."""
        with (
            patch("shared.outcome_store.search_memories", new_callable=AsyncMock) as mock_search,
            patch("shared.outcome_store.save_memory", new_callable=AsyncMock) as mock_save,
        ):
            mock_search.return_value = {
                "memories": [
                    {
                        "key": "outcome/owner/repo#42",
                        "value": '{"pr_status": "ci_failing"}',
                    }
                ]
            }
            mock_save.return_value = {"status": "success"}

            o = _outcome(pr_status="merged")
            await save_outcome(o)

            mock_save.assert_called()

    @pytest.mark.asyncio
    async def test_importance_escalation(self) -> None:
        """Failure patterns get escalated importance on repeat."""
        with (
            patch("shared.outcome_store.search_memories", new_callable=AsyncMock) as mock_search,
            patch("shared.outcome_store.save_memory", new_callable=AsyncMock) as mock_save,
        ):
            # First call (for outcome dedup): no existing
            # Subsequent calls (for pattern save): existing pattern with importance 5
            mock_search.side_effect = [
                {"memories": []},  # outcome dedup check
                {
                    "memories": [
                        {
                            "key": _pattern_key("owner/repo", "ruff:E501"),
                            "value": '{"count": 1, "importance": 5}',
                        }
                    ]
                },  # pattern check
            ]
            mock_save.return_value = {"status": "success"}

            o = _outcome(failure_patterns=["ruff:E501"])
            await save_outcome(o)

            # Find the pattern save call
            pattern_calls = [
                c for c in mock_save.call_args_list if c.kwargs.get("category") == "failure_pattern"
            ]
            assert len(pattern_calls) == 1
            assert pattern_calls[0].kwargs["importance"] == 7  # escalated from 5


# ---------------------------------------------------------------------------
# get_outcomes
# ---------------------------------------------------------------------------


class TestGetOutcomes:
    @pytest.mark.asyncio
    async def test_get_outcomes_filters_repo(self) -> None:
        with patch("shared.outcome_store.get_memories", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "memories": [
                    {
                        "value": '{"task_id": "1", "task_title": "Fix", "repo": "owner/repo", "pr_status": "merged"}'
                    },
                    {
                        "value": '{"task_id": "2", "task_title": "Fix", "repo": "other/repo", "pr_status": "merged"}'
                    },
                ]
            }

            results = await get_outcomes(repo="owner/repo")
            assert len(results) == 1
            assert results[0].repo == "owner/repo"

    @pytest.mark.asyncio
    async def test_get_outcomes_no_filter(self) -> None:
        with patch("shared.outcome_store.get_memories", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "memories": [
                    {
                        "value": '{"task_id": "1", "task_title": "Fix", "repo": "owner/repo", "pr_status": "merged"}'
                    },
                ]
            }

            results = await get_outcomes()
            assert len(results) == 1


# ---------------------------------------------------------------------------
# get_failure_patterns
# ---------------------------------------------------------------------------


class TestGetFailurePatterns:
    @pytest.mark.asyncio
    async def test_returns_pattern_data(self) -> None:
        with patch("shared.outcome_store.get_memories", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "memories": [
                    {"value": '{"pattern": "ruff:E501", "repo": "owner/repo", "count": 3}'},
                    {"value": '{"pattern": "pytest:test_auth", "repo": "owner/repo", "count": 1}'},
                ]
            }

            patterns = await get_failure_patterns(repo="owner/repo")
            assert len(patterns) == 2
            assert patterns[0]["pattern"] == "ruff:E501"


# ---------------------------------------------------------------------------
# get_relevant_feedback
# ---------------------------------------------------------------------------


class TestGetRelevantFeedback:
    @pytest.mark.asyncio
    async def test_empty_when_no_data(self) -> None:
        with (
            patch("shared.outcome_store.get_memories", new_callable=AsyncMock) as mock_get,
            patch("shared.outcome_store.search_memories", new_callable=AsyncMock) as mock_search,
        ):
            mock_get.return_value = {"memories": []}
            mock_search.return_value = {"memories": []}

            result = await get_relevant_feedback()
            assert result == ""

    @pytest.mark.asyncio
    async def test_includes_patterns_and_fixes(self) -> None:
        with (
            patch("shared.outcome_store.get_memories", new_callable=AsyncMock) as mock_get,
            patch("shared.outcome_store.search_memories", new_callable=AsyncMock) as mock_search,
        ):
            mock_get.side_effect = [
                # failure patterns
                {"memories": [{"value": '{"pattern": "ruff:E501", "count": 3}'}]},
                # fix patterns
                {
                    "memories": [
                        {"value": '{"pattern": "ruff:E501", "fix": "Run ruff check --fix ."}'}
                    ]
                },
                # outcomes (from get_outcomes -> get_memories)
                {"memories": []},
            ]
            mock_search.return_value = {"memories": []}

            result = await get_relevant_feedback(repo="owner/repo")
            assert "Lessons from previous tasks" in result
            assert "ruff:E501" in result
            assert "Run ruff check --fix" in result
            assert "`owner/repo`" in result

    @pytest.mark.asyncio
    async def test_includes_outcome_stats(self) -> None:
        with (
            patch("shared.outcome_store.get_memories", new_callable=AsyncMock) as mock_get,
            patch("shared.outcome_store.search_memories", new_callable=AsyncMock) as mock_search,
        ):
            mock_get.side_effect = [
                # failure patterns
                {"memories": []},
                # fix patterns
                {"memories": []},
                # outcomes (called by get_outcomes)
                {
                    "memories": [
                        {
                            "value": '{"task_id": "1", "task_title": "A", "repo": "r", "pr_status": "merged"}'
                        },
                        {
                            "value": '{"task_id": "2", "task_title": "B", "repo": "r", "pr_status": "merged"}'
                        },
                        {
                            "value": '{"task_id": "3", "task_title": "C", "repo": "r", "pr_status": "ci_failing"}'
                        },
                    ]
                },
            ]
            mock_search.return_value = {"memories": []}

            result = await get_relevant_feedback()
            assert "merged" in result


# ---------------------------------------------------------------------------
# save_fix_pattern
# ---------------------------------------------------------------------------


class TestSaveFixPattern:
    @pytest.mark.asyncio
    async def test_saves_fix(self) -> None:
        with patch("shared.outcome_store.save_memory", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = {"status": "success"}

            await save_fix_pattern("owner/repo", "ruff:E501", "Run ruff check --fix .")

            mock_save.assert_called_once()
            assert mock_save.call_args.kwargs["category"] == "fix_pattern"
            assert mock_save.call_args.kwargs["importance"] == 7
