#!/usr/bin/env python3
"""Token management utility script.

View, refresh, or delete stored OAuth tokens.

Usage:
    # List all tokens
    uv run python scripts/manage_tokens.py list

    # Show details for a specific token
    uv run python scripts/manage_tokens.py show twitter

    # Refresh a token
    uv run python scripts/manage_tokens.py refresh twitter

    # Delete a token
    uv run python scripts/manage_tokens.py delete twitter

    # Generate encryption key
    uv run python scripts/manage_tokens.py generate-key
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.mcp_server.auth.oauth_handler import OAuthHandler
from config.mcp_server.auth.token_store import TokenStore

# Load environment variables
load_dotenv()


def get_token_store() -> TokenStore:
    """Initialize and return token store."""
    storage_path = Path(os.getenv("TOKEN_STORAGE_PATH", "./tokens"))
    encryption_key = os.getenv("TOKEN_ENCRYPTION_KEY")

    if not encryption_key:
        print("⚠️  Warning: No TOKEN_ENCRYPTION_KEY found. Tokens may be unencrypted.")

    return TokenStore(storage_path, encryption_key)


def list_tokens():
    """List all stored tokens."""
    token_store = get_token_store()
    token_files = list(token_store.storage_path.glob("*.token"))

    if not token_files:
        print("No tokens found.")
        return

    print(f"\n📦 Stored tokens ({len(token_files)}):\n")

    for token_file in token_files:
        # Parse filename: platform_userid.token
        parts = token_file.stem.split("_", 1)
        platform = parts[0]
        user_id = parts[1] if len(parts) > 1 else "default"

        # Try to load token
        token = token_store.get_token(platform, user_id)

        if token:
            status = "❌ Expired" if token.is_expired() else "✅ Valid"
            expiry_info = ""
            if token.expires_at:
                time_left = token.time_until_expiry()
                if time_left:
                    hours = int(time_left.total_seconds() / 3600)
                    expiry_info = f" (expires in {hours}h)"

            print(f"  {status} {platform}:{user_id}{expiry_info}")
        else:
            print(f"  ⚠️  {platform}:{user_id} (failed to load)")


def show_token(platform: str, user_id: str = "default"):
    """Show detailed token information."""
    token_store = get_token_store()
    token = token_store.get_token(platform, user_id)

    if not token:
        print(f"❌ No token found for {platform}:{user_id}")
        return

    print(f"\n📋 Token details for {platform}:{user_id}\n")
    print(f"  Token type: {token.token_type}")
    print(f"  Has refresh token: {bool(token.refresh_token)}")

    if token.expires_at:
        print(f"  Expires at: {token.expires_at}")
        if token.is_expired():
            print("  Status: ❌ Expired")
        else:
            time_left = token.time_until_expiry()
            if time_left:
                hours = int(time_left.total_seconds() / 3600)
                minutes = int((time_left.total_seconds() % 3600) / 60)
                print(f"  Time remaining: {hours}h {minutes}m")
                print("  Status: ✅ Valid")

    if token.scope:
        print(f"  Scopes: {token.scope}")

    # Show file location
    token_path = token_store._get_token_path(platform, user_id)
    print(f"\n  Stored at: {token_path}")


async def refresh_token(platform: str, user_id: str = "default"):
    """Refresh an expired token."""
    token_store = get_token_store()

    # Get OAuth credentials
    client_id = os.getenv(f"{platform.upper()}_CLIENT_ID")
    client_secret = os.getenv(f"{platform.upper()}_CLIENT_SECRET")

    if not client_id or not client_secret:
        print(f"❌ Missing OAuth credentials for {platform}")
        print(f"   Please set {platform.upper()}_CLIENT_ID and {platform.upper()}_CLIENT_SECRET")
        return

    oauth_handler = OAuthHandler(
        token_store=token_store,
        client_id=client_id,
        client_secret=client_secret,
    )

    print(f"🔄 Refreshing token for {platform}:{user_id}...")

    new_token = await oauth_handler.refresh_token(platform, user_id)

    if new_token:
        print("✅ Token refreshed successfully!")
        print(f"   Expires at: {new_token.expires_at}")
    else:
        print("❌ Failed to refresh token")
        print(
            "   You may need to re-authorize using: uv run python scripts/oauth_setup.py "
            + platform
        )


def delete_token(platform: str, user_id: str = "default"):
    """Delete a stored token."""
    token_store = get_token_store()

    confirm = input(f"⚠️  Delete token for {platform}:{user_id}? (y/N): ")
    if confirm.lower() != "y":
        print("Cancelled.")
        return

    if token_store.delete_token(platform, user_id):
        print(f"✅ Token deleted for {platform}:{user_id}")
    else:
        print("❌ Failed to delete token")


def generate_key():
    """Generate a new encryption key."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    print("\n🔑 Generated encryption key:")
    print(f"\nTOKEN_ENCRYPTION_KEY={key}\n")
    print("Add this to your .env file to enable token encryption.")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "list":
        list_tokens()

    elif command == "show":
        if len(sys.argv) < 3:
            print("Usage: uv run python scripts/manage_tokens.py show <platform> [user_id]")
            sys.exit(1)
        platform = sys.argv[2]
        user_id = sys.argv[3] if len(sys.argv) > 3 else "default"
        show_token(platform, user_id)

    elif command == "refresh":
        if len(sys.argv) < 3:
            print("Usage: uv run python scripts/manage_tokens.py refresh <platform> [user_id]")
            sys.exit(1)
        platform = sys.argv[2]
        user_id = sys.argv[3] if len(sys.argv) > 3 else "default"
        asyncio.run(refresh_token(platform, user_id))

    elif command == "delete":
        if len(sys.argv) < 3:
            print("Usage: uv run python scripts/manage_tokens.py delete <platform> [user_id]")
            sys.exit(1)
        platform = sys.argv[2]
        user_id = sys.argv[3] if len(sys.argv) > 3 else "default"
        delete_token(platform, user_id)

    elif command == "generate-key":
        generate_key()

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
