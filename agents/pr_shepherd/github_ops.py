"""GitHub operations via the ``gh`` CLI.

All functions shell out to ``gh`` via asyncio subprocesses so the service
stays stateless and avoids needing a GitHub token in code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from shared.gh import run_gh as _run_gh
from shared.gh import validate_repo

logger = logging.getLogger(__name__)


async def list_open_prs(repo: str, label: str | None = None) -> list[dict[str, Any]]:
    """List open PRs for *repo*, optionally filtered by label.

    Returns a list of dicts with ``number``, ``title``, ``headRefName``,
    and ``labels`` keys.
    """
    validate_repo(repo)
    cmd = [
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--json",
        "number,title,headRefName,labels",
    ]
    if label:
        cmd.extend(["--label", label])

    rc, out, err = await _run_gh(cmd)
    if rc != 0:
        logger.error(f"gh pr list failed for {repo}: {err}")
        return []

    try:
        prs = json.loads(out)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse gh pr list output: {out[:200]}")
        return []

    result: list[dict[str, Any]] = []
    for pr in prs:
        labels = [lb["name"] for lb in pr.get("labels", []) if isinstance(lb, dict)]
        result.append(
            {
                "number": pr["number"],
                "title": pr["title"],
                "headRefName": pr["headRefName"],
                "labels": labels,
            }
        )
    return result


async def get_check_status(repo: str, pr_number: int) -> tuple[str, list[str]]:
    """Return (overall_status, failing_check_names) for a PR.

    ``overall_status`` is one of ``"pass"``, ``"fail"``, or ``"pending"``.
    """
    rc, out, err = await _run_gh(
        ["pr", "checks", str(pr_number), "--repo", repo, "--json", "name,state"],
    )
    if rc != 0:
        # gh pr checks exits non-zero when checks are failing — that's expected
        if not out.strip():
            logger.warning(f"gh pr checks produced no output for {repo}#{pr_number}: {err}")
            return ("pending", [])

    try:
        checks = json.loads(out)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse gh pr checks output: {out[:200]}")
        return ("pending", [])

    if not checks:
        return ("pending", [])

    failing: list[str] = []
    any_pending = False
    for check in checks:
        state = check.get("state", "").upper()
        if state in ("FAILURE", "ERROR"):
            failing.append(check.get("name", "unknown"))
        elif state in ("PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"):
            any_pending = True

    if failing:
        return ("fail", failing)
    if any_pending:
        return ("pending", [])
    return ("pass", [])


async def get_failing_logs(repo: str, pr_number: int) -> str:
    """Fetch the failing CI run logs for *pr_number*.

    Returns log text (may be truncated). Empty string on failure.
    """
    # First get the failing run ID
    rc, out, err = await _run_gh(
        ["pr", "checks", str(pr_number), "--repo", repo, "--json", "name,state,link"],
    )
    if rc != 0 and not out.strip():
        return ""

    try:
        checks = json.loads(out)
    except json.JSONDecodeError:
        return ""

    # Find a failing check with a run link
    run_id = None
    for check in checks:
        state = check.get("state", "").upper()
        if state in ("FAILURE", "ERROR"):
            link = check.get("link", "")
            # Extract run ID from GitHub Actions URL
            match = re.search(r"/actions/runs/(\d+)", link)
            if match:
                run_id = match.group(1)
                break

    if not run_id:
        return ""

    rc, out, err = await _run_gh(
        ["run", "view", run_id, "--repo", repo, "--log-failed"],
        timeout=60,
    )
    if rc != 0:
        logger.warning(f"gh run view --log-failed failed: {err[:200]}")
        return ""

    # Truncate to keep context manageable
    max_len = 15000
    if len(out) > max_len:
        out = out[:max_len] + "\n\n... (logs truncated)"
    return out


async def merge_pr(repo: str, pr_number: int, method: str = "squash") -> bool:
    """Merge a PR. Returns True on success."""
    flag = f"--{method}"
    rc, out, err = await _run_gh(
        ["pr", "merge", str(pr_number), "--repo", repo, flag, "--delete-branch"],
    )
    if rc != 0:
        logger.error(f"gh pr merge failed for {repo}#{pr_number}: {err}")
        return False
    logger.info(f"Merged {repo}#{pr_number} via {method}")
    return True


async def add_comment(repo: str, pr_number: int, body: str) -> None:
    """Add a comment to a PR."""
    rc, _, err = await _run_gh(
        ["pr", "comment", str(pr_number), "--repo", repo, "--body", body],
    )
    if rc != 0:
        logger.warning(f"gh pr comment failed for {repo}#{pr_number}: {err[:200]}")


async def get_fix_attempt_count(repo: str, pr_number: int) -> int:
    """Count previous fix attempts by parsing PR comments for our prefix."""
    rc, out, err = await _run_gh(
        ["pr", "view", str(pr_number), "--repo", repo, "--json", "comments"],
    )
    if rc != 0:
        return 0

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return 0

    count = 0
    for comment in data.get("comments", []):
        body = comment.get("body", "")
        if body.startswith("[PR Shepherd] Fix attempt"):
            count += 1
    return count


# Known bot logins whose code review comments are trusted.
_TRUSTED_REVIEW_BOT_LOGINS: set[str] = {"claude"}


async def get_review_comments(repo: str, pr_number: int) -> str:
    """Fetch bot review comments from a PR (code review, not security review).

    Extracts comments left by trusted automated reviewers. A comment is
    included only when **both** conditions are met:

    1. The author is a known bot (login in ``_TRUSTED_REVIEW_BOT_LOGINS``
       or ending with ``[bot]``).
    2. The body contains the ``<!-- claude-code-review -->`` HTML marker.

    This prevents prompt-injection via forged markers in human comments.
    Security reviews are skipped because they rarely contain actionable
    code fixes.

    Returns empty string if there are no relevant comments.
    """
    rc, out, _ = await _run_gh(
        ["pr", "view", str(pr_number), "--repo", repo, "--json", "comments"],
    )
    if rc != 0:
        return ""

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return ""

    review_bodies: list[str] = []
    for comment in data.get("comments", []):
        body = comment.get("body", "")
        author = comment.get("author", {}).get("login", "")

        # Only trust comments from known bots
        if author not in _TRUSTED_REVIEW_BOT_LOGINS and not author.endswith("[bot]"):
            continue
        # Skip security reviews — they rarely contain actionable code fixes
        if "<!-- claude-security-review -->" in body:
            continue
        # Include code review bot comments
        if "<!-- claude-code-review -->" in body:
            review_bodies.append(body)

    if not review_bodies:
        return ""

    combined = "\n\n---\n\n".join(review_bodies)
    # Truncate to keep context manageable
    max_len = 10000
    if len(combined) > max_len:
        combined = combined[:max_len] + "\n\n... (review comments truncated)"
    return combined


async def configure_git_credentials(workspace_path: str) -> bool:
    """Configure ``gh`` CLI as the git credential helper for a workspace.

    Sets the local git config so that fetch, pull, and push operations
    authenticate via the ``gh`` CLI's existing token. This is needed
    because workspaces are cloned over HTTPS (for SSRF safety) and
    raw ``git push`` requires credentials.

    Should be called once after workspace creation, before any
    authenticated git operations.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "config",
            "--local",
            "credential.helper",
            "!gh auth git-credential",
            cwd=workspace_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    except TimeoutError:
        logger.error(f"git config timed out in {workspace_path}")
        return False
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")
        logger.error(f"Failed to configure git credentials in {workspace_path}: {err}")
        return False
    return True


async def push_branch(workspace_path: str, branch: str) -> bool:
    """Push a branch from *workspace_path*. Returns True on success."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "push",
            "origin",
            branch,
            cwd=workspace_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    except TimeoutError:
        logger.error(f"git push timed out in {workspace_path}")
        return False
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")
        logger.error(f"git push failed in {workspace_path}: {err}")
        return False
    return True
