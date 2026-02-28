"""Tests for the code_reviewer github_issues module."""

import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agents.code_reviewer.github_issues import (
    _LABELS,
    _build_issue_creation_prompt,
    _ensure_labels,
    _parse_issue_summary,
    create_issues_from_review,
    detect_repo,
)


class TestDetectRepo:
    """Tests for auto-detecting GitHub repo from a local directory."""

    @pytest.mark.asyncio
    async def test_detect_repo_success(self):
        """Valid gh output returns owner/repo string."""
        with patch(
            "agents.code_reviewer.github_issues._run_gh",
            new_callable=AsyncMock,
            return_value=(0, "owner/repo-name\n", ""),
        ):
            result = await detect_repo("/some/path")
        assert result == "owner/repo-name"

    @pytest.mark.asyncio
    async def test_detect_repo_strips_whitespace(self):
        """Whitespace around output is stripped."""
        with patch(
            "agents.code_reviewer.github_issues._run_gh",
            new_callable=AsyncMock,
            return_value=(0, "  my-org/my-repo  \n", ""),
        ):
            result = await detect_repo("/some/path")
        assert result == "my-org/my-repo"

    @pytest.mark.asyncio
    async def test_detect_repo_nonzero_exit(self):
        """Non-zero exit code returns None."""
        with patch(
            "agents.code_reviewer.github_issues._run_gh",
            new_callable=AsyncMock,
            return_value=(1, "", "not a git repo"),
        ):
            result = await detect_repo("/some/path")
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_repo_empty_output(self):
        """Empty stdout returns None even with rc=0."""
        with patch(
            "agents.code_reviewer.github_issues._run_gh",
            new_callable=AsyncMock,
            return_value=(0, "", ""),
        ):
            result = await detect_repo("/some/path")
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_repo_invalid_format(self):
        """Output not matching owner/repo pattern returns None."""
        with patch(
            "agents.code_reviewer.github_issues._run_gh",
            new_callable=AsyncMock,
            return_value=(0, "not-a-valid-repo", ""),
        ):
            result = await detect_repo("/some/path")
        assert result is None

    @pytest.mark.asyncio
    async def test_detect_repo_passes_cwd(self):
        """target_path is passed as cwd to gh."""
        mock_gh = AsyncMock(return_value=(0, "owner/repo\n", ""))
        with patch("agents.code_reviewer.github_issues._run_gh", mock_gh):
            await detect_repo("/my/project")
        mock_gh.assert_called_once()
        _, kwargs = mock_gh.call_args
        assert kwargs["cwd"] == "/my/project"

    @pytest.mark.asyncio
    async def test_detect_repo_special_chars(self):
        """Repo names with dots, dashes, underscores are valid."""
        with patch(
            "agents.code_reviewer.github_issues._run_gh",
            new_callable=AsyncMock,
            return_value=(0, "my_org.name/repo-name.py\n", ""),
        ):
            result = await detect_repo("/some/path")
        assert result == "my_org.name/repo-name.py"


class TestEnsureLabels:
    """Tests for _ensure_labels creating repository labels."""

    @pytest.mark.asyncio
    async def test_creates_all_labels(self):
        """All labels from _LABELS are created via gh."""
        mock_gh = AsyncMock(return_value=(0, "", ""))
        with patch("agents.code_reviewer.github_issues._run_gh", mock_gh):
            await _ensure_labels("owner/repo")
        assert mock_gh.call_count == len(_LABELS)

    @pytest.mark.asyncio
    async def test_label_args_format(self):
        """Each gh call has correct args structure."""
        mock_gh = AsyncMock(return_value=(0, "", ""))
        with patch("agents.code_reviewer.github_issues._run_gh", mock_gh):
            await _ensure_labels("owner/repo")

        for call in mock_gh.call_args_list:
            args = call[0][0]
            assert args[0] == "label"
            assert args[1] == "create"
            # label name
            assert args[2] in _LABELS
            assert "--repo" in args
            assert "owner/repo" in args
            assert "--description" in args
            assert "--color" in args

    @pytest.mark.asyncio
    async def test_ignores_nonzero_exit(self):
        """Non-zero exit (label exists) doesn't raise."""
        mock_gh = AsyncMock(return_value=(1, "", "already exists"))
        with patch("agents.code_reviewer.github_issues._run_gh", mock_gh):
            # Should not raise
            await _ensure_labels("owner/repo")

    @pytest.mark.asyncio
    async def test_label_color_and_description(self):
        """Verify correct color and description are passed for each label."""
        calls: list[list[str]] = []
        mock_gh = AsyncMock(return_value=(0, "", ""))
        mock_gh.side_effect = lambda args, **_kw: (calls.append(args), (0, "", ""))[1]
        with patch("agents.code_reviewer.github_issues._run_gh", mock_gh):
            await _ensure_labels("owner/repo")

        for call_args in calls:
            label_name = call_args[2]
            expected_desc, expected_color = _LABELS[label_name]
            desc_idx = call_args.index("--description") + 1
            color_idx = call_args.index("--color") + 1
            assert call_args[desc_idx] == expected_desc
            assert call_args[color_idx] == expected_color


