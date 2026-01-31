#!/usr/bin/env python3
"""Email intake agent runner.

Monitors an email inbox for task requests from the admin and routes them
to appropriate agents for processing.

Usage:
    # Run once (check emails and process)
    uv run python -m agents.email_intake.main

    # Interactive mode
    uv run python -m agents.email_intake.main --interactive

    # Dry run (don't actually send replies or modify emails)
    uv run python -m agents.email_intake.main --dry-run

Environment Variables:
    INTAKE_EMAIL_ADDRESS: The email address to monitor for incoming tasks
    ADMIN_EMAIL_ADDRESS: Only process emails from this address
    INTAKE_SHARED_SECRET: Required secret that must appear in email body (security)
    FASTMAIL_API_TOKEN: Required for email access

Security:
    This agent requires a shared secret to prevent email spoofing attacks.
    The secret must be present in the email body to be processed.
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Agent routing keywords
AGENT_KEYWORDS = {
    "pr": [
        "content",
        "seo",
        "website",
        "blog",
        "social media",
        "twitter",
        "linkedin",
        "marketing",
        "copywriting",
        "analyze website",
        "web content",
        "engagement",
    ],
    "security": [
        "security",
        "vulnerability",
        "cve",
        "exploit",
        "penetration",
        "pentest",
        "malware",
        "threat",
        "attack",
        "encryption",
        "authentication",
    ],
    "business": [
        "business",
        "monetization",
        "revenue",
        "pricing",
        "strategy",
        "market",
        "competitor",
        "startup",
        "funding",
        "investor",
    ],
    "tasks": [
        "task",
        "remind",
        "schedule",
        "todo",
        "deadline",
        "meeting",
        "calendar",
        "appointment",
    ],
    "events": [
        "event",
        "concert",
        "show",
        "festival",
        "local",
        "happening",
        "weekend",
        "entertainment",
    ],
}


def _match_keyword(keyword: str, content: str) -> bool:
    """Match a keyword using word boundaries to avoid false positives.

    Args:
        keyword: The keyword to search for
        content: The content to search in (should be lowercase)

    Returns:
        True if keyword matches as a whole word/phrase
    """
    # Use word boundaries to match whole words only
    # This prevents 'task' from matching inside 'attack'
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return bool(re.search(pattern, content))


def determine_agent(subject: str, body: str) -> str:
    """Determine which agent should handle the task based on content.

    Uses word boundary matching to avoid false positives from substring
    collisions (e.g., 'task' inside 'attack').

    Args:
        subject: Email subject line
        body: Email body text

    Returns:
        Agent name (chatbot, pr, security, business, tasks, events)
    """
    content = f"{subject} {body}".lower()

    # Score each agent based on keyword matches (using word boundaries)
    scores: dict[str, int] = {}
    for agent, keywords in AGENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if _match_keyword(kw, content))
        if score > 0:
            scores[agent] = score

    # Return the agent with highest score, or chatbot as default
    if scores:
        return max(scores, key=lambda x: scores[x])
    return "chatbot"


async def run_agent_task(agent_name: str, task: str) -> str:
    """Run a task through the specified agent.

    Args:
        agent_name: Name of the agent to use
        task: The task/prompt to send to the agent

    Returns:
        The agent's response text
    """
    # Import agent classes dynamically to avoid circular imports
    from agent_framework import Agent

    from agents.api.server import _build_registry

    registry = _build_registry()

    if agent_name not in registry:
        return f"Error: Agent '{agent_name}' not found. Available: {list(registry.keys())}"

    agent_class, kwargs, description = registry[agent_name]

    logger.info(f"Running {agent_name} agent: {description}")

    try:
        # Create agent instance
        agent: Agent = agent_class(**(kwargs or {}))

        # Process the task
        response = await agent.process_message(task)

        logger.info(
            f"Agent completed (tokens: {agent.total_input_tokens} in, "
            f"{agent.total_output_tokens} out)"
        )

        return response

    except Exception as e:
        logger.exception(f"Agent {agent_name} failed")
        return f"Error running {agent_name} agent: {e!s}"


async def check_and_process_emails(dry_run: bool = False) -> int:
    """Check inbox for new emails and process them.

    Args:
        dry_run: If True, don't actually send replies or modify emails

    Returns:
        Number of emails processed
    """
    from agent_framework.core.config import settings
    from agent_framework.tools.fastmail import (
        get_email,
        get_emails,
        move_email,
        send_email,
        update_email_flags,
    )

    # Validate configuration
    if not settings.intake_email_address:
        logger.error("INTAKE_EMAIL_ADDRESS not configured")
        return 0

    if not settings.admin_email_address:
        logger.error("ADMIN_EMAIL_ADDRESS not configured")
        return 0

    if not settings.fastmail_api_token:
        logger.error("FASTMAIL_API_TOKEN not configured")
        return 0

    if not settings.intake_shared_secret:
        logger.error(
            "INTAKE_SHARED_SECRET not configured - required for security. "
            "Generate a random string and add it to your .env file."
        )
        return 0

    intake_email = settings.intake_email_address.lower()
    admin_email = settings.admin_email_address.lower()
    shared_secret = settings.intake_shared_secret

    logger.info(f"Checking emails to: {intake_email}")
    logger.info(f"From admin: {admin_email}")

    # Get unread emails from inbox
    result = await get_emails(
        mailbox_role="inbox",
        filter_unread=True,
        limit=50,
    )

    if result.get("status") != "success":
        logger.error(f"Failed to get emails: {result.get('message')}")
        return 0

    emails = result.get("emails", [])
    logger.info(f"Found {len(emails)} unread emails")

    processed = 0

    for email_summary in emails:
        email_id = email_summary.get("id")
        subject = email_summary.get("subject", "(no subject)")
        from_list = email_summary.get("from", [])
        to_list = email_summary.get("to", [])

        # Extract sender email
        sender_email = ""
        if from_list:
            sender_email = from_list[0].get("email", "").lower()

        # Extract recipient emails
        recipient_emails = [r.get("email", "").lower() for r in to_list]

        # Check if this email is from admin to intake address
        if sender_email != admin_email:
            logger.debug(f"Skipping: not from admin ({sender_email})")
            continue

        if intake_email not in recipient_emails:
            logger.debug(f"Skipping: not to intake address ({recipient_emails})")
            continue

        logger.info(f"Processing email: {subject}")

        # Get full email content
        full_email_result = await get_email(email_id)
        if full_email_result.get("status") != "success":
            logger.error(f"Failed to get email content: {full_email_result.get('message')}")
            continue

        full_email = full_email_result.get("email", {})
        body_text = full_email.get("body_text", "")
        body_html = full_email.get("body_html", "")

        # Use text body, fall back to stripping HTML
        body = body_text or _strip_html(body_html)

        # Security: Validate shared secret is present in the email
        # This prevents email spoofing attacks where an attacker forges the From header
        if shared_secret not in body:
            logger.warning(
                f"SECURITY: Rejecting email - missing shared secret. "
                f"Subject: {subject}, From: {sender_email}"
            )
            continue

        # Remove the shared secret from the body before processing
        # so it doesn't get passed to agents or included in responses
        body = body.replace(shared_secret, "[SECRET_REDACTED]")

        # Mark as read immediately to prevent reprocessing if agent/reply fails
        # This prevents duplicate task execution on retry
        if not dry_run:
            await update_email_flags(email_id, mark_read=True)
            logger.debug(f"Marked email as read: {email_id}")

        # Determine which agent to use
        agent_name = determine_agent(subject, body)
        logger.info(f"Routing to agent: {agent_name}")

        # Build the task prompt
        task_prompt = f"""Process this email request:

