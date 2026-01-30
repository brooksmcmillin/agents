"""Tests for Claude Code automation tools."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_framework.tools.claude_code import (
    _get_workspace_path,
    _validate_folder_name,
    create_claude_code_workspace,
    delete_claude_code_workspace,
    get_claude_code_workspace_status,
    list_claude_code_workspaces,
    run_claude_code,
)


class TestValidateFolderName:
    """Tests for _validate_folder_name function."""

    def test_valid_alphanumeric(self):
        """Test valid alphanumeric folder names."""
        _validate_folder_name("myproject")
        _validate_folder_name("MyProject123")
        _validate_folder_name("project1")

    def test_valid_with_hyphens_underscores(self):
        """Test valid folder names with hyphens and underscores."""
        _validate_folder_name("my-project")
        _validate_folder_name("my_project")
        _validate_folder_name("my-project_v2")

    def test_valid_with_dots(self):
        """Test valid folder names with dots (not at start)."""
        _validate_folder_name("project.v1")
        _validate_folder_name("my-project.backup")

    def test_invalid_starts_with_dot(self):
        """Test that folder names starting with dot are rejected."""
        with pytest.raises(ValueError, match="Must start with alphanumeric"):
            _validate_folder_name(".hidden")

    def test_invalid_starts_with_hyphen(self):
        """Test that folder names starting with hyphen are rejected."""
        with pytest.raises(ValueError, match="Must start with alphanumeric"):
            _validate_folder_name("-project")

    def test_invalid_path_traversal_dotdot(self):
        """Test that path traversal with .. is rejected."""
        # foo..bar is caught by the regex (double dot pattern)
        with pytest.raises(ValueError):
            _validate_folder_name("foo..bar")
        # ../etc is caught by the regex first (starts with .)
        with pytest.raises(ValueError):
            _validate_folder_name("../etc")

    def test_invalid_path_traversal_slash(self):
        """Test that path traversal with slashes is rejected."""
        # These are caught by the regex (invalid characters)
        with pytest.raises(ValueError):
            _validate_folder_name("foo/bar")
        with pytest.raises(ValueError):
            _validate_folder_name("foo\\bar")

    def test_invalid_special_characters(self):
        """Test that special characters are rejected."""
        with pytest.raises(ValueError, match="Must start with alphanumeric"):
            _validate_folder_name("project@name")
        with pytest.raises(ValueError, match="Must start with alphanumeric"):
            _validate_folder_name("project name")  # space


class TestGetWorkspacePath:
    """Tests for _get_workspace_path function."""

    def test_valid_workspace(self, tmp_path):
        """Test getting a valid workspace path."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "myproject"
        project_dir.mkdir()

        result = _get_workspace_path("myproject", str(workspace_dir))

        assert result == project_dir

    def test_nonexistent_workspace(self, tmp_path):
        """Test that nonexistent workspace raises FileNotFoundError."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="Workspace not found"):
            _get_workspace_path("nonexistent", str(workspace_dir))

    def test_invalid_folder_name(self, tmp_path):
        """Test that invalid folder name raises ValueError."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        with pytest.raises(ValueError, match="Invalid folder name"):
            _get_workspace_path("../etc/passwd", str(workspace_dir))

    def test_path_is_file_not_directory(self, tmp_path):
        """Test that a file (not directory) raises ValueError."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        file_path = workspace_dir / "notadir"
        file_path.write_text("I'm a file")

        with pytest.raises(ValueError, match="not a directory"):
            _get_workspace_path("notadir", str(workspace_dir))


class TestListClaudeCodeWorkspaces:
    """Tests for list_claude_code_workspaces function."""

    @pytest.mark.asyncio
    async def test_list_empty_directory(self, tmp_path):
        """Test listing workspaces in empty directory."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        result = await list_claude_code_workspaces(str(workspace_dir))

        assert result["count"] == 0
        assert result["workspaces"] == []
        assert result["base_dir"] == str(workspace_dir)

    @pytest.mark.asyncio
    async def test_list_with_workspaces(self, tmp_path):
        """Test listing workspaces with multiple directories."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        # Create some workspaces
        (workspace_dir / "project1").mkdir()
        (workspace_dir / "project2").mkdir()
        (workspace_dir / "project2" / ".git").mkdir()  # Make it a git repo

        result = await list_claude_code_workspaces(str(workspace_dir))

        assert result["count"] == 2
        assert len(result["workspaces"]) == 2

        names = [ws["name"] for ws in result["workspaces"]]
        assert "project1" in names
        assert "project2" in names

        # Check git repo detection
        project2 = next(ws for ws in result["workspaces"] if ws["name"] == "project2")
        assert project2["is_git_repo"] is True

        project1 = next(ws for ws in result["workspaces"] if ws["name"] == "project1")
        assert project1["is_git_repo"] is False

    @pytest.mark.asyncio
    async def test_list_ignores_hidden_directories(self, tmp_path):
        """Test that hidden directories are ignored."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        (workspace_dir / "visible").mkdir()
        (workspace_dir / ".hidden").mkdir()

        result = await list_claude_code_workspaces(str(workspace_dir))

        assert result["count"] == 1
        assert result["workspaces"][0]["name"] == "visible"

    @pytest.mark.asyncio
    async def test_list_creates_directory_if_missing(self, tmp_path):
        """Test that base directory is created if it doesn't exist."""
        workspace_dir = tmp_path / "new_workspaces"

        result = await list_claude_code_workspaces(str(workspace_dir))

        assert workspace_dir.exists()
        assert result["count"] == 0


