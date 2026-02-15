#!/usr/bin/env python3
"""Garbage-collect stale Claude Code workspaces.

Scans the workspaces directory, checks the age of each workspace (via
``git log`` for the last commit time, falling back to directory mtime),
and deletes any that exceed the configured max age.

Usage:
    uv run python scripts/cleanup_workspaces.py                # dry run by default
    uv run python scripts/cleanup_workspaces.py --delete       # actually delete
    uv run python scripts/cleanup_workspaces.py --max-age 5    # 5-day threshold
    uv run python scripts/cleanup_workspaces.py --dir /tmp/ws  # custom directory

Intended to be run via cron or systemd timer, e.g.:
    0 3 * * * cd /home/user/build/agents && uv run python scripts/cleanup_workspaces.py --delete
"""

from __future__ import annotations

import argparse
import shutil
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

DEFAULT_WORKSPACES_DIR = Path.home() / ".claude_code_workspaces"
DEFAULT_MAX_AGE_DAYS = 3


def _last_commit_epoch(workspace: Path) -> float | None:
    """Get epoch timestamp of the most recent git commit in a workspace."""
    if not (workspace / ".git").exists():
        return None
    try:
        result = subprocess.run(  # nosec B603 B607
            ["git", "log", "-1", "--format=%ct"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


def _workspace_age_epoch(workspace: Path) -> float:
    """Best-effort timestamp of last meaningful activity in a workspace.

    Uses the last git commit time if available, otherwise falls back to
    the directory's mtime.
    """
    commit_time = _last_commit_epoch(workspace)
    if commit_time is not None:
        return commit_time
    return workspace.stat().st_mtime


def _format_age(seconds: float) -> str:
    """Human-readable age string."""
    days = seconds / 86400
    if days >= 1:
        return f"{days:.1f}d"
    hours = seconds / 3600
    return f"{hours:.1f}h"


def cleanup_workspaces(
    workspaces_dir: Path,
    max_age_days: float,
    delete: bool,
    force: bool,
) -> None:
    """Scan and remove stale workspaces."""
    if not workspaces_dir.is_dir():
        print(f"Workspaces directory does not exist: {workspaces_dir}")
        sys.exit(0)

    now = time.time()
    max_age_seconds = max_age_days * 86400

    entries = sorted(workspaces_dir.iterdir())
    workspaces = [e for e in entries if e.is_dir()]

    if not workspaces:
        print("No workspaces found.")
        return

    stale: list[tuple[Path, float]] = []
    fresh: list[tuple[Path, float]] = []

    for ws in workspaces:
        age_epoch = _workspace_age_epoch(ws)
        age_seconds = now - age_epoch
        if age_seconds > max_age_seconds:
            stale.append((ws, age_seconds))
        else:
            fresh.append((ws, age_seconds))

    # Report
    print(f"Workspaces directory: {workspaces_dir}")
    print(f"Max age: {max_age_days} days")
    print(f"Total: {len(workspaces)} | Stale: {len(stale)} | Fresh: {len(fresh)}")
    print()

    if not stale:
        print("Nothing to clean up.")
        return

    for ws, age in stale:
        action = "DELETE" if delete else "WOULD DELETE"
        print(f"  [{action}] {ws.name}  (age: {_format_age(age)})")

    print()

    if not delete:
        print("Dry run — pass --delete to actually remove these workspaces.")
        return

    deleted = 0
    errors = 0
    for ws, _age in stale:
        # Safety check: skip workspaces with uncommitted changes unless forced
        if not force and (ws / ".git").exists():
            try:
                result = subprocess.run(  # nosec B603 B607
                    ["git", "status", "--porcelain"],
                    cwd=ws,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    print(f"  SKIPPED {ws.name} (uncommitted changes, use --force)")
                    continue
            except (subprocess.TimeoutExpired, OSError):
                pass

        try:
            shutil.rmtree(ws)
            deleted += 1
        except OSError as e:
            print(f"  ERROR deleting {ws.name}: {e}")
            errors += 1

    print(f"Deleted {deleted} workspace(s).", end="")
    if errors:
        print(f" {errors} error(s).", end="")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Garbage-collect stale Claude Code workspaces.",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_WORKSPACES_DIR,
        help=f"Workspaces directory (default: {DEFAULT_WORKSPACES_DIR})",
    )
    parser.add_argument(
        "--max-age",
        type=float,
        default=DEFAULT_MAX_AGE_DAYS,
        help=f"Max age in days before a workspace is considered stale (default: {DEFAULT_MAX_AGE_DAYS})",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete stale workspaces (default is dry run)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete even if workspace has uncommitted git changes",
    )
    args = parser.parse_args()

    cleanup_workspaces(
        workspaces_dir=args.dir,
        max_age_days=args.max_age,
        delete=args.delete,
        force=args.force,
    )


if __name__ == "__main__":
    main()
