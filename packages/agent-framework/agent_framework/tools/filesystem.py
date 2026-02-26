"""Filesystem tools for code analysis and modification.

Provides tools to read, write, and edit files, list directories, glob for
files, and grep file contents.  All operations are scoped to directories
listed in the ``FILESYSTEM_ALLOWED_DIRS`` environment variable
(comma-separated absolute paths).  Paths are resolved through symlinks
before validation so that symlink escapes are caught.
"""

import fnmatch
import logging
import os
import re
import sre_parse
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Maximum file size we'll read (bytes).  Override via env var.
MAX_FILE_SIZE = int(os.environ.get("FILESYSTEM_MAX_FILE_SIZE", 1_048_576))  # 1 MB

# Hard cap on result items returned by list/glob/grep.
MAX_RESULTS = 500


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------


class FilesystemValidator:
    """Validate that paths fall within the configured allowed directories."""

    def __init__(self) -> None:
        raw = os.environ.get("FILESYSTEM_ALLOWED_DIRS", "")
        self._allowed_dirs: list[Path] = []
        for entry in raw.split(","):
            entry = entry.strip()
            if entry:
                resolved = Path(entry).resolve()
                if resolved.is_dir():
                    self._allowed_dirs.append(resolved)
                else:
                    logger.warning(
                        "FILESYSTEM_ALLOWED_DIRS entry is not a directory, skipping: %s", entry
                    )

    @property
    def configured(self) -> bool:
        return len(self._allowed_dirs) > 0

    def validate(self, path: str) -> Path:
        """Resolve *path* and verify it lives under an allowed directory.

        Raises ``PermissionError`` if the path is outside all allowed dirs or
        if no allowed dirs are configured.  Raises ``ValueError`` if the raw
        path contains ``..`` segments (defense-in-depth).
        """
        if not self.configured:
            raise PermissionError(
                "No allowed directories configured. Set FILESYSTEM_ALLOWED_DIRS "
                "environment variable to a comma-separated list of absolute paths."
            )

        # Defense in depth: reject raw ".." before resolution
        raw_parts = Path(path).parts
        if ".." in raw_parts:
            raise ValueError(f"Path contains '..': {path}")

        resolved = Path(path).resolve()

        for allowed in self._allowed_dirs:
            try:
                resolved.relative_to(allowed)
                return resolved
            except ValueError:
                continue

        raise PermissionError(
            f"Path {path} (resolved to {resolved}) is outside allowed directories: "
            f"{[str(d) for d in self._allowed_dirs]}"
        )


# Module-level cached validator.  Rebuilt only when the env var changes.
_validator = FilesystemValidator()
_validator_env_snapshot = os.environ.get("FILESYSTEM_ALLOWED_DIRS", "")


def _get_validator() -> FilesystemValidator:
    """Return the cached validator, rebuilding only if the env var changed."""
    global _validator, _validator_env_snapshot  # noqa: PLW0603
    current = os.environ.get("FILESYSTEM_ALLOWED_DIRS", "")
    if current != _validator_env_snapshot:
        _validator = FilesystemValidator()
        _validator_env_snapshot = current
    return _validator


def _is_binary(data: bytes) -> bool:
    """Heuristic: file is binary if it contains null bytes in the first 8 KB."""
    return b"\x00" in data[:8192]


# Maximum length of a single line we'll run regex against (defense in depth).
_MAX_GREP_LINE_LEN = 10_000

# Maximum regex pattern length.
_MAX_PATTERN_LEN = 1000

# sre_parse opcodes that represent quantifiers (repeat constructs).
_QUANTIFIER_OPCODES = {sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT}