class TestCreateClaudeCodeWorkspace:
    """Tests for create_claude_code_workspace function."""

    @pytest.mark.asyncio
    async def test_create_empty_workspace(self, tmp_path):
        """Test creating an empty workspace with git init."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        with patch("agent_framework.tools.claude_code.asyncio.create_subprocess_exec") as mock_exec:
            # Mock git init success
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_process.returncode = 0
            mock_exec.return_value = mock_process

            result = await create_claude_code_workspace(
                folder_name="newproject",
                working_dir_base=str(workspace_dir),
            )

        assert result["success"] is True
        assert "newproject" in result["workspace_path"]
        assert (workspace_dir / "newproject").exists()

    @pytest.mark.asyncio
    async def test_create_workspace_with_git_clone(self, tmp_path):
        """Test creating a workspace by cloning a git repo."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        with patch("agent_framework.tools.claude_code.asyncio.create_subprocess_exec") as mock_exec:
            # Mock git clone success
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"", b""))
            mock_process.returncode = 0
            mock_exec.return_value = mock_process

            result = await create_claude_code_workspace(
                folder_name="cloned",
                git_repo_url="https://github.com/example/repo.git",
                working_dir_base=str(workspace_dir),
            )

        assert result["success"] is True
        assert result["is_git_repo"] is True
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert "git" in call_args
        assert "clone" in call_args

    @pytest.mark.asyncio
    async def test_create_workspace_already_exists(self, tmp_path):
        """Test that creating existing workspace fails."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        (workspace_dir / "existing").mkdir()

        result = await create_claude_code_workspace(
            folder_name="existing",
            working_dir_base=str(workspace_dir),
        )

        assert result["success"] is False
        assert "already exists" in result["message"]

    @pytest.mark.asyncio
    async def test_create_workspace_invalid_name(self, tmp_path):
        """Test that invalid folder name fails."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        result = await create_claude_code_workspace(
            folder_name="../escape",
            working_dir_base=str(workspace_dir),
        )

        assert result["success"] is False
        assert "error" in result


class TestDeleteClaudeCodeWorkspace:
    """Tests for delete_claude_code_workspace function."""

    @pytest.mark.asyncio
    async def test_delete_workspace(self, tmp_path):
        """Test deleting a workspace."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "todelete"
        project_dir.mkdir()

        result = await delete_claude_code_workspace(
            folder_name="todelete",
            working_dir_base=str(workspace_dir),
            force=True,
        )

        assert result["success"] is True
        assert not project_dir.exists()

    @pytest.mark.asyncio
    async def test_delete_workspace_with_uncommitted_changes(self, tmp_path):
        """Test that deleting workspace with uncommitted changes fails without force."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "dirty"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()

        with patch("agent_framework.tools.claude_code.asyncio.create_subprocess_exec") as mock_exec:
            # Mock git status showing uncommitted changes
            mock_process = AsyncMock()
            mock_process.communicate = AsyncMock(return_value=(b"M file.txt", b""))
            mock_process.returncode = 0
            mock_exec.return_value = mock_process

            result = await delete_claude_code_workspace(
                folder_name="dirty",
                working_dir_base=str(workspace_dir),
                force=False,
            )

        assert result["success"] is False
        assert result["had_uncommitted_changes"] is True
        assert project_dir.exists()  # Should not be deleted

    @pytest.mark.asyncio
    async def test_delete_workspace_force_with_uncommitted(self, tmp_path):
        """Test force deleting workspace with uncommitted changes."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "dirty"
        project_dir.mkdir()

        result = await delete_claude_code_workspace(
            folder_name="dirty",
            working_dir_base=str(workspace_dir),
            force=True,
        )

        assert result["success"] is True
        assert not project_dir.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_workspace(self, tmp_path):
        """Test deleting a workspace that doesn't exist."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        result = await delete_claude_code_workspace(
            folder_name="nonexistent",
            working_dir_base=str(workspace_dir),
        )

        assert result["success"] is False
        assert "error" in result


