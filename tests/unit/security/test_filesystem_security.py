"""Tests for filesystem tool security: path validation, symlink escape, binary rejection, ReDoS."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from agent_framework.tools.filesystem import (
    FilesystemValidator,
    _is_binary,
    _is_redos_pattern,
    edit_file,
    glob_files,
    grep_files,
    read_file,
    write_file,
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
        # Build pattern dynamically to avoid CodeQL flagging it as a vulnerability
        # (the whole point of this test is that grep_files rejects it before compilation)
        redos_pattern = "".join(["(a+)", "+$"])
        result = await grep_files(redos_pattern, str(workspace))
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


class TestWriteFile:
    """Test write_file security and functionality."""

    @pytest.mark.asyncio
    async def test_writes_new_file(self, workspace: Path) -> None:
        target = workspace / "new.txt"
        result = await write_file(str(target), "hello world\n")
        assert result.get("success") is True
        assert result["created"] is True
        assert result["size_bytes"] == 12
        assert target.read_text() == "hello world\n"

    @pytest.mark.asyncio
    async def test_overwrites_existing_file(self, workspace: Path) -> None:
        result = await write_file(str(workspace / "hello.txt"), "replaced\n")
        assert result.get("success") is True
        assert result["created"] is False
        assert (workspace / "hello.txt").read_text() == "replaced\n"

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, workspace: Path) -> None:
        result = await write_file(str(workspace / ".." / ".." / "etc" / "evil"), "bad")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_path_outside_allowed(self) -> None:
        result = await write_file("/tmp/not_allowed.txt", "bad")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_content_too_large(self, workspace: Path) -> None:
        result = await write_file(str(workspace / "big.txt"), "x" * (1_048_576 + 1))
        assert "error" in result
        assert "too large" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_rejects_missing_parent_without_create_dirs(self, workspace: Path) -> None:
        result = await write_file(str(workspace / "sub" / "deep" / "file.txt"), "content")
        assert "error" in result
        assert "create_dirs" in result["error"]

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, workspace: Path) -> None:
        target = workspace / "sub" / "deep" / "file.txt"
        result = await write_file(str(target), "nested content\n", create_dirs=True)
        assert result.get("success") is True
        assert target.read_text() == "nested content\n"

    @pytest.mark.asyncio
    async def test_symlink_escape_blocked(self, workspace: Path) -> None:
        """Writing through a symlink that escapes allowed dirs is rejected."""
        outside = workspace.parent / "outside_write"
        outside.mkdir(exist_ok=True)
        link = workspace / "escape_link"
        link.symlink_to(str(outside))
        result = await write_file(str(link / "evil.txt"), "bad content")
        assert "error" in result


class TestEditFile:
    """Test edit_file security and functionality."""

    @pytest.mark.asyncio
    async def test_basic_edit(self, workspace: Path) -> None:
        result = await edit_file(str(workspace / "hello.txt"), "line two", "line TWO")
        assert result.get("success") is True
        assert result["replacements"] == 1
        content = (workspace / "hello.txt").read_text()
        assert "line TWO" in content
        assert "line two" not in content

    @pytest.mark.asyncio
    async def test_rejects_not_found(self, workspace: Path) -> None:
        result = await edit_file(str(workspace / "hello.txt"), "nonexistent text", "replacement")
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_ambiguous_match(self, workspace: Path) -> None:
        # "line" appears 3 times in hello.txt
        result = await edit_file(str(workspace / "hello.txt"), "line", "LINE")
        assert "error" in result
        assert "3 times" in result["error"]

    @pytest.mark.asyncio
    async def test_replace_all(self, workspace: Path) -> None:
        result = await edit_file(str(workspace / "hello.txt"), "line", "LINE", replace_all=True)
        assert result.get("success") is True
        assert result["replacements"] == 3
        content = (workspace / "hello.txt").read_text()
        assert content.count("LINE") == 3
        assert "line" not in content

    @pytest.mark.asyncio
    async def test_rejects_identical_strings(self, workspace: Path) -> None:
        result = await edit_file(str(workspace / "hello.txt"), "line one", "line one")
        assert "error" in result
        assert "identical" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, workspace: Path) -> None:
        result = await edit_file(str(workspace / ".." / ".." / "etc" / "passwd"), "root", "hacked")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_rejects_binary_file(self, workspace: Path) -> None:
        binary = workspace / "binary.dat"
        binary.write_bytes(b"\x00\x01\x02\x03")
        result = await edit_file(str(binary), "old", "new")
        assert "error" in result
        assert "Binary" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_not_a_file(self, workspace: Path) -> None:
        result = await edit_file(str(workspace), "old", "new")
        assert "error" in result
        assert "Not a file" in result["error"]
