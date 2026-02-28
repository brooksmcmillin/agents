#!/usr/bin/env python3
"""Code review batch runner.

Runs 5 specialized code review agents on a target directory in parallel using
independent Claude Code sessions, then optionally emails the combined report
and creates GitHub issues for findings.

Each agent gets its own 10-minute timeout. If one agent fails or times out,
the others still produce results.

Usage:
    uv run python -m agents.code_reviewer.main /path/to/review
    uv run python -m agents.code_reviewer.main /path/to/review --no-email
    uv run python -m agents.code_reviewer.main /path/to/review --repo owner/name
    uv run python -m agents.code_reviewer.main /path/to/review --no-issues

Environment Variables:
    ADMIN_EMAIL_ADDRESS: Required for email delivery
    FASTMAIL_API_TOKEN: Required for email delivery
    FASTMAIL_ACCOUNT_ID: Required for email delivery
"""

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Each agent gets its own Claude Code session with independent timeout
REVIEW_AGENTS: list[dict[str, str]] = [
    {
        "name": "code-optimizer",
        "description": "Analyze maintainability, duplication, and complexity",
    },
    {
        "name": "security-code-reviewer",
        "description": "Scan for vulnerabilities and security issues",
    },
    {
        "name": "doc-auditor",
        "description": "Check for stale/inconsistent documentation",
    },
    {
        "name": "dependency-auditor",
        "description": "Audit for CVEs and outdated packages",
    },
    {
        "name": "test-coverage-checker",
        "description": "Identify untested code paths",
    },
]

PER_AGENT_TIMEOUT = 600  # 10 minutes per agent
PER_AGENT_MAX_TURNS = 30


@dataclass
class AgentResult:
    """Result from a single review agent."""

    name: str
    success: bool
    output: str
    error: str | None = None


async def _run_single_agent(
    agent: dict[str, str],
    folder_path: str,
    model: str,
    custom_env: dict[str, str],
) -> AgentResult:
    """Run a single review agent in its own Claude Code session."""
    from agent_framework.tools.claude_code import run_claude_code

    name = agent["name"]
    description = agent["description"]
    folder_name = Path(folder_path).name
    parent_path = str(Path(folder_path).parent)

    command = (
        f"Run the {name} agent to {description}. "
        f"Provide a thorough report of all findings with file paths, "
        f"line numbers, severity levels, and recommendations."
    )

    logger.info("Starting agent: %s", name)

    try:
        result = await run_claude_code(
            folder_name=folder_name,
            command=command,
            model=model,
            working_dir_base=parent_path,
            max_turns=PER_AGENT_MAX_TURNS,
            timeout=PER_AGENT_TIMEOUT,
            env=custom_env,
        )

        if result.get("success"):
            output = result.get("output", "")
            logger.info("Agent %s completed (%d chars)", name, len(output))
            return AgentResult(name=name, success=True, output=output)
        else:
            error_msg = result.get("error_output") or result.get("output", "Unknown error")
            logger.error("Agent %s failed: %s", name, error_msg[:200])
            return AgentResult(name=name, success=False, output="", error=error_msg[:500])

    except Exception as exc:
        logger.exception("Agent %s crashed", name)
        return AgentResult(name=name, success=False, output="", error=str(exc))


async def run_review(folder_path: str, model: str = "opus") -> str | None:
    """Run all review agents in parallel and combine results.

    Each agent runs in its own Claude Code session with an independent
    timeout. If some agents fail, the successful ones still contribute
    to the report.

    Returns the combined review output, or None if all agents failed.
    """
    # Allowlist: only pass environment variables the subprocess actually needs.
    # This prevents leaking secrets (API tokens, DB creds, etc.) to child processes.
    _ALLOWED_ENV_NAMES = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "TMPDIR",
        "TEMP",
        "TMP",
        "EDITOR",
        "VISUAL",
    }
    _ALLOWED_ENV_PREFIXES = (
        "LANG",
        "LC_",
        "XDG_",
    )
    custom_env = {
        k: v
        for k, v in os.environ.items()
        if k in _ALLOWED_ENV_NAMES or k.startswith(_ALLOWED_ENV_PREFIXES)
    }

    logger.info(
        "Starting code review of %s (%d agents in parallel)...", folder_path, len(REVIEW_AGENTS)
    )

    tasks = [_run_single_agent(agent, folder_path, model, custom_env) for agent in REVIEW_AGENTS]
    results: list[AgentResult] = await asyncio.gather(*tasks)

    # Build combined report from successful agents
    sections: list[str] = []
    succeeded = 0
    failed = 0

    for result in results:
        if result.success and result.output.strip():
            sections.append(f"## {result.name}\n\n{result.output.strip()}")
            succeeded += 1
        else:
            error_detail = result.error or "No output produced"
            sections.append(f"## {result.name}\n\n**Agent failed:** {error_detail[:300]}")
            failed += 1

    logger.info("Review complete: %d/%d agents succeeded", succeeded, len(REVIEW_AGENTS))

    if succeeded == 0:
        logger.error("All agents failed — no report generated")
        return None

    header = (
        f"# Code Review Report\n\n"
        f"**Target:** `{folder_path}`\n"
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"**Agents:** {succeeded}/{len(REVIEW_AGENTS)} succeeded"
        + (f" ({failed} failed)" if failed else "")
        + "\n\n---\n"
    )

    return header + "\n\n---\n\n".join(sections)