def _has_nested_quantifier(parsed: sre_parse.SubPattern, in_quantifier: bool = False) -> bool:  # type: ignore[type-arg]
    """Walk a parsed regex AST and detect nested quantifiers or ambiguous alternation.

    Catches patterns like ``(a+)+``, ``(a*)*``, ``(\\d{1,10})+``
    (nested quantifiers) and ``(a|a)+`` (alternation inside a quantifier,
    which causes backtracking when branches overlap).
    """
    for op, av in parsed:  # type: ignore[assignment]
        if op in _QUANTIFIER_OPCODES:
            # av is (min, max, subpattern)
            if in_quantifier:
                return True
            if _has_nested_quantifier(av[2], in_quantifier=True):  # type: ignore[index]
                return True
        elif op == sre_parse.SUBPATTERN:
            # av is (group, add_flags, del_flags, pattern)
            if _has_nested_quantifier(av[-1], in_quantifier):  # type: ignore[index]
                return True
        elif op == sre_parse.BRANCH:
            # av is (None, [branch1, branch2, ...])
            # Alternation inside a quantifier is dangerous when branches
            # can match the same input (causes exponential backtracking).
            branches = av[1]  # type: ignore[index]
            if in_quantifier and len(branches) >= 2:  # type: ignore[arg-type]
                return True
            for branch in branches:  # type: ignore[union-attr]
                if _has_nested_quantifier(branch, in_quantifier):
                    return True
    return False


def _is_redos_pattern(pattern: str) -> bool:
    """Check if a regex pattern is vulnerable to ReDoS.

    Uses sre_parse to walk the AST and detect nested quantifiers.
    Returns True if the pattern looks dangerous.
    """
    try:
        parsed = sre_parse.parse(pattern)
    except re.error:
        return False  # Will be caught later by re.compile
    return _has_nested_quantifier(parsed)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def read_file(
    path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Read a file's content with line numbers (``cat -n`` style).

    Args:
        path: Absolute path to the file.
        offset: 1-based line number to start reading from.
        limit: Maximum number of lines to return.

    Returns:
        Dict with ``content``, ``path``, ``total_lines``, ``size_bytes``,
        ``truncated``, and ``error`` (if any).
    """
    validator = _get_validator()
    try:
        resolved = validator.validate(path)

        if not resolved.is_file():
            return {"error": f"Not a file: {path}"}

        raw = resolved.read_bytes()
        size = len(raw)
        if size > MAX_FILE_SIZE:
            return {
                "error": f"File too large ({size:,} bytes). Max is {MAX_FILE_SIZE:,} bytes.",
                "path": str(resolved),
                "size_bytes": size,
            }

        if _is_binary(raw):
            return {"error": f"Binary file: {path}", "path": str(resolved), "size_bytes": size}

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"error": f"Not a UTF-8 text file: {path}", "path": str(resolved)}
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)

        start = (offset or 1) - 1  # convert to 0-based
        start = max(0, min(start, total_lines))
        end = start + limit if limit else total_lines
        selected = lines[start:end]

        # Format with line numbers
        numbered = []
        for i, line in enumerate(selected, start=start + 1):
            numbered.append(f"{i:>6}\t{line.rstrip()}")

        return {
            "content": "\n".join(numbered),
            "path": str(resolved),
            "total_lines": total_lines,
            "lines_shown": len(selected),
            "size_bytes": size,
            "truncated": end < total_lines,
        }

    except (PermissionError, ValueError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("read_file error: %s", e)
        return {"error": str(e)}


async def list_directory(
    path: str,
    include_hidden: bool = False,
) -> dict[str, Any]:
    """List entries in a directory.

    Args:
        path: Absolute path to a directory.
        include_hidden: Whether to include dot-files/dirs.

    Returns:
        Dict with ``entries`` list (name, type, size_bytes) and metadata.
    """
    validator = _get_validator()
    try:
        resolved = validator.validate(path)

        if not resolved.is_dir():
            return {"error": f"Not a directory: {path}"}

        dirs: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []

        for item in sorted(resolved.iterdir()):
            name = item.name
            if not include_hidden and name.startswith("."):
                continue

            try:
                stat = item.stat()
            except OSError:
                continue

            entry: dict[str, Any] = {"name": name}
            if item.is_dir():
                entry["type"] = "directory"
                dirs.append(entry)
            else:
                entry["type"] = "file"
                entry["size_bytes"] = stat.st_size
                files.append(entry)

            if len(dirs) + len(files) >= MAX_RESULTS:
                break

        entries = dirs + files
        return {
            "entries": entries,
            "path": str(resolved),
            "count": len(entries),
            "truncated": len(entries) >= MAX_RESULTS,
        }

    except (PermissionError, ValueError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("list_directory error: %s", e)
        return {"error": str(e)}


async def glob_files(
    pattern: str,
    path: str,
) -> dict[str, Any]:
    """Find files matching a glob pattern under *path*.

    Args:
        pattern: Glob pattern (e.g. ``**/*.py``).
        path: Root directory to search from (must be within allowed dirs).

    Returns:
        Dict with ``matches`` list (path, size_bytes) and metadata.
    """
    validator = _get_validator()
    try:
        resolved = validator.validate(path)

        if not resolved.is_dir():
            return {"error": f"Not a directory: {path}"}

        # Reject patterns that could traverse outside root
        if ".." in Path(pattern).parts or pattern.startswith("/"):
            return {"error": "Pattern must not contain '..' path segments or start with '/'"}

        matches: list[dict[str, Any]] = []
        for match in sorted(resolved.glob(pattern)):
            if not match.is_file():
                continue
            # Validate each resolved match is within allowed dirs.
            # validate() calls Path.resolve() which follows symlinks,
            # so symlinks pointing outside allowed dirs are caught here.
            try:
                validator.validate(str(match))
            except (PermissionError, ValueError):
                continue

            try:
                size = match.stat().st_size
            except OSError:
                size = 0

            matches.append({"path": str(match), "size_bytes": size})
            if len(matches) >= MAX_RESULTS:
                break

        return {
            "matches": matches,
            "pattern": pattern,
            "root": str(resolved),
            "count": len(matches),
            "truncated": len(matches) >= MAX_RESULTS,
        }

    except (PermissionError, ValueError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("glob_files error: %s", e)
        return {"error": str(e)}


async def grep_files(
    pattern: str,
    path: str,
    glob: str | None = None,
    max_matches: int = 200,
    case_sensitive: bool = True,
) -> dict[str, Any]:
    """Search file contents by regex under *path*.

    Args:
        pattern: Regular expression to search for.
        path: Root directory to search from.
        glob: Optional glob to filter which files are searched (e.g. ``*.py``).
        max_matches: Maximum total matches to return.
        case_sensitive: Whether the regex is case-sensitive.

    Returns:
        Dict with ``matches`` list (file, line, content) and metadata.
    """
    validator = _get_validator()
    try:
        resolved = validator.validate(path)

        if not resolved.is_dir():
            return {"error": f"Not a directory: {path}"}

        # Guard against ReDoS
        if len(pattern) > _MAX_PATTERN_LEN:
            return {
                "error": f"Regex pattern too long ({len(pattern)} chars, max {_MAX_PATTERN_LEN})"
            }
        if _is_redos_pattern(pattern):
            return {"error": "Regex contains nested quantifiers (potential ReDoS)"}

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return {"error": f"Invalid regex: {e}"}

        cap = min(max_matches, MAX_RESULTS)
        matches: list[dict[str, Any]] = []

        # Walk the tree
        for dirpath, _dirnames, filenames in os.walk(resolved):
            for fname in sorted(filenames):
                if glob and not fnmatch.fnmatch(fname, glob):
                    continue

                fpath = Path(dirpath) / fname
                try:
                    validator.validate(str(fpath))
                except (PermissionError, ValueError):
                    continue

                try:
                    raw = fpath.read_bytes()
                except OSError:
                    continue

                if len(raw) > MAX_FILE_SIZE:
                    continue

                if _is_binary(raw):
                    continue

                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue

                for lineno, line in enumerate(text.splitlines(), start=1):
                    if regex.search(line[:_MAX_GREP_LINE_LEN]):
                        matches.append(
                            {
                                "file": str(fpath),
                                "line": lineno,
                                "content": line.rstrip()[:500],  # cap line length
                            }
                        )
                        if len(matches) >= cap:
                            break

                if len(matches) >= cap:
                    break
            if len(matches) >= cap:
                break

        return {
            "matches": matches,
            "pattern": pattern,
            "root": str(resolved),
            "count": len(matches),
            "truncated": len(matches) >= cap,
        }

    except (PermissionError, ValueError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("grep_files error: %s", e)
        return {"error": str(e)}


async def write_file(
    path: str,
    content: str,
    create_dirs: bool = False,
) -> dict[str, Any]:
    """Write content to a file.

    Creates a new file or overwrites an existing one.  Parent directories
    can optionally be created.

    Args:
        path: Absolute path to the file to write.
        content: Text content to write.
        create_dirs: If True, create parent directories as needed.

    Returns:
        Dict with ``success``, ``path``, ``size_bytes``, ``created``,
        and ``error`` (if any).
    """
    validator = _get_validator()
    try:
        resolved = validator.validate(path)

        content_bytes = content.encode("utf-8")
        if len(content_bytes) > MAX_FILE_SIZE:
            return {
                "error": (
                    f"Content too large ({len(content_bytes):,} bytes). "
                    f"Max is {MAX_FILE_SIZE:,} bytes."
                ),
                "path": str(resolved),
            }

        if resolved.is_dir():
            return {"error": f"Path is a directory, not a file: {resolved}", "path": str(resolved)}

        created = not resolved.exists()

        if not resolved.parent.exists():
            if create_dirs:
                # Validate the parent is also within allowed dirs
                validator.validate(str(resolved.parent))
                resolved.parent.mkdir(parents=True, exist_ok=True)
            else:
                return {
                    "error": (
                        f"Parent directory does not exist: {resolved.parent}. "
                        "Set create_dirs=true to create it."
                    ),
                    "path": str(resolved),
                }

        resolved.write_bytes(content_bytes)
        size = len(content_bytes)

        action = "created" if created else "overwrote"
        logger.info("write_file: %s %s (%d bytes)", action, resolved, size)

        return {
            "success": True,
            "path": str(resolved),
            "size_bytes": size,
            "created": created,
        }

    except (PermissionError, ValueError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("write_file error: %s", e)
        return {"error": str(e)}


async def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> dict[str, Any]:
    """Edit a file by replacing an exact string match.

    Reads the file, finds ``old_string``, and replaces it with
    ``new_string``.  By default the match must be unique (appear exactly
    once); set ``replace_all=True`` to replace every occurrence.

    Args:
        path: Absolute path to the file to edit.
        old_string: The exact text to find and replace.
        new_string: The replacement text.
        replace_all: Replace all occurrences instead of requiring uniqueness.

    Returns:
        Dict with ``success``, ``path``, ``replacements``, ``size_bytes``,
        and ``error`` (if any).
    """
    validator = _get_validator()
    try:
        resolved = validator.validate(path)

        if not resolved.is_file():
            return {"error": f"Not a file: {path}"}

        raw = resolved.read_bytes()
        if len(raw) > MAX_FILE_SIZE:
            return {
                "error": f"File too large ({len(raw):,} bytes). Max is {MAX_FILE_SIZE:,} bytes.",
                "path": str(resolved),
            }

        if _is_binary(raw):
            return {"error": f"Binary file: {path}", "path": str(resolved)}

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"error": f"Not a UTF-8 text file: {path}", "path": str(resolved)}

        if not old_string:
            return {"error": "old_string cannot be empty", "path": str(resolved)}

        if old_string == new_string:
            return {"error": "old_string and new_string are identical", "path": str(resolved)}

        count = text.count(old_string)
        if count == 0:
            return {"error": "old_string not found in file", "path": str(resolved)}

        if not replace_all and count > 1:
            return {
                "error": (
                    f"old_string found {count} times. "
                    "Provide more context to make it unique, or set replace_all=true."
                ),
                "path": str(resolved),
            }

        if replace_all:
            new_text = text.replace(old_string, new_string)
        else:
            new_text = text.replace(old_string, new_string, 1)

        new_bytes = new_text.encode("utf-8")
        if len(new_bytes) > MAX_FILE_SIZE:
            return {
                "error": (
                    f"Edited content too large ({len(new_bytes):,} bytes). "
                    f"Max is {MAX_FILE_SIZE:,} bytes."
                ),
                "path": str(resolved),
            }

        resolved.write_bytes(new_bytes)

        logger.info(
            "edit_file: %d replacement(s) in %s (%d bytes)", count, resolved, len(new_bytes)
        )

        return {
            "success": True,
            "path": str(resolved),
            "replacements": count,
            "size_bytes": len(new_bytes),
        }

    except (PermissionError, ValueError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.error("edit_file error: %s", e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Read a file's content with line numbers (cat -n format). "
            "Supports reading specific line ranges with offset and limit. "
            "Only works on files within FILESYSTEM_ALLOWED_DIRS. "
            "Rejects binary files and files larger than FILESYSTEM_MAX_FILE_SIZE (default 1MB)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to read",
                },
                "offset": {
                    "type": "integer",
                    "description": "1-based line number to start reading from (default: 1)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (default: all)",
                },
            },
            "required": ["path"],
        },
        "handler": read_file,
    },
    {
        "name": "list_directory",
        "description": (
            "List entries in a directory. Returns name, type (file/directory), "
            "and size for each entry. Directories are listed first, then files, "
            "both sorted alphabetically. Only works within FILESYSTEM_ALLOWED_DIRS."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory to list",
                },
                "include_hidden": {
                    "type": "boolean",
                    "description": "Whether to include hidden files/directories (default: false)",
                    "default": False,
                },
            },
            "required": ["path"],
        },
        "handler": list_directory,
    },
    {
        "name": "glob_files",
        "description": (
            "Find files matching a glob pattern (e.g. '**/*.py', '*.ts', "
            "'src/**/*.test.js'). Returns matching file paths and sizes. "
            "Only searches within FILESYSTEM_ALLOWED_DIRS."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match (e.g. '**/*.py')",
                },
                "path": {
                    "type": "string",
                    "description": "Root directory to search from (absolute path)",
                },
            },
            "required": ["pattern", "path"],
        },
        "handler": glob_files,
    },
    {
        "name": "grep_files",
        "description": (
            "Search file contents using a regular expression. Returns matching "
            "file paths, line numbers, and line content. Skips binary files. "
            "Optionally filter by file glob (e.g. '*.py'). "
            "Only searches within FILESYSTEM_ALLOWED_DIRS."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Root directory to search from (absolute path)",
                },
                "glob": {
                    "type": "string",
                    "description": "Optional file glob to filter which files are searched (e.g. '*.py')",
                },
                "max_matches": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default: 200)",
                    "default": 200,
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether the regex is case-sensitive (default: true)",
                    "default": True,
                },
            },
            "required": ["pattern", "path"],
        },
        "handler": grep_files,
    },
    {
        "name": "write_file",
        "description": (
            "Write text content to a file. Creates a new file or overwrites an "
            "existing one. Optionally creates parent directories. "
            "Only works within FILESYSTEM_ALLOWED_DIRS. "
            "Content must be UTF-8 and under FILESYSTEM_MAX_FILE_SIZE (default 1MB)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write to the file",
                },
                "create_dirs": {
                    "type": "boolean",
                    "description": "Create parent directories if they don't exist (default: false)",
                    "default": False,
                },
            },
            "required": ["path", "content"],
        },
        "handler": write_file,
    },
    {
        "name": "edit_file",
        "description": (
            "Edit a file by finding and replacing an exact string. "
            "The old_string must appear exactly once unless replace_all is true. "
            "Only works on text files within FILESYSTEM_ALLOWED_DIRS."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find and replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement text",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences instead of requiring uniqueness (default: false)",
                    "default": False,
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
        "handler": edit_file,
    },
]
