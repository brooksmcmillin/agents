#!/usr/bin/env python3
"""Clean up test conversations from the database.

This script removes all conversations with titles matching the test pattern (test_*).

Usage:
    uv run python scripts/cleanup_test_conversations.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()


async def cleanup_test_conversations():
    """Delete all conversations with test_ prefix in title."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable not set")
        sys.exit(1)

    try:
        import asyncpg
    except ImportError:
        print("Error: asyncpg not installed. Run: uv add asyncpg")
        sys.exit(1)

    print("Connecting to database...")

    # Connect to database
    conn = await asyncpg.connect(database_url)

    try:
        # Count test conversations
        count = await conn.fetchval("SELECT COUNT(*) FROM conversations WHERE title LIKE 'test_%'")
        print(f"Found {count} test conversations")

        if count == 0:
            print("No test conversations to delete")
            return

        # Ask for confirmation
        response = input(f"Delete {count} test conversations? (yes/no): ")
        if response.lower() not in ["yes", "y"]:
            print("Cancelled")
            return

        # Delete test conversations
        # The CASCADE will also delete associated messages
        deleted = await conn.execute("DELETE FROM conversations WHERE title LIKE 'test_%'")
        print(f"Deleted: {deleted}")

        # Verify
        remaining = await conn.fetchval(
            "SELECT COUNT(*) FROM conversations WHERE title LIKE 'test_%'"
        )
        print(f"Remaining test conversations: {remaining}")

    finally:
        await conn.close()

    print("Cleanup complete!")


if __name__ == "__main__":
    asyncio.run(cleanup_test_conversations())
