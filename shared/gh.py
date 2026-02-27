"""Shared helpers for running ``gh`` CLI commands.

Provides :func:`run_gh` (async subprocess wrapper) and
:func:`validate_repo` (``owner/repo`` format check) so that multiple
agents can shell out to ``gh`` without duplicating boilerplate.
"""

from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

REPO_RE = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")


def validate_repo(repo: str) -> str:
    """Validate ``owner/repo`` format. Raises :class:`ValueError` on mismatch."""
    if not REPO_RE.match(repo):
        raise ValueError(f"Invalid repo format (expected owner/repo): {repo!r}")
    return repo


async def run_gh(
    args: list[str], timeout: int = 30, cwd: str | None = None
) -> tuple[int, str, str]:
    """Run a ``gh`` CLI command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "gh",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        logger.warning("gh command timed out after %ds: gh %s", timeout, " ".join(args[:3]))
        return (1, "", f"timed out after {timeout}s")
    return (
        proc.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )
