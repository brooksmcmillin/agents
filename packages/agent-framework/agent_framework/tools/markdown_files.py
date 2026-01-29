"""Markdown file management tools.

These tools allow agents to read, write, list, and delete markdown files
from a dedicated directory, providing a simple file storage mechanism
for notes, documentation, and other markdown content.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default base directory for markdown files (configurable via environment)
DEFAULT_MARKDOWN_DIR = os.environ.get(
    "MARKDOWN_FILES_DIR",
    str(Path.home() / ".agent_markdown_files"),
)


def _validate_filename(filename: str) -> None:
    """Validate filename to prevent path traversal attacks.

    Args:
        filename: The filename to validate

    Raises:
        ValueError: If filename contains invalid characters or is invalid
    """
    # Must end with .md
    if not filename.endswith(".md"):
        raise ValueError(f"Invalid filename: {filename}. Must end with '.md'")

    # Get the name without extension for validation
    name_part = filename[:-3]

    # Only allow alphanumeric, hyphens, underscores, and dots (but not at start)
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_\-\.]*$", name_part):
        raise ValueError(
            f"Invalid filename: {filename}. "
            "Must start with alphanumeric and contain only alphanumeric, "
            "hyphens, underscores, and dots before the .md extension."
        )

    # Prevent path traversal
    if ".." in filename or "/" in filename or "\\" in filename:
        raise ValueError(f"Invalid filename: {filename}. Path traversal characters not allowed.")


def _get_markdown_dir(base_dir: str | None = None) -> Path:
    """Get the markdown files directory, creating it if needed.

    Args:
        base_dir: Optional custom base directory

    Returns:
        Path to the markdown files directory
    """
    dir_path = Path(base_dir or DEFAULT_MARKDOWN_DIR).expanduser()
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def _get_file_path(filename: str, base_dir: str | None = None) -> Path:
    """Get and validate the full file path.

    Args:
        filename: Name of the markdown file (must end with .md)
        base_dir: Optional custom base directory

    Returns:
        Path object for the file

    Raises:
        ValueError: If filename is invalid
    """
    _validate_filename(filename)
    return _get_markdown_dir(base_dir) / filename


async def list_markdown_files(
    base_dir: str | None = None,
) -> dict[str, Any]:
    """List all markdown files in the storage directory.

    Args:
        base_dir: Optional custom base directory for markdown files

    Returns:
        Dict with:
            - files: List of file info dicts containing:
                - name: File name
                - path: Full path to file
                - size_bytes: File size in bytes
                - modified_at: Last modified timestamp (ISO format)
            - base_dir: Base directory being used
            - count: Total number of files

    Example:
        >>> result = await list_markdown_files()
        >>> for f in result['files']:
        ...     print(f"{f['name']}: {f['size_bytes']} bytes")
    """
    try:
        dir_path = _get_markdown_dir(base_dir)

        files = []
        for item in sorted(dir_path.iterdir()):
            if item.is_file() and item.suffix == ".md":
                stat = item.stat()
                files.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "size_bytes": stat.st_size,
                        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )

        return {
            "files": files,
            "base_dir": str(dir_path),
            "count": len(files),
        }

    except Exception as e:
        logger.error(f"Error listing markdown files: {e}")
        return {
            "files": [],
            "base_dir": str(base_dir or DEFAULT_MARKDOWN_DIR),
            "count": 0,
            "error": str(e),
        }


async def read_markdown_file(
    filename: str,
    base_dir: str | None = None,
) -> dict[str, Any]:
    """Read a markdown file's content.

    Args:
        filename: Name of the markdown file (must end with .md)
        base_dir: Optional custom base directory

    Returns:
        Dict with:
            - success: bool - Whether file was read successfully
            - filename: str - The filename
            - path: str - Full path to the file
            - content: str - File content
            - size_bytes: int - File size in bytes
            - modified_at: str - Last modified timestamp (ISO format)

    Raises:
        ValueError: If filename is invalid
        FileNotFoundError: If file doesn't exist

    Example:
        >>> result = await read_markdown_file("notes.md")
        >>> print(result['content'])
    """
    try:
        file_path = _get_file_path(filename, base_dir)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {filename}")

        if not file_path.is_file():
            raise ValueError(f"Path exists but is not a file: {filename}")

        content = file_path.read_text(encoding="utf-8")
        stat = file_path.stat()

        logger.info(f"Read markdown file: {filename}")

        return {
            "success": True,
            "filename": filename,
            "path": str(file_path),
            "content": content,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }

    except FileNotFoundError:
        logger.warning(f"Markdown file not found: {filename}")
        raise

    except Exception as e:
        logger.error(f"Error reading markdown file {filename}: {e}")
        return {
            "success": False,
            "filename": filename,
            "path": "",
            "content": "",
            "size_bytes": 0,
            "modified_at": "",
            "error": str(e),
        }


async def write_markdown_file(
    filename: str,
    content: str,
    base_dir: str | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Write content to a markdown file.

    Creates a new file or updates an existing one. Set overwrite=False to
    prevent overwriting existing files.

    Args:
        filename: Name of the markdown file (must end with .md)
        content: Markdown content to write
        base_dir: Optional custom base directory
        overwrite: Whether to overwrite existing files (default: True)

    Returns:
        Dict with:
            - success: bool - Whether file was written successfully
            - filename: str - The filename
            - path: str - Full path to the file
            - size_bytes: int - File size in bytes
            - created: bool - Whether a new file was created
            - message: str - Success or error message

    Raises:
        ValueError: If filename is invalid
        FileExistsError: If file exists and overwrite=False

    Example:
        >>> result = await write_markdown_file(
        ...     filename="notes.md",
        ...     content="# My Notes\\n\\nSome content here."
        ... )
        >>> print(result['path'])
    """
    file_path = None
    try:
        file_path = _get_file_path(filename, base_dir)

        created = not file_path.exists()

        if file_path.exists() and not overwrite:
            raise FileExistsError(
                f"File already exists: {filename}. Set overwrite=True to replace it."
            )

        file_path.write_text(content, encoding="utf-8")
        stat = file_path.stat()

        action = "Created" if created else "Updated"
        logger.info(f"{action} markdown file: {filename}")

        return {
            "success": True,
            "filename": filename,
            "path": str(file_path),
            "size_bytes": stat.st_size,
            "created": created,
            "message": f"{action} {filename} successfully",
        }

    except FileExistsError:
        logger.warning(f"Markdown file already exists: {filename}")
        raise

    except Exception as e:
        logger.error(f"Error writing markdown file {filename}: {e}")
        return {
            "success": False,
            "filename": filename,
            "path": str(file_path) if file_path else "",
            "size_bytes": 0,
            "created": False,
            "message": str(e),
            "error": str(e),
        }


