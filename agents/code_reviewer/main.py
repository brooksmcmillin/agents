#!/usr/bin/env python3
"""Code review batch runner.

Runs 5 specialized code review agents on a target directory using Claude Code,
then emails the combined report to the admin.

Usage:
    uv run python -m agents.code_reviewer.main /path/to/review
    uv run python -m agents.code_reviewer.main /path/to/review --no-email

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


async def run_review(folder_path: str, model: str = "opus") -> str | None:
    """Run code review agents on the target directory.

    Returns the review output, or None on failure.
    """
    from agent_framework.tools.claude_code import run_claude_code

    folder_name = Path(folder_path).name
    parent_path = str(Path(folder_path).parent)

    # Command tells Claude Code to run all 5 review agents sequentially
    command = """Run these 5 code review agents SEQUENTIALLY (do NOT run them in the background):

1. code-optimizer - Analyze maintainability, duplication, and complexity
2. security-code-reviewer - Scan for vulnerabilities and security issues
3. doc-auditor - Check for stale/inconsistent documentation
4. dependency-auditor - Audit for CVEs and outdated packages
5. test-coverage-checker - Identify untested code paths

IMPORTANT: Run each agent one at a time, wait for it to complete, then run the next.
Do NOT use run_in_background=true. Collect all results and provide a combined summary."""

    # Create custom environment without the caller's ANTHROPIC_API_KEY
    # so the spawned Claude Code uses its own key
    custom_env = os.environ.copy()
    if "ANTHROPIC_API_KEY" in custom_env:
        del custom_env["ANTHROPIC_API_KEY"]

    logger.info(f"Starting code review of {folder_path}...")

    try:
        result = await run_claude_code(
            folder_name=folder_name,
            command=command,
            model=model,
            working_dir_base=parent_path,
            max_turns=100,
            timeout=1800,  # 30 minutes for 5 sequential reviews
            env=custom_env,
        )

        if result.get("success"):
            output = result.get("output", "")
            logger.info(f"Review completed ({len(output)} chars)")
            return output
        else:
            error_msg = result.get("error_output") or result.get("output", "Unknown error")
            logger.error(f"Review failed: {error_msg[:200]}")
            return None

    except Exception:
        logger.exception("Review crashed")
        return None


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

    # Run the review
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

    logger.info("Done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