Subject: {subject}

Body:
{body}

Provide a helpful response to this request."""

        # Run the agent
        agent_response = await run_agent_task(agent_name, task_prompt)

        # Compose reply
        reply_body = f"""Your request has been processed by the {agent_name} agent.

---
REQUEST SUMMARY:
Subject: {subject}

---
AGENT RESPONSE:

{agent_response}

---
Processed by Email Intake Agent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        if dry_run:
            logger.info("DRY RUN - Would send reply:")
            print(f"\n--- Reply to: {sender_email} ---")
            print(f"Subject: Re: {subject}")
            print(reply_body)
            print("--- End Reply ---\n")
        else:
            # Send reply
            reply_result = await send_email(
                to=[sender_email],
                subject=f"Re: {subject}",
                body=reply_body,
                reply_to_email_id=email_id,
                identity_email=intake_email,
            )

            if reply_result.get("status") != "success":
                logger.error(f"Failed to send reply: {reply_result.get('message')}")
                continue

            logger.info("Reply sent successfully")

            # Archive the email (already marked as read earlier)
            archive_result = await move_email(email_id, to_mailbox_role="archive")
            if archive_result.get("status") == "success":
                logger.info("Email archived")
            else:
                logger.warning(f"Failed to archive: {archive_result.get('message')}")

        processed += 1

    return processed


def _strip_html(html: str) -> str:
    """Strip HTML tags from content."""
    if not html:
        return ""
    # Simple HTML tag removal
    clean = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def show_status() -> None:
    """Show current configuration status."""
    from agent_framework.core.config import settings

    print("\nEmail Intake Agent Status")
    print("=" * 40)
    print(f"Intake Email:   {settings.intake_email_address or 'NOT CONFIGURED'}")
    print(f"Admin Email:    {settings.admin_email_address or 'NOT CONFIGURED'}")
    print(f"Shared Secret:  {'Configured' if settings.intake_shared_secret else 'NOT CONFIGURED (REQUIRED)'}")
    print(f"FastMail:       {'Configured' if settings.fastmail_api_token else 'NOT CONFIGURED'}")
    print()

    # Check which agents are available
    try:
        from agents.api.server import _build_registry

        registry = _build_registry()
        print("Available Agents:")
        for name, (_, _, desc) in registry.items():
            print(f"  - {name}: {desc}")
    except Exception as e:
        print(f"Error loading agents: {e}")

    print()


async def interactive_mode() -> None:
    """Run in interactive mode."""
    from .prompts import USER_GREETING_PROMPT

    print(USER_GREETING_PROMPT)

    while True:
        try:
            cmd = input("\n> ").strip().lower()

            if cmd in ("exit", "quit", "q"):
                print("Goodbye!")
                break
            elif cmd == "check":
                count = await check_and_process_emails()
                print(f"Processed {count} emails")
            elif cmd == "status":
                show_status()
            elif cmd == "help":
                print("Commands: check, status, exit")
            else:
                print("Unknown command. Type 'help' for available commands.")

        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Email intake agent - processes task requests from email",
    )

    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Run in interactive mode",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't send replies or modify emails, just show what would happen",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show configuration status and exit",
    )

    return parser.parse_args()


async def main() -> int:
    """Main entry point."""
    args = parse_args()

    if args.status:
        show_status()
        return 0

    if args.interactive:
        await interactive_mode()
        return 0

    # Default: run once and process emails
    logger.info("Email Intake Agent starting...")
    count = await check_and_process_emails(dry_run=args.dry_run)
    logger.info(f"Done. Processed {count} emails.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