class TestParseIssueSummary:
    """Tests for _parse_issue_summary extracting stats from output."""

    def test_valid_summary(self):
        """Standard summary block is parsed correctly."""
        output = """Some preamble text...

ISSUE_SUMMARY_START
Created: 5
Skipped (duplicate): 2
Failed: 1
ISSUE_SUMMARY_END

Some trailing text..."""
        result = _parse_issue_summary(output)
        assert result["created"] == 5
        assert result["skipped"] == 2
        assert result["failed"] == 1

    def test_zero_counts(self):
        """All-zero counts are parsed correctly."""
        output = """ISSUE_SUMMARY_START
Created: 0
Skipped (duplicate): 0
Failed: 0
ISSUE_SUMMARY_END"""
        result = _parse_issue_summary(output)
        assert result["created"] == 0
        assert result["skipped"] == 0
        assert result["failed"] == 0

    def test_missing_summary_block(self):
        """Missing summary block returns all zeros."""
        result = _parse_issue_summary("No summary here at all")
        assert result["created"] == 0
        assert result["skipped"] == 0
        assert result["failed"] == 0

    def test_empty_string(self):
        """Empty string returns all zeros."""
        result = _parse_issue_summary("")
        assert result["created"] == 0
        assert result["skipped"] == 0
        assert result["failed"] == 0

    def test_large_numbers(self):
        """Large counts are parsed as integers."""
        output = """ISSUE_SUMMARY_START
Created: 123
Skipped (duplicate): 456
Failed: 789
ISSUE_SUMMARY_END"""
        result = _parse_issue_summary(output)
        assert result["created"] == 123
        assert result["skipped"] == 456
        assert result["failed"] == 789

    def test_extra_whitespace(self):
        """Extra whitespace around numbers is tolerated."""
        output = """ISSUE_SUMMARY_START
Created:   10
Skipped (duplicate):   3
Failed:   0
ISSUE_SUMMARY_END"""
        result = _parse_issue_summary(output)
        assert result["created"] == 10
        assert result["skipped"] == 3
        assert result["failed"] == 0

    def test_partial_block_not_matched(self):
        """Incomplete summary block returns zeros."""
        output = """ISSUE_SUMMARY_START
Created: 5
Failed: 1
ISSUE_SUMMARY_END"""
        result = _parse_issue_summary(output)
        assert result["created"] == 0  # Regex requires all three lines


class TestBuildIssueCreationPrompt:
    """Tests for _build_issue_creation_prompt constructing the Claude prompt."""

    def test_contains_repo(self):
        """Prompt references the target repo."""
        prompt = _build_issue_creation_prompt("owner/repo")
        assert "owner/repo" in prompt

    def test_contains_review_file(self):
        """Prompt instructs reading the temp review file."""
        prompt = _build_issue_creation_prompt("owner/repo")
        assert ".code-review-output.md" in prompt

    def test_contains_summary_markers(self):
        """Prompt includes the summary block markers for parsing."""
        prompt = _build_issue_creation_prompt("owner/repo")
        assert "ISSUE_SUMMARY_START" in prompt
        assert "ISSUE_SUMMARY_END" in prompt

    def test_contains_all_category_labels(self):
        """Prompt mentions all category labels for classification."""
        prompt = _build_issue_creation_prompt("owner/repo")
        for label in ["security", "dependencies", "testing", "documentation", "code-quality"]:
            assert label in prompt

    def test_contains_duplicate_check(self):
        """Prompt includes duplicate checking instructions."""
        prompt = _build_issue_creation_prompt("owner/repo")
        assert "gh issue list" in prompt
        assert "duplicate" in prompt.lower()


