"""GitHub issue creation from code review findings.

After the 5 review agents complete, this module spawns a Claude Code session
that parses the combined review output, checks for duplicate issues via
``gh issue list --search``, and creates new issues for novel findings.
"""

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REPO_RE = re.compile(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$")

# Labels and their colors for code review issues
_LABELS: dict[str, tuple[str, str]] = {
    "code-review": ("Automated code review finding", "C5DEF5"),
    "security": ("Security vulnerability or concern", "D73A4A"),
    "dependencies": ("Dependency vulnerability or update", "0075CA"),
    "testing": ("Test coverage gap", "BFD4F2"),
    "documentation": ("Documentation issue", "0E8A16"),
    "code-quality": ("Code quality or maintainability issue", "E4E669"),
}


async def _run_gh(
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


async def detect_repo(target_path: str) -> str | None:
    """Auto-detect the GitHub ``owner/name`` from a local directory."""
    rc, out, _ = await _run_gh(
        ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        cwd=target_path,
    )
    if rc == 0 and out.strip():
        repo = out.strip()
        if _REPO_RE.match(repo):
            return repo
    return None


async def _ensure_labels(repo: str) -> None:
    """Create code-review labels if they don't already exist."""
    for name, (description, color) in _LABELS.items():
        await _run_gh(
            [
                "label",
                "create",
                name,
                "--repo",
                repo,
                "--description",
                description,
                "--color",
                color,
            ],
        )
        # Non-zero exit is fine — label likely already exists


async def create_issues_from_review(
    review_output: str,
    target_path: str,
    repo: str,
    model: str = "sonnet",
) -> dict[str, Any]:
    """Create GitHub issues from code review findings.

    Writes the review report to a temp file, then spawns a Claude Code
    session that reads the report, searches for duplicates, and creates
    new issues via ``gh``.

    Returns a dict with ``created``, ``skipped``, ``failed`` counts
    and a ``success`` flag.
    """
    from agent_framework.tools.claude_code import run_claude_code

    # Ensure labels exist before Claude Code tries to use them
    await _ensure_labels(repo)

    # Write review output to a temp file so Claude Code can read it
    # (avoids CLI argument size limits for large reports)
    review_file = Path(target_path) / ".code-review-output.md"
    review_file.write_text(review_output)

    try:
        folder_name = Path(target_path).name
        parent_path = str(Path(target_path).parent)

        command = _build_issue_creation_prompt(repo)

        # Strip caller's API key so Claude Code uses its own
        custom_env = os.environ.copy()
        custom_env.pop("ANTHROPIC_API_KEY", None)

        logger.info("Creating GitHub issues for %s from review findings...", repo)

        result = await run_claude_code(
            folder_name=folder_name,
            command=command,
            model=model,
            working_dir_base=parent_path,
            max_turns=50,
            timeout=600,  # 10 minutes
            env=custom_env,
        )

        output = result.get("output", "")
        summary = _parse_issue_summary(output)
        summary["success"] = result.get("success", False)

        logger.info(
            "Issue creation complete: %d created, %d skipped, %d failed",
            summary["created"],
            summary["skipped"],
            summary["failed"],
        )

        return summary

    finally:
        review_file.unlink(missing_ok=True)


def _build_issue_creation_prompt(repo: str) -> str:
    """Build the prompt for the issue-creation Claude Code session."""
    return f"""Read the code review report from the file .code-review-output.md in this directory.

Your task is to create GitHub issues for each **distinct, actionable finding** in the report.
Ignore informational notes, summaries, and headers — only create issues for concrete problems
or recommendations that a developer should act on.

For EACH finding, follow these steps in order:

1. **Formulate a concise title** (max 80 chars) that uniquely identifies the finding.
   Prefix with the category, e.g. "[Security] SQL injection in user_handler.py".

2. **Check for duplicates** — run BOTH searches:
       gh issue list --repo {repo} --state all --search "<3-5 key terms>" --json number,title
       gh issue list --repo {repo} --label code-review --state all --json number,title
   Compare your proposed title against ALL returned issue titles. If ANY existing issue
   covers the same problem (even if the wording differs), SKIP this finding. Err on the
   side of skipping — a missed duplicate is worse than a missed new issue.

3. **Create the issue** (only if no duplicate found):
       gh issue create --repo {repo} \\
         --title "<title>" \\
         --body "<body>" \\
         --label "code-review" --label "<category-label>"

   The body should include:
   - One-paragraph description of the problem
   - Affected file(s) and line numbers (if available)
   - Recommended fix or next steps
   - Severity (low / medium / high / critical)

   Category labels to use:
   - Security findings → "security"
   - Dependency / CVE findings → "dependencies"
   - Test coverage gaps → "testing"
   - Documentation issues → "documentation"
   - Code quality / optimization → "code-quality"

After processing ALL findings, output exactly this summary block (with real numbers):

ISSUE_SUMMARY_START
Created: <N>
Skipped (duplicate): <N>
Failed: <N>
ISSUE_SUMMARY_END"""


def _parse_issue_summary(output: str) -> dict[str, Any]:
    """Parse the issue creation summary from Claude Code output."""
    summary: dict[str, int] = {"created": 0, "skipped": 0, "failed": 0}

    match = re.search(
        r"ISSUE_SUMMARY_START\s*\n"
        r"Created:\s*(\d+)\s*\n"
        r"Skipped.*?:\s*(\d+)\s*\n"
        r"Failed:\s*(\d+)\s*\n"
        r"ISSUE_SUMMARY_END",
        output,
    )
    if match:
        summary["created"] = int(match.group(1))
        summary["skipped"] = int(match.group(2))
        summary["failed"] = int(match.group(3))

    return summary