class TestGetClaudeCodeWorkspaceStatus:
    """Tests for get_claude_code_workspace_status function."""

    @pytest.mark.asyncio
    async def test_status_non_git_workspace(self, tmp_path):
        """Test getting status of non-git workspace."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "plain"
        project_dir.mkdir()
        (project_dir / "file.txt").write_text("content")

        result = await get_claude_code_workspace_status(
            folder_name="plain",
            working_dir_base=str(workspace_dir),
        )

        assert result["is_git_repo"] is False
        assert result["file_count"] == 1
        assert result["current_branch"] == ""

    @pytest.mark.asyncio
    async def test_status_git_workspace(self, tmp_path):
        """Test getting status of git workspace."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "gitrepo"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()

        with patch("agent_framework.tools.claude_code.asyncio.create_subprocess_exec") as mock_exec:
            # Mock git commands
            mock_process = AsyncMock()

            async def mock_communicate():
                # Return different values for different calls
                if mock_exec.call_count == 1:
                    return (b"main", b"")  # git branch --show-current
                else:
                    return (b"M file.txt", b"")  # git status --porcelain

            mock_process.communicate = mock_communicate
            mock_process.returncode = 0
            mock_exec.return_value = mock_process

            result = await get_claude_code_workspace_status(
                folder_name="gitrepo",
                working_dir_base=str(workspace_dir),
            )

        assert result["is_git_repo"] is True

    @pytest.mark.asyncio
    async def test_status_nonexistent_workspace(self, tmp_path):
        """Test getting status of nonexistent workspace."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        result = await get_claude_code_workspace_status(
            folder_name="nonexistent",
            working_dir_base=str(workspace_dir),
        )

        assert "error" in result


class TestRunClaudeCode:
    """Tests for run_claude_code function."""

    @pytest.mark.asyncio
    async def test_run_success(self, tmp_path):
        """Test successful Claude Code execution."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "project"
        project_dir.mkdir()

        with patch(
            "agent_framework.tools.claude_code.shutil.which", return_value="/usr/bin/claude"
        ):
            with patch(
                "agent_framework.tools.claude_code.asyncio.create_subprocess_exec"
            ) as mock_exec:
                mock_process = AsyncMock()
                mock_process.communicate = AsyncMock(
                    return_value=(b"Task completed successfully", b"")
                )
                mock_process.returncode = 0
                mock_exec.return_value = mock_process

                result = await run_claude_code(
                    folder_name="project",
                    command="List files",
                    working_dir_base=str(workspace_dir),
                )

        assert result["success"] is True
        assert result["exit_code"] == 0
        assert "Task completed successfully" in result["output"]

    @pytest.mark.asyncio
    async def test_run_failure(self, tmp_path):
        """Test failed Claude Code execution."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "project"
        project_dir.mkdir()

        with patch(
            "agent_framework.tools.claude_code.shutil.which", return_value="/usr/bin/claude"
        ):
            with patch(
                "agent_framework.tools.claude_code.asyncio.create_subprocess_exec"
            ) as mock_exec:
                mock_process = AsyncMock()
                mock_process.communicate = AsyncMock(return_value=(b"", b"Error occurred"))
                mock_process.returncode = 1
                mock_exec.return_value = mock_process

                result = await run_claude_code(
                    folder_name="project",
                    command="Do something",
                    working_dir_base=str(workspace_dir),
                )

        assert result["success"] is False
        assert result["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_run_timeout(self, tmp_path):
        """Test Claude Code execution timeout."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "project"
        project_dir.mkdir()

        with patch(
            "agent_framework.tools.claude_code.shutil.which", return_value="/usr/bin/claude"
        ):
            with patch(
                "agent_framework.tools.claude_code.asyncio.create_subprocess_exec"
            ) as mock_exec:
                mock_process = AsyncMock()

                async def slow_communicate(input=None):
                    await asyncio.sleep(10)  # Simulate slow execution
                    return (b"", b"")

                mock_process.communicate = slow_communicate
                mock_process.kill = MagicMock()
                mock_process.wait = AsyncMock()
                mock_exec.return_value = mock_process

                result = await run_claude_code(
                    folder_name="project",
                    command="Slow task",
                    timeout=1,  # 1 second timeout
                    working_dir_base=str(workspace_dir),
                )

        assert result["success"] is False
        assert "timeout" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_run_claude_not_installed(self, tmp_path):
        """Test error when Claude CLI is not installed."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "project"
        project_dir.mkdir()

        with patch("agent_framework.tools.claude_code.shutil.which", return_value=None):
            result = await run_claude_code(
                folder_name="project",
                command="Do something",
                working_dir_base=str(workspace_dir),
            )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_run_nonexistent_workspace(self, tmp_path):
        """Test running in nonexistent workspace."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()

        result = await run_claude_code(
            folder_name="nonexistent",
            command="Do something",
            working_dir_base=str(workspace_dir),
        )

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_run_with_custom_instructions(self, tmp_path):
        """Test running with custom instructions prepended."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "project"
        project_dir.mkdir()

        with patch(
            "agent_framework.tools.claude_code.shutil.which", return_value="/usr/bin/claude"
        ):
            with patch(
                "agent_framework.tools.claude_code.asyncio.create_subprocess_exec"
            ) as mock_exec:
                mock_process = AsyncMock()
                mock_process.communicate = AsyncMock(return_value=(b"Done", b""))
                mock_process.returncode = 0
                mock_exec.return_value = mock_process

                await run_claude_code(
                    folder_name="project",
                    command="Do the task",
                    custom_instructions="Always use TypeScript",
                    working_dir_base=str(workspace_dir),
                )

                # Verify the input includes both custom instructions and command
                communicate_call = mock_process.communicate.call_args
                input_bytes = communicate_call[1]["input"]
                input_str = input_bytes.decode("utf-8")

                assert "Always use TypeScript" in input_str
                assert "Do the task" in input_str

    @pytest.mark.asyncio
    async def test_run_with_different_model(self, tmp_path):
        """Test running with different model specified."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "project"
        project_dir.mkdir()

        with patch(
            "agent_framework.tools.claude_code.shutil.which", return_value="/usr/bin/claude"
        ):
            with patch(
                "agent_framework.tools.claude_code.asyncio.create_subprocess_exec"
            ) as mock_exec:
                mock_process = AsyncMock()
                mock_process.communicate = AsyncMock(return_value=(b"Done", b""))
                mock_process.returncode = 0
                mock_exec.return_value = mock_process

                await run_claude_code(
                    folder_name="project",
                    command="Do something",
                    model="opus",
                    working_dir_base=str(workspace_dir),
                )

                # Verify model flag is included
                call_args = mock_exec.call_args[0]
                assert "--model" in call_args
                assert "opus" in call_args

    @pytest.mark.asyncio
    async def test_run_invalid_model(self, tmp_path):
        """Test running with invalid model."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "project"
        project_dir.mkdir()

        with patch(
            "agent_framework.tools.claude_code.shutil.which", return_value="/usr/bin/claude"
        ):
            result = await run_claude_code(
                folder_name="project",
                command="Do something",
                model="invalid_model",
                working_dir_base=str(workspace_dir),
            )

        assert result["success"] is False
        assert "Unknown model" in result["error"]

    @pytest.mark.asyncio
    async def test_run_uses_stdin_not_message_flag(self, tmp_path):
        """Test that run_claude_code uses stdin instead of --message flag."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "project"
        project_dir.mkdir()

        with patch(
            "agent_framework.tools.claude_code.shutil.which", return_value="/usr/bin/claude"
        ):
            with patch(
                "agent_framework.tools.claude_code.asyncio.create_subprocess_exec"
            ) as mock_exec:
                mock_process = AsyncMock()
                mock_process.communicate = AsyncMock(return_value=(b"Done", b""))
                mock_process.returncode = 0
                mock_exec.return_value = mock_process

                await run_claude_code(
                    folder_name="project",
                    command="Test command with special chars: \"quotes\" and 'apostrophes'",
                    working_dir_base=str(workspace_dir),
                )

                # Verify --message is NOT in args (we use stdin now)
                call_args = mock_exec.call_args[0]
                assert "--message" not in call_args

                # Verify -p flag is used for print mode
                assert "-p" in call_args

                # Verify stdin is set to PIPE
                call_kwargs = mock_exec.call_args[1]
                assert call_kwargs.get("stdin") == asyncio.subprocess.PIPE

                # Verify command was passed via stdin
                communicate_call = mock_process.communicate.call_args
                assert "input" in communicate_call[1]

    @pytest.mark.asyncio
    async def test_run_uses_dangerously_skip_permissions(self, tmp_path):
        """Test that run_claude_code uses --dangerously-skip-permissions flag."""
        workspace_dir = tmp_path / "workspaces"
        workspace_dir.mkdir()
        project_dir = workspace_dir / "project"
        project_dir.mkdir()

        with patch(
            "agent_framework.tools.claude_code.shutil.which", return_value="/usr/bin/claude"
        ):
            with patch(
                "agent_framework.tools.claude_code.asyncio.create_subprocess_exec"
            ) as mock_exec:
                mock_process = AsyncMock()
                mock_process.communicate = AsyncMock(return_value=(b"Done", b""))
                mock_process.returncode = 0
                mock_exec.return_value = mock_process

                await run_claude_code(
                    folder_name="project",
                    command="Do something",
                    working_dir_base=str(workspace_dir),
                )

                call_args = mock_exec.call_args[0]
                assert "--dangerously-skip-permissions" in call_args