class TestCreateIssuesFromReview:
    """Tests for the full create_issues_from_review pipeline."""

    @pytest.mark.asyncio
    async def test_success_flow(self, tmp_path: Path):
        """Happy path: labels ensured, review file written, claude invoked, file cleaned up."""
        target = tmp_path / "project"
        target.mkdir()
        review_output = "## Findings\n\n- Bug in foo.py"

        mock_ensure = AsyncMock()
        mock_claude = AsyncMock(
            return_value={
                "success": True,
                "output": (
                    "ISSUE_SUMMARY_START\n"
                    "Created: 3\n"
                    "Skipped (duplicate): 1\n"
                    "Failed: 0\n"
                    "ISSUE_SUMMARY_END"
                ),
            }
        )

        with (
            patch("agents.code_reviewer.github_issues._ensure_labels", mock_ensure),
            patch("agent_framework.tools.claude_code.run_claude_code", mock_claude),
        ):
            result = await create_issues_from_review(
                review_output=review_output,
                target_path=str(target),
                repo="owner/repo",
            )

        assert result["created"] == 3
        assert result["skipped"] == 1
        assert result["failed"] == 0
        assert result["success"] is True

        # Ensure labels were called
        mock_ensure.assert_awaited_once_with("owner/repo")

        # Temp file should be cleaned up
        assert not (target / ".code-review-output.md").exists()

    @pytest.mark.asyncio
    async def test_writes_review_file(self, tmp_path: Path):
        """Review output is written to temp file before claude code runs."""
        target = tmp_path / "project"
        target.mkdir()
        review_output = "Test review content"

        written_content: list[str] = []

        async def capture_claude(**kwargs: Any) -> dict[str, Any]:
            # Read the file that should exist at this point
            review_file = target / ".code-review-output.md"
            if review_file.exists():
                written_content.append(review_file.read_text())
            return {"success": True, "output": ""}

        with (
            patch("agents.code_reviewer.github_issues._ensure_labels", new_callable=AsyncMock),
            patch("agent_framework.tools.claude_code.run_claude_code", side_effect=capture_claude),
        ):
            await create_issues_from_review(
                review_output=review_output,
                target_path=str(target),
                repo="owner/repo",
            )

        assert len(written_content) == 1
        assert written_content[0] == review_output

    @pytest.mark.asyncio
    async def test_cleanup_on_failure(self, tmp_path: Path):
        """Temp file is cleaned up even when claude code raises."""
        target = tmp_path / "project"
        target.mkdir()

        with (
            patch("agents.code_reviewer.github_issues._ensure_labels", new_callable=AsyncMock),
            patch(
                "agent_framework.tools.claude_code.run_claude_code",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await create_issues_from_review(
                    review_output="test",
                    target_path=str(target),
                    repo="owner/repo",
                )

        assert not (target / ".code-review-output.md").exists()

    @pytest.mark.asyncio
    async def test_strips_api_key(self, tmp_path: Path):
        """ANTHROPIC_API_KEY is stripped from env passed to claude code."""
        target = tmp_path / "project"
        target.mkdir()

        captured_env: list[dict[str, str]] = []

        async def capture_claude(**kwargs: Any) -> dict[str, Any]:
            captured_env.append(kwargs.get("env", {}))
            return {"success": True, "output": ""}

        with (
            patch("agents.code_reviewer.github_issues._ensure_labels", new_callable=AsyncMock),
            patch("agent_framework.tools.claude_code.run_claude_code", side_effect=capture_claude),
            patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-secret-key"}, clear=False),
        ):
            await create_issues_from_review(
                review_output="test",
                target_path=str(target),
                repo="owner/repo",
            )

        assert len(captured_env) == 1
        assert "ANTHROPIC_API_KEY" not in captured_env[0]

    @pytest.mark.asyncio
    async def test_claude_failure_propagates_success_false(self, tmp_path: Path):
        """When claude code reports failure, success=False in result."""
        target = tmp_path / "project"
        target.mkdir()

        with (
            patch("agents.code_reviewer.github_issues._ensure_labels", new_callable=AsyncMock),
            patch(
                "agent_framework.tools.claude_code.run_claude_code",
                new_callable=AsyncMock,
                return_value={"success": False, "output": ""},
            ),
        ):
            result = await create_issues_from_review(
                review_output="test",
                target_path=str(target),
                repo="owner/repo",
            )

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_model_passed_through(self, tmp_path: Path):
        """Model parameter is forwarded to claude code."""
        target = tmp_path / "project"
        target.mkdir()

        mock_claude = AsyncMock(return_value={"success": True, "output": ""})

        with (
            patch("agents.code_reviewer.github_issues._ensure_labels", new_callable=AsyncMock),
            patch("agent_framework.tools.claude_code.run_claude_code", mock_claude),
        ):
            await create_issues_from_review(
                review_output="test",
                target_path=str(target),
                repo="owner/repo",
                model="haiku",
            )

        mock_claude.assert_awaited_once()
        call_kwargs = mock_claude.call_args[1]
        assert call_kwargs["model"] == "haiku"
