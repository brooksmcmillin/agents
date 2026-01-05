#!/usr/bin/env python3
"""OAuth setup script for social media platforms.

This script runs a local OAuth flow to obtain and store access tokens
for Twitter, LinkedIn, or other platforms.

Usage:
    uv run python scripts/oauth_setup.py twitter
    uv run python scripts/oauth_setup.py linkedin
"""

import asyncio
import os
import secrets
import sys
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aiohttp import web
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.auth.oauth_handler import OAuthHandler
from mcp_server.auth.token_store import TokenStore

# Load environment variables
load_dotenv()


class OAuthSetup:
    """Interactive OAuth setup with local callback server."""

    def __init__(self, platform: str):
        """Initialize OAuth setup.

        Args:
            platform: Platform name (twitter, linkedin, etc.)
        """
        self.platform = platform
        self.redirect_uri = "http://localhost:8888/callback"
        self.state = secrets.token_urlsafe(32)
        self.auth_code = None
        self.server_runner = None

        # Initialize token store
        storage_path = Path(os.getenv("TOKEN_STORAGE_PATH", "./tokens"))
        encryption_key = os.getenv("TOKEN_ENCRYPTION_KEY")

        if not encryption_key:
            print("⚠️  No TOKEN_ENCRYPTION_KEY found in .env")
            print("Generating a new encryption key...")
            encryption_key = Fernet.generate_key().decode()
            print(f"\n🔑 Add this to your .env file:")
            print(f"TOKEN_ENCRYPTION_KEY={encryption_key}\n")

        self.token_store = TokenStore(storage_path, encryption_key)

        # Get OAuth credentials from environment
        client_id = os.getenv(f"{platform.upper()}_CLIENT_ID")
        client_secret = os.getenv(f"{platform.upper()}_CLIENT_SECRET")

        if not client_id or not client_secret:
            raise ValueError(
                f"Missing OAuth credentials for {platform}. "
                f"Please set {platform.upper()}_CLIENT_ID and "
                f"{platform.upper()}_CLIENT_SECRET in your .env file."
            )

        self.oauth_handler = OAuthHandler(
            token_store=self.token_store,
            client_id=client_id,
            client_secret=client_secret,
        )

    async def handle_callback(self, request: web.Request) -> web.Response:
        """Handle OAuth callback from authorization server."""
        # Parse query parameters
        params = parse_qs(urlparse(str(request.url)).query)

        # Verify state to prevent CSRF
        if params.get("state", [""])[0] != self.state:
            return web.Response(
                text="❌ Invalid state parameter. Possible CSRF attack.",
                status=400
            )

        # Get authorization code
        if "code" in params:
            self.auth_code = params["code"][0]
            response_html = """
            <html>
                <head><title>Authorization Successful</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>✅ Authorization Successful!</h1>
                    <p>You can close this window and return to the terminal.</p>
                </body>
            </html>
            """
            return web.Response(text=response_html, content_type="text/html")
        elif "error" in params:
            error = params["error"][0]
            error_description = params.get("error_description", ["Unknown error"])[0]
            response_html = f"""
            <html>
                <head><title>Authorization Failed</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>❌ Authorization Failed</h1>
                    <p><strong>Error:</strong> {error}</p>
                    <p>{error_description}</p>
                    <p>Please close this window and try again.</p>
                </body>
            </html>
            """
            return web.Response(text=response_html, content_type="text/html", status=400)
        else:
            return web.Response(text="❌ Missing authorization code", status=400)

    async def run_server(self):
        """Run temporary callback server."""
        app = web.Application()
        app.router.add_get("/callback", self.handle_callback)

        runner = web.AppRunner(app)
        await runner.setup()

        site = web.TCPSite(runner, "localhost", 8888)
        await site.start()

        self.server_runner = runner
        print(f"🌐 Callback server started on {self.redirect_uri}")

    async def stop_server(self):
        """Stop callback server."""
        if self.server_runner:
            await self.server_runner.cleanup()
            print("🛑 Callback server stopped")

    async def run_oauth_flow(self):
        """Run the complete OAuth flow."""
        try:
            # Step 1: Start callback server
            await self.run_server()

            # Step 2: Generate authorization URL
            auth_url = self.oauth_handler.get_authorization_url(
                platform=self.platform,
                redirect_uri=self.redirect_uri,
                state=self.state,
            )

            print(f"\n{'='*70}")
            print(f"Starting OAuth flow for {self.platform.upper()}")
            print(f"{'='*70}\n")
            print("📋 Steps:")
            print("1. Your browser will open to authorize the application")
            print("2. Log in and grant the requested permissions")
            print("3. You'll be redirected back to this script")
            print("\n🔗 Authorization URL:")
            print(f"{auth_url}\n")

            input("Press Enter to open browser...")

            # Open browser
            webbrowser.open(auth_url)

            print("\n⏳ Waiting for authorization callback...")

            # Wait for callback (with timeout)
            timeout = 300  # 5 minutes
            start_time = asyncio.get_event_loop().time()

            while not self.auth_code:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    raise TimeoutError("OAuth flow timed out after 5 minutes")
                await asyncio.sleep(0.5)

            print("✅ Authorization code received!")

            # Step 3: Exchange code for token
            print("\n🔄 Exchanging authorization code for access token...")

            token_data = await self.oauth_handler.exchange_code_for_token(
                platform=self.platform,
                code=self.auth_code,
                redirect_uri=self.redirect_uri,
                user_id="default",
            )

            if token_data:
                print("\n✅ Token obtained and saved successfully!")
                print(f"\n📦 Token details:")
                print(f"   Token type: {token_data.token_type}")
                print(f"   Has refresh token: {bool(token_data.refresh_token)}")
                if token_data.expires_at:
                    print(f"   Expires at: {token_data.expires_at}")
                if token_data.scope:
                    print(f"   Scopes: {token_data.scope}")

                # Show storage location
                token_path = self.token_store._get_token_path(self.platform, "default")
                print(f"\n💾 Token stored at: {token_path}")

                return True
            else:
                print("\n❌ Failed to obtain token")
                return False

        except TimeoutError as e:
            print(f"\n⏱️  {e}")
            return False
        except Exception as e:
            print(f"\n❌ Error during OAuth flow: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            await self.stop_server()


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: uv run python scripts/oauth_setup.py <platform>")
        print("\nSupported platforms:")
        print("  - twitter")
        print("  - linkedin")
        sys.exit(1)

    platform = sys.argv[1].lower()

    try:
        oauth_setup = OAuthSetup(platform)
        success = await oauth_setup.run_oauth_flow()

        if success:
            print("\n" + "="*70)
            print("🎉 OAuth setup complete!")
            print("="*70)
            print("\nYou can now use the MCP tools that require authentication.")
        else:
            print("\n" + "="*70)
            print("❌ OAuth setup failed")
            print("="*70)
            sys.exit(1)

    except ValueError as e:
        print(f"\n❌ Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
