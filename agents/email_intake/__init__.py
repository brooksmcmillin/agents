"""Email Intake Agent.

Monitors an email inbox for task requests from the admin and routes them
to appropriate agents for processing.

Usage:
    # Run once (check emails and process)
    uv run python -m agents.email_intake.main

    # Interactive mode
    uv run python -m agents.email_intake.main --interactive

    # Dry run
    uv run python -m agents.email_intake.main --dry-run

Environment Variables:
    INTAKE_EMAIL_ADDRESS: The email address to monitor for incoming tasks
    ADMIN_EMAIL_ADDRESS: Only process emails from this address
    FASTMAIL_API_TOKEN: Required for email access
"""

__version__ = "0.1.0"
