"""Tests for the code_reviewer main module."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agents.code_reviewer.main import (
    ALLOWED_ENV_NAMES,
    ALLOWED_ENV_PREFIXES,
    PER_AGENT_MAX_TURNS,
    PER_AGENT_TIMEOUT,
    REVIEW_AGENTS,
    AgentResult,
    _run_single_agent,
    markdown_to_html,
    run_review,
    send_report,
)


class TestAgentResult:
    """Tests for the AgentResult dataclass."""

    def test_defaults(self):
        """Error defaults to None."""
        r = AgentResult(name="test", success=True, output="ok")
        assert r.name == "test"
        assert r.success is True
        assert r.output == "ok"
        assert r.error is None

    def test_with_error(self):
        """Error field can be set explicitly."""
        r = AgentResult(name="test", success=False, output="", error="boom")
        assert r.error == "boom"
        assert r.success is False


class TestRunSingleAgent:
    """Tests for _run_single_agent executing a Claude Code session."""

    @pytest.mark.asyncio
    async def test_success(self):
        """Successful agent run returns AgentResult with output."""
        agent = {"name": "test-agent", "description": "do something"}
        mock_claude = AsyncMock(return_value={"success": True, "output": "Found 3 issues"})

        with patch("agent_framework.tools.claude_code.run_claude_code", mock_claude):
            result = await _run_single_agent(agent, "/path/to/project", "sonnet", {})

        assert result.success is True
        assert result.name == "test-agent"
        assert result.output == "Found 3 issues"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_failure_error_output(self):
        """Failed agent returns error from error_output field."""
        agent = {"name": "test-agent", "description": "do something"}
        mock_claude = AsyncMock(return_value={"success": False, "error_output": "timeout exceeded"})

        with patch("agent_framework.tools.claude_code.run_claude_code", mock_claude):
            result = await _run_single_agent(agent, "/path/to/project", "sonnet", {})

        assert result.success is False
        assert result.error is not None
        assert "timeout exceeded" in result.error

    @pytest.mark.asyncio
    async def test_failure_fallback_to_output(self):
        """When error_output is absent, falls back to output field."""
        agent = {"name": "test-agent", "description": "do something"}
        mock_claude = AsyncMock(return_value={"success": False, "output": "something went wrong"})

        with patch("agent_framework.tools.claude_code.run_claude_code", mock_claude):
            result = await _run_single_agent(agent, "/path/to/project", "sonnet", {})

        assert result.success is False
        assert result.error is not None
        assert "something went wrong" in result.error

    @pytest.mark.asyncio
    async def test_exception_caught(self):
        """Exceptions are caught and returned as error."""
        agent = {"name": "crash-agent", "description": "do something"}
        mock_claude = AsyncMock(side_effect=RuntimeError("process died"))

        with patch("agent_framework.tools.claude_code.run_claude_code", mock_claude):
            result = await _run_single_agent(agent, "/path/to/project", "sonnet", {})

        assert result.success is False
        assert result.error is not None
        assert "process died" in result.error

    @pytest.mark.asyncio
    async def test_passes_correct_args(self):
        """Verify folder_name, model, timeout, max_turns are passed correctly."""
        agent = {"name": "test-agent", "description": "test desc"}
        mock_claude = AsyncMock(return_value={"success": True, "output": "ok"})

        with patch("agent_framework.tools.claude_code.run_claude_code", mock_claude):
            await _run_single_agent(agent, "/workspace/myproject", "haiku", {"PATH": "/usr/bin"})

        mock_claude.assert_awaited_once()
        kwargs = mock_claude.call_args[1]
        assert kwargs["folder_name"] == "myproject"
        assert kwargs["working_dir_base"] == "/workspace"
        assert kwargs["model"] == "haiku"
        assert kwargs["timeout"] == PER_AGENT_TIMEOUT
        assert kwargs["max_turns"] == PER_AGENT_MAX_TURNS
        assert kwargs["env"] == {"PATH": "/usr/bin"}

    @pytest.mark.asyncio
    async def test_error_truncated_to_500(self):
        """Long error messages are truncated to 500 chars."""
        agent = {"name": "test-agent", "description": "do something"}
        long_error = "x" * 1000
        mock_claude = AsyncMock(return_value={"success": False, "error_output": long_error})

        with patch("agent_framework.tools.claude_code.run_claude_code", mock_claude):
            result = await _run_single_agent(agent, "/path/to/project", "sonnet", {})

        assert result.error is not None and len(result.error) == 500

    @pytest.mark.asyncio
    async def test_command_includes_agent_info(self):
        """Command sent to claude code includes agent name and description."""
        agent = {"name": "security-checker", "description": "find vulnerabilities"}
        mock_claude = AsyncMock(return_value={"success": True, "output": "ok"})

        with patch("agent_framework.tools.claude_code.run_claude_code", mock_claude):
            await _run_single_agent(agent, "/path/to/project", "sonnet", {})

        command = mock_claude.call_args[1]["command"]
        assert "security-checker" in command
        assert "find vulnerabilities" in command


class TestRunReview:
    """Tests for run_review orchestrating parallel agents."""

    @pytest.mark.asyncio
    async def test_all_succeed(self):
        """All agents succeed — report contains all sections."""

        async def mock_run_single(agent, *_args, **_kwargs):
            return AgentResult(
                name=agent["name"],
                success=True,
                output=f"Results from {agent['name']}",
            )

        with patch("agents.code_reviewer.main._run_single_agent", side_effect=mock_run_single):
            report = await run_review("/some/path", model="sonnet")

        assert report is not None
        assert "Code Review Report" in report
        assert "/some/path" in report
        assert f"{len(REVIEW_AGENTS)}/{len(REVIEW_AGENTS)} succeeded" in report
        for agent in REVIEW_AGENTS:
            assert agent["name"] in report

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        """Some agents fail — report still generated from successful ones."""
        call_count = 0

        async def mock_run_single(agent, *_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return AgentResult(name=agent["name"], success=True, output="Findings here")
            return AgentResult(name=agent["name"], success=False, output="", error="timed out")

        with patch("agents.code_reviewer.main._run_single_agent", side_effect=mock_run_single):
            report = await run_review("/some/path")

        assert report is not None
        assert "2/5 succeeded" in report
        assert "3 failed" in report
        assert "Agent failed" in report

    @pytest.mark.asyncio
    async def test_all_fail_returns_none(self):
        """All agents fail — returns None."""

        async def mock_run_single(agent, *_a, **_kw):
            return AgentResult(name=agent["name"], success=False, output="", error="crash")

        with patch("agents.code_reviewer.main._run_single_agent", side_effect=mock_run_single):
            report = await run_review("/some/path")

        assert report is None

    @pytest.mark.asyncio
    async def test_empty_output_treated_as_failure(self):
        """Agent with success=True but empty output is treated as failure."""

        async def mock_run_single(agent, *_a, **_kw):
            return AgentResult(name=agent["name"], success=True, output="   ")

        with patch("agents.code_reviewer.main._run_single_agent", side_effect=mock_run_single):
            report = await run_review("/some/path")

        # All have blank output, so all treated as failed
        assert report is None

    @pytest.mark.asyncio
    async def test_env_filtering(self):
        """Only allowed env vars are passed to agents."""
        captured_envs: list[dict[str, str]] = []

        async def mock_run_single(agent, _folder_path, _model, custom_env):
            captured_envs.append(custom_env)
            return AgentResult(name=agent["name"], success=True, output="ok")

        test_env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "ANTHROPIC_API_KEY": "sk-secret",
            "DATABASE_URL": "postgres://...",
            "LANG": "en_US.UTF-8",
            "LC_ALL": "C",
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "GITHUB_TOKEN": "ghp_token",
            "RANDOM_SECRET": "should-be-filtered",
        }

        with (
            patch("agents.code_reviewer.main._run_single_agent", side_effect=mock_run_single),
            patch.dict(os.environ, test_env, clear=True),
        ):
            await run_review("/some/path")

        assert len(captured_envs) == len(REVIEW_AGENTS)
        env = captured_envs[0]
        assert "PATH" in env
        assert "HOME" in env
        assert "GITHUB_TOKEN" in env
        assert "LANG" in env
        assert "LC_ALL" in env
        assert "XDG_RUNTIME_DIR" in env
        assert "ANTHROPIC_API_KEY" not in env
        assert "DATABASE_URL" not in env
        assert "RANDOM_SECRET" not in env

    @pytest.mark.asyncio
    async def test_report_contains_date(self):
        """Report header includes current date."""

        async def mock_run_single(agent, *_a, **_kw):
            return AgentResult(name=agent["name"], success=True, output="findings")

        with patch("agents.code_reviewer.main._run_single_agent", side_effect=mock_run_single):
            report = await run_review("/some/path")

        assert report is not None
        # Should contain a date like 2026-02-27
        assert "**Date:**" in report


class TestMarkdownToHtml:
    """Tests for markdown_to_html conversion."""

    def test_basic_conversion(self):
        """Markdown is converted to HTML with wrapper."""
        html = markdown_to_html("# Hello\n\nWorld")
        assert "<h1>Hello</h1>" in html
        assert "<p>World</p>" in html

    def test_has_html_structure(self):
        """Output has full HTML document structure."""
        html = markdown_to_html("test")
        assert "<!DOCTYPE html>" in html
        assert "<html>" in html
        assert "<head>" in html
        assert "<body>" in html
        assert "</html>" in html

    def test_has_css_styles(self):
        """Output includes CSS styling."""
        html = markdown_to_html("test")
        assert "<style>" in html
        assert "font-family" in html

    def test_code_block(self):
        """Fenced code blocks are rendered."""
        md = "```python\ndef foo():\n    pass\n```"
        html = markdown_to_html(md)
        assert "<pre>" in html
        assert "<code" in html

    def test_table(self):
        """Tables are rendered as HTML."""
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = markdown_to_html(md)
        assert "<table>" in html
        assert "<th>" in html


class TestSendReport:
    """Tests for send_report emailing the review."""

    @pytest.mark.asyncio
    async def test_success(self, tmp_path: Path):
        """Successful email returns True."""
        mock_send = AsyncMock(return_value={"status": "success", "to_address": "test@example.com"})

        with patch("agent_framework.tools.fastmail.send_agent_report", mock_send):
            result = await send_report("# Report\n\nFindings", tmp_path / "project")

        assert result is True
        mock_send.assert_awaited_once()
        kwargs = mock_send.call_args[1]
        assert kwargs["is_html"] is True
        assert kwargs["agent_name"] == "code-reviewer"
        assert "project" in kwargs["subject"]

    @pytest.mark.asyncio
    async def test_failure(self, tmp_path: Path):
        """Failed email returns False."""
        mock_send = AsyncMock(return_value={"status": "error", "message": "auth failed"})

        with patch("agent_framework.tools.fastmail.send_agent_report", mock_send):
            result = await send_report("# Report", tmp_path / "project")

        assert result is False

    @pytest.mark.asyncio
    async def test_exception(self, tmp_path: Path):
        """Exception during send returns False (doesn't raise)."""
        mock_send = AsyncMock(side_effect=ConnectionError("network down"))

        with patch("agent_framework.tools.fastmail.send_agent_report", mock_send):
            result = await send_report("# Report", tmp_path / "project")

        assert result is False

    @pytest.mark.asyncio
    async def test_html_body_sent(self, tmp_path: Path):
        """Report is converted to HTML before sending."""
        mock_send = AsyncMock(return_value={"status": "success"})

        with patch("agent_framework.tools.fastmail.send_agent_report", mock_send):
            await send_report("# Hello", tmp_path / "project")

        body = mock_send.call_args[1]["body"]
        assert "<!DOCTYPE html>" in body
        assert "<h1>Hello</h1>" in body


class TestConstants:
    """Tests for module-level constants."""

    def test_review_agents_count(self):
        """There are exactly 5 review agents."""
        assert len(REVIEW_AGENTS) == 5

    def test_review_agents_have_required_keys(self):
        """Each agent has name and description."""
        for agent in REVIEW_AGENTS:
            assert "name" in agent
            assert "description" in agent

    def test_timeout_values(self):
        """Timeout and max_turns are reasonable."""
        assert PER_AGENT_TIMEOUT == 600
        assert PER_AGENT_MAX_TURNS == 30

    def test_allowed_env_contains_essentials(self):
        """Allowlist includes PATH, HOME, and GitHub tokens."""
        assert "PATH" in ALLOWED_ENV_NAMES
        assert "HOME" in ALLOWED_ENV_NAMES
        assert "GITHUB_TOKEN" in ALLOWED_ENV_NAMES
        assert "GH_TOKEN" in ALLOWED_ENV_NAMES

    def test_allowed_env_excludes_secrets(self):
        """Allowlist does not include common secret patterns."""
        for name in ALLOWED_ENV_NAMES:
            assert "API_KEY" not in name
            assert "SECRET" not in name
            assert "PASSWORD" not in name

    def test_allowed_prefixes(self):
        """Allowed prefixes cover locale and XDG vars."""
        assert "LANG" in ALLOWED_ENV_PREFIXES
        assert "LC_" in ALLOWED_ENV_PREFIXES
        assert "XDG_" in ALLOWED_ENV_PREFIXES
