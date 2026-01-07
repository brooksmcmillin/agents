#!/usr/bin/env python3
"""Clear cached OAuth tokens.

This is useful when you have a stale token cached in ~/.agents/tokens/
that's conflicting with your updated .env token.

Usage:
    uv run python scripts/clear_token_cache.py
"""

from pathlib import Path


def main():
    """Clear OAuth token cache."""
    token_dir = Path.home() / ".agents" / "tokens"

    if not token_dir.exists():
        print("✅ No token cache directory found - nothing to clear")
        return

    # Count tokens
    token_files = list(token_dir.glob("*.json"))

    if not token_files:
        print("✅ No cached tokens found - nothing to clear")
        return

    print(f"Found {len(token_files)} cached token(s):")
    for token_file in token_files:
        print(f"  - {token_file.name}")

    # Confirm deletion
    response = input("\nDelete all cached tokens? (y/N): ")

    if response.lower() != "y":
        print("❌ Cancelled - no tokens deleted")
        return

    # Delete tokens
    deleted = 0
    for token_file in token_files:
        try:
            token_file.unlink()
            deleted += 1
        except Exception as e:
            print(f"❌ Failed to delete {token_file.name}: {e}")

    print(f"\n✅ Deleted {deleted} cached token(s)")
    print("\nYour next connection will use the token from .env")


if __name__ == "__main__":
    main()