def markdown_to_html(md_content: str) -> str:
    """Convert markdown to styled HTML for email."""
    import markdown

    # Convert markdown to HTML with table and fenced code support
    html_body = markdown.markdown(
        md_content,
        extensions=["tables", "fenced_code", "nl2br"],
    )

    # Wrap in styled HTML template
    return f"""<!DOCTYPE html>
<html>
<head>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
h1, h2, h3 {{ color: #2c3e50; margin-top: 1.5em; }}
h2 {{ border-bottom: 2px solid #3498db; padding-bottom: 0.3em; }}
h3 {{ color: #2980b9; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
th {{ background-color: #3498db; color: white; }}
tr:nth-child(even) {{ background-color: #f9f9f9; }}
code {{ background-color: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-family: 'SF Mono', Consolas, monospace; }}
pre {{ background-color: #2d2d2d; color: #f8f8f2; padding: 15px; border-radius: 5px; overflow-x: auto; }}
pre code {{ background-color: transparent; padding: 0; }}
hr {{ border: none; border-top: 1px solid #eee; margin: 2em 0; }}
strong {{ color: #c0392b; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""


async def send_report(report: str, target_path: Path) -> bool:
    """Send the report via email to the admin."""
    from agent_framework.tools.fastmail import send_agent_report

    timestamp = datetime.now().strftime("%Y-%m-%d")
    subject = f"Code Review Report: {target_path.name} ({timestamp})"

    # Convert markdown to styled HTML
    html_report = markdown_to_html(report)

    logger.info("Sending email report...")

    try:
        result = await send_agent_report(
            subject=subject,
            body=html_report,
            is_html=True,
            agent_name="code-reviewer",
        )

        if result.get("status") == "success":
            logger.info(f"Email sent to {result.get('to_address')}")
            return True
        else:
            logger.error(f"Email failed: {result.get('message')}")
            return False

    except Exception:
        logger.exception("Email sending crashed")
        return False


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run code review agents on a directory and email the results.",
    )

    parser.add_argument(
        "target",
        type=str,
        help="Directory to review (path)",
    )

    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Skip sending email, just print report to stdout",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Save report to file (in addition to email)",
    )

    parser.add_argument(
        "--model",
        type=str,
        default="opus",
        choices=["sonnet", "haiku", "opus"],
        help="Claude model to use (default: opus)",
    )

    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="GitHub repo (owner/name) for issue creation. Auto-detected if omitted.",
    )

    parser.add_argument(
        "--no-issues",
        action="store_true",
        help="Skip creating GitHub issues from findings",
    )

    return parser.parse_args()


async def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Validate target path
    target_path = Path(args.target).resolve()
    if not target_path.exists():
        logger.error(f"Target does not exist: {target_path}")
        return 1
    if not target_path.is_dir():
        logger.error(f"Target is not a directory: {target_path}")
        return 1

    # Check required environment variables for email
    if not args.no_email:
        if not os.getenv("ADMIN_EMAIL_ADDRESS"):
            logger.error("ADMIN_EMAIL_ADDRESS required (or use --no-email)")
            return 1
        if not os.getenv("FASTMAIL_API_TOKEN"):
            logger.error("FASTMAIL_API_TOKEN required (or use --no-email)")
            return 1

    # Run the review (5 agents in parallel)
    report = await run_review(str(target_path), model=args.model)

    if not report:
        logger.error("No report generated")
        return 1

    # Output results
    if args.no_email:
        print("\n" + report)
    else:
        email_sent = await send_report(report, target_path)
        if not email_sent:
            logger.warning("Email failed, printing report to stdout instead")
            print("\n" + report)

    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(report)
        logger.info(f"Report saved to: {output_path}")

    # Create GitHub issues from findings
    if not args.no_issues:
        from agents.code_reviewer.github_issues import (
            create_issues_from_review,
            detect_repo,
        )

        repo = args.repo
        if not repo:
            logger.info("Auto-detecting GitHub repo...")
            repo = await detect_repo(str(target_path))

        if repo:
            logger.info(f"Creating GitHub issues for {repo}...")
            issue_result = await create_issues_from_review(
                review_output=report,
                target_path=str(target_path),
                repo=repo,
                model=args.model,
            )
            logger.info(
                "Issues: %d created, %d skipped (duplicate), %d failed",
                issue_result.get("created", 0),
                issue_result.get("skipped", 0),
                issue_result.get("failed", 0),
            )
        else:
            logger.warning("Could not detect GitHub repo. Use --repo owner/name to create issues.")

    logger.info("Done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