async def delete_markdown_file(
    filename: str,
    base_dir: str | None = None,
) -> dict[str, Any]:
    """Delete a markdown file.

    Args:
        filename: Name of the markdown file to delete (must end with .md)
        base_dir: Optional custom base directory

    Returns:
        Dict with:
            - success: bool - Whether file was deleted successfully
            - filename: str - The filename
            - path: str - Path that was deleted
            - message: str - Success or error message

    Raises:
        ValueError: If filename is invalid
        FileNotFoundError: If file doesn't exist

    Example:
        >>> result = await delete_markdown_file("old-notes.md")
        >>> print(result['message'])
    """
    file_path = None
    try:
        file_path = _get_file_path(filename, base_dir)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {filename}")

        if not file_path.is_file():
            raise ValueError(f"Path exists but is not a file: {filename}")

        file_path.unlink()

        logger.info(f"Deleted markdown file: {filename}")

        return {
            "success": True,
            "filename": filename,
            "path": str(file_path),
            "message": f"Deleted {filename} successfully",
        }

    except FileNotFoundError:
        logger.warning(f"Markdown file not found for deletion: {filename}")
        raise

    except Exception as e:
        logger.error(f"Error deleting markdown file {filename}: {e}")
        return {
            "success": False,
            "filename": filename,
            "path": str(file_path) if file_path else "",
            "message": str(e),
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_markdown_files",
        "description": (
            "List all markdown files in the storage directory. "
            "Returns file names, paths, sizes, and modification timestamps. "
            "Use this to see what markdown files are available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "base_dir": {
                    "type": "string",
                    "description": "Optional custom base directory for markdown files (uses MARKDOWN_FILES_DIR env var or default if not provided)",
                },
            },
        },
        "handler": list_markdown_files,
    },
    {
        "name": "read_markdown_file",
        "description": (
            "Read a markdown file's content. "
            "Retrieves the full content of a markdown file from the storage directory. "
            "Useful for reading notes, documentation, or any stored markdown content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the markdown file to read (must end with .md)",
                },
                "base_dir": {
                    "type": "string",
                    "description": "Optional custom base directory",
                },
            },
            "required": ["filename"],
        },
        "handler": read_markdown_file,
    },
    {
        "name": "write_markdown_file",
        "description": (
            "Write content to a markdown file. "
            "Creates a new file or updates an existing one. "
            "Useful for saving notes, documentation, or any markdown content. "
            "Set overwrite=False to prevent accidentally replacing existing files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the markdown file (must end with .md)",
                },
                "content": {
                    "type": "string",
                    "description": "Markdown content to write to the file",
                },
                "base_dir": {
                    "type": "string",
                    "description": "Optional custom base directory",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether to overwrite existing files (default: true)",
                    "default": True,
                },
            },
            "required": ["filename", "content"],
        },
        "handler": write_markdown_file,
    },
    {
        "name": "delete_markdown_file",
        "description": (
            "Delete a markdown file from the storage directory. "
            "Permanently removes the specified markdown file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Name of the markdown file to delete (must end with .md)",
                },
                "base_dir": {
                    "type": "string",
                    "description": "Optional custom base directory",
                },
            },
            "required": ["filename"],
        },
        "handler": delete_markdown_file,
    },
]
