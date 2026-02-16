"""Tests for filesystem tool security: path validation, symlink escape, binary rejection, ReDoS."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from agent_framework.tools.filesystem import (
    FilesystemValidator,
    _is_binary,
    _is_redos_pattern,
    glob_files,
    grep_files,
    read_file,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a temp workspace with allowed dirs set."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "hello.txt").write_text("line one\nline two\nline three\n")
    (allowed / "data.py").write_text("import os\nprint('hello')\n")
    return allowed


@pytest.fixture(autouse=True)
def _set_allowed_dirs(workspace: Path):  # type: ignore[type-arg]
    """Point FILESYSTEM_ALLOWED_DIRS at the test workspace and invalidate cache."""
    import agent_framework.tools.filesystem as _fs_mod

    with patch.dict(os.environ, {"FILESYSTEM_ALLOWED_DIRS": str(workspace)}):
        # Force validator cache rebuild
        _fs_mod._validator_env_snapshot = ""
        yield


class TestPathValidation:
    """Ensure paths outside allowed directories are rejected."""

    def test_rejects_when_no_dirs_configured(self) -> None:
        with patch.dict(os.environ, {"FILESYSTEM_ALLOWED_DIRS": ""}):
            v = FilesystemValidator()
            with pytest.raises(PermissionError, match="No allowed directories"):
                v.validate("/etc/passwd")

    def test_rejects_path_outside_allowed(self, workspace: Path) -> None:
        v = FilesystemValidator()
        with pytest.raises(PermissionError, match="outside allowed"):
            v.validate("/etc/passwd")

    def test_rejects_dotdot_traversal(self, workspace: Path) -> None:
        v = FilesystemValidator()
        with pytest.raises(ValueError, match="contains '..'"):
            v.validate(str(workspace / ".." / "etc" / "passwd"))

    def test_allows_valid_path(self, workspace: Path) -> None:
        v = FilesystemValidator()
        result = v.validate(str(workspace / "hello.txt"))
        assert result == (workspace / "hello.txt").resolve()

    def test_symlink_escape_blocked(self, workspace: Path) -> None:
        """Symlink pointing outside allowed dirs should be rejected."""
        link = workspace / "escape"
        link.symlink_to("/etc")
        v = FilesystemValidator()
        with pytest.raises(PermissionError, match="outside allowed"):
            v.validate(str(link / "passwd"))


class TestReadFile:
    """Test read_file security boundaries."""

    @pytest.mark.asyncio
    async def test_reads_valid_file(self, workspace: Path) -> None:
        result = await read_file(str(workspace / "hello.txt"))
        assert "error" not in result
        assert result["total_lines"] == 3
        assert "line one" in result["content"]

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, workspace: Path) -> None:
        result = await read_file(str(workspace / ".." / ".." / "etc" / "passwd"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_binary_file(self, workspace: Path) -> None:
        binary = workspace / "binary.dat"
        binary.write_bytes(b"\x00\x01\x02\x03")
        result = await read_file(str(binary))
        assert "error" in result
        assert "Binary" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_large_file(self, workspace: Path) -> None:
        large = workspace / "large.txt"
        large.write_text("x" * (1_048_576 + 1))  # > 1 MB default
        result = await read_file(str(large))
        assert "error" in result
        assert "too large" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_offset_and_limit(self, workspace: Path) -> None:
        result = await read_file(str(workspace / "hello.txt"), offset=2, limit=1)
        assert result["lines_shown"] == 1
        assert "line two" in result["content"]

    @pytest.mark.asyncio
    async def test_not_a_file(self, workspace: Path) -> None:
        result = await read_file(str(workspace))
        assert "error" in result
        assert "Not a file" in result["error"]


class TestGlobFiles:
    """Test glob_files security boundaries."""

    @pytest.mark.asyncio
    async def test_finds_matching_files(self, workspace: Path) -> None:
        result = await glob_files("*.py", str(workspace))
        assert result["count"] == 1
        assert "data.py" in result["matches"][0]["path"]

    @pytest.mark.asyncio
    async def test_rejects_dotdot_in_pattern(self, workspace: Path) -> None:
        result = await glob_files("../../etc/*", str(workspace))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_absolute_pattern(self, workspace: Path) -> None:
        result = await glob_files("/etc/passwd", str(workspace))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_symlink_escape_in_glob(self, workspace: Path) -> None:
        """Symlinks matching a glob that point outside allowed dirs are skipped."""
        import agent_framework.tools.filesystem as _fs_mod

        # Create a directory outside the allowed workspace
        outside = workspace.parent / "outside"
        outside.mkdir(exist_ok=True)
        secret = outside / "secret.py"
        secret.write_text("SECRET = 'leaked'")

        subdir = workspace / "sub"
        subdir.mkdir()
        link = subdir / "escape.py"
        link.symlink_to(str(secret))

        # Create validator scoped to workspace only and patch it globally
        with patch.dict(os.environ, {"FILESYSTEM_ALLOWED_DIRS": str(workspace)}):
            v = FilesystemValidator()
            with patch.object(_fs_mod, "_get_validator", return_value=v):
                result = await _fs_mod.glob_files("**/*.py", str(workspace))

        # escape.py should NOT appear because it resolves outside allowed dirs
        filenames = [Path(m["path"]).name for m in result["matches"]]
        assert "escape.py" not in filenames, f"Symlink escape leaked: {filenames}"


class TestGrepFiles:
    """Test grep_files security: ReDoS, pattern limits, path validation."""

    @pytest.mark.asyncio
    async def test_basic_grep(self, workspace: Path) -> None:
        result = await grep_files("import", str(workspace))
        assert result["count"] >= 1
        assert any("import" in m["content"] for m in result["matches"])

    @pytest.mark.asyncio
    async def test_rejects_redos_pattern(self, workspace: Path) -> None:
        result = await grep_files("(a+)+$", str(workspace))
        assert "error" in result
        assert "ReDoS" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_long_pattern(self, workspace: Path) -> None:
        result = await grep_files("a" * 1001, str(workspace))
        assert "error" in result
        assert "too long" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_regex(self, workspace: Path) -> None:
        result = await grep_files("[invalid", str(workspace))
        assert "error" in result
        assert "Invalid regex" in result["error"]

    @pytest.mark.asyncio
    async def test_case_insensitive(self, workspace: Path) -> None:
        result = await grep_files("IMPORT", str(workspace), case_sensitive=False)
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_glob_filter(self, workspace: Path) -> None:
        result = await grep_files("line", str(workspace), glob="*.txt")
        assert result["count"] >= 1
        assert all(m["file"].endswith(".txt") for m in result["matches"])


class TestBinaryDetection:
    """Test the binary file heuristic."""

    def test_detects_null_bytes(self) -> None:
        assert _is_binary(b"hello\x00world") is True

    def test_accepts_plain_text(self) -> None:
        assert _is_binary(b"hello world\n") is False

    def test_empty_bytes(self) -> None:
        assert _is_binary(b"") is False

    def test_null_byte_beyond_8k(self) -> None:
        """Null byte at position > 8192 should not trigger binary detection."""
        data = b"x" * 8193 + b"\x00"
        assert _is_binary(data) is False


class TestReDoSProtection:
    """Test nested quantifier detection."""

    def test_detects_nested_plus(self) -> None:
        assert _is_redos_pattern("(a+)+") is True

    def test_detects_nested_star(self) -> None:
        assert _is_redos_pattern("(a*)*") is True

    def test_detects_nested_repeat(self) -> None:
        assert _is_redos_pattern(r"(\d{1,10})+") is True

    def test_allows_simple_patterns(self) -> None:
        assert _is_redos_pattern(r"\d+") is False
        assert _is_redos_pattern(r"[a-z]+") is False
        assert _is_redos_pattern(r"hello world") is False

    def test_detects_alternation_in_quantifier(self) -> None:
        assert _is_redos_pattern("(a|a)+") is True

    def test_invalid_regex_returns_false(self) -> None:
        """Invalid regex can't be parsed - returns False (caught later by re.compile)."""
        assert _is_redos_pattern("[invalid") is False
