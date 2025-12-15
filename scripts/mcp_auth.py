#!/usr/bin/env python3
"""OAuth authentication for remote MCP server.

This script runs a PKCE OAuth flow to authenticate with your remote MCP server
and stores the access token for use by agents.

Usage:
    uv run python scripts/mcp_auth.py
    uv run python scripts/mcp_auth.py test      # Test connection
    uv run python scripts/mcp_auth.py config    # Show configuration
"""

import asyncio
import base64
import hashlib
import os
import secrets
import sys
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from aiohttp import web
from dotenv import load_dotenv, set_key

# Load environment variables
load_dotenv()

# MCP Server Configuration
MCP_SERVER_BASE = os.getenv("MCP_SERVER_URL", "https://mcp.brooksmcmillin.com/mcp")


def discover_oauth_endpoints() -> dict[str, str]:
    """Discover OAuth endpoints from MCP server's well-known metadata.

    Returns:
        Dict with authorize_url, token_url, register_url, and scope
    """
    # Try to get the base URL (remove /mcp, etc)
    from urllib.parse import urlparse
    parsed = urlparse(MCP_SERVER_BASE)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    well_known_urls = [
        f"{base_url}/.well-known/oauth-authorization-server",
        f"{MCP_SERVER_BASE}/.well-known/oauth-authorization-server",
    ]

    import httpx
    for url in well_known_urls:
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(url)
                if response.status_code == 200:
                    metadata = response.json()
                    return {
                        "authorize_url": metadata.get("authorization_endpoint"),
                        "token_url": metadata.get("token_endpoint"),
                        "register_url": metadata.get("registration_endpoint"),
                        "scope": metadata.get("scopes_supported", ["mcp:access"])[0],
                    }
        except Exception:
            continue

    # Fallback to manual configuration
    auth_base = MCP_SERVER_BASE.removesuffix('/mcp')
    return {
        "authorize_url": os.getenv("MCP_AUTHORIZE_URL", f"{auth_base}/authorize"),
        "token_url": os.getenv("MCP_TOKEN_URL", f"{auth_base}/token"),
        "register_url": os.getenv("MCP_REGISTER_URL", f"{auth_base}/register"),
        "scope": os.getenv("MCP_OAUTH_SCOPE", "mcp:access"),
    }


# Discover OAuth endpoints
_discovered = discover_oauth_endpoints()

MCP_OAUTH_CONFIG = {
    "authorize_url": _discovered["authorize_url"],
    "token_url": _discovered["token_url"],
    "register_url": _discovered["register_url"],
    "redirect_uri": "http://localhost:8889/callback",
    "scope": _discovered["scope"],
}


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge.

    Returns:
        Tuple of (code_verifier, code_challenge)
    """
    # Generate random verifier (43-128 characters)
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')

    # Create SHA256 challenge
    challenge_bytes = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')

    return code_verifier, code_challenge


class MCPAuth:
    """Interactive OAuth setup for MCP server authentication using PKCE."""

    def __init__(self, auto_register: bool = True):
        """Initialize MCP authentication.

        Args:
            auto_register: If True, automatically register a new OAuth client.
                          If False, use existing client_id from environment.
        """
        self.redirect_uri = MCP_OAUTH_CONFIG["redirect_uri"]
        self.state = secrets.token_urlsafe(32)
        self.auth_code = None
        self.server_runner = None
        self.auto_register = auto_register
        self.client_id: str | None = None

        # Generate PKCE parameters
        self.code_verifier, self.code_challenge = generate_pkce_pair()

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
                <head><title>MCP Authorization Successful</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1>✅ MCP Authorization Successful!</h1>
                    <p>You can close this window and return to the terminal.</p>
                    <p style="color: #666; margin-top: 30px;">
                        Your agent can now connect to the MCP server.
                    </p>
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

        site = web.TCPSite(runner, "localhost", 8889)
        await site.start()

        self.server_runner = runner
        print(f"🌐 Callback server started on {self.redirect_uri}")

    async def stop_server(self):
        """Stop callback server."""
        if self.server_runner:
            await self.server_runner.cleanup()
            print("🛑 Callback server stopped")

    async def register_client(self) -> str | None:
        """Dynamically register a new OAuth client using RFC 7591.

        Returns:
            Client ID if successful, None otherwise
        """
        register_url = MCP_OAUTH_CONFIG["register_url"]

        registration_data = {
            "redirect_uris": [self.redirect_uri],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # Public client (PKCE)
            "scope": MCP_OAUTH_CONFIG["scope"],
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    register_url,
                    json=registration_data,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code in (200, 201):
                    data = response.json()
                    client_id = data.get("client_id")

                    if client_id:
                        print(f"✅ Registered new OAuth client: {client_id}")

                        # Save to .env for future use (without quotes)
                        env_path = Path(".env")
                        if not env_path.exists():
                            env_path.touch()
                        set_key(env_path, "MCP_CLIENT_ID", client_id, quote_mode='never')

                        return client_id
                    else:
                        print(f"❌ No client_id in registration response: {data}")
                        return None
                else:
                    print(f"❌ Client registration failed: {response.status_code}")
                    print(f"   Response: {response.text}")
                    return None

        except Exception as e:
            print(f"❌ Error during client registration: {e}")
            return None

    async def exchange_code_for_token(self) -> dict | None:
        """Exchange authorization code for access token using PKCE.

        Returns:
            Token data dict if successful, None otherwise
        """
        token_url = MCP_OAUTH_CONFIG["token_url"]

        data = {
            "grant_type": "authorization_code",
            "code": self.auth_code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": self.code_verifier,  # PKCE verification
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    token_url,
                    data=data,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                )

                if response.status_code == 200:
                    token_data = response.json()
                    return token_data
                else:
                    print(f"❌ Token exchange failed: {response.status_code}")
                    print(f"   Response: {response.text}")
                    return None

        except Exception as e:
            print(f"❌ Error during token exchange: {e}")
            return None

    async def run_oauth_flow(self) -> bool:
        """Run the complete PKCE OAuth flow.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Step 1: Register or get client ID
            if self.auto_register:
                print("🔧 Registering OAuth client...")
                self.client_id = await self.register_client()
                if not self.client_id:
                    print("❌ Failed to register OAuth client")
                    return False
            else:
                self.client_id = os.getenv("MCP_CLIENT_ID")
                if not self.client_id:
                    print("❌ No MCP_CLIENT_ID found in environment")
                    print("   Either set MCP_CLIENT_ID or use auto-registration")
                    return False

            # Step 2: Start callback server
            await self.run_server()

            # Step 3: Generate authorization URL with PKCE
            auth_params = {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "state": self.state,
                "code_challenge": self.code_challenge,
                "code_challenge_method": "S256",  # SHA-256
            }

            if MCP_OAUTH_CONFIG["scope"]:
                auth_params["scope"] = MCP_OAUTH_CONFIG["scope"]

            auth_url = f"{MCP_OAUTH_CONFIG['authorize_url']}?{urlencode(auth_params)}"

            print(f"\n{'='*70}")
            print("MCP Server Authentication (PKCE Flow)")
            print(f"{'='*70}\n")
            print(f"Server: {MCP_SERVER_BASE}")
            print(f"Client ID: {self.client_id}")
            print("Using PKCE: ✅ (No client secret needed)")
            print("\n📋 Steps:")
            print("1. Your browser will open to the login page")
            print("2. Log in with your credentials")
            print("3. Grant the requested permissions")
            print("4. You'll be redirected back to this script")
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

            # Step 4: Exchange code for token (with PKCE verifier)
            print("\n🔄 Exchanging authorization code for access token (with PKCE)...")

            token_data = await self.exchange_code_for_token()

            if token_data and "access_token" in token_data:
                access_token = token_data["access_token"]
                refresh_token = token_data.get("refresh_token")

                print("✅ Access token received!")

                # Save tokens to .env file (without quotes)
                env_path = Path(".env")
                if not env_path.exists():
                    env_path.touch()

                # Use quote_mode='never' to avoid wrapping in quotes
                set_key(env_path, "MCP_AUTH_TOKEN", access_token, quote_mode='never')
                if refresh_token:
                    set_key(env_path, "MCP_REFRESH_TOKEN", refresh_token, quote_mode='never')
                    print("✅ Refresh token also saved!")

                print("\n💾 Token saved to .env file as MCP_AUTH_TOKEN")

                # Show token info
                if "expires_in" in token_data:
                    expires_hours = token_data["expires_in"] / 3600
                    print(f"⏱️  Token expires in: {expires_hours:.1f} hours")

                print(f"\n{'='*70}")
                print("🎉 Authentication successful!")
                print(f"{'='*70}")
                print("\nYour agents can now connect to the MCP server.")
                print("The token will be automatically used when connecting.")

                return True
            else:
                print("\n❌ Failed to obtain access token")
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


async def test_connection():
    """Test the connection to the MCP server with the stored token."""
    print("\n🔍 Testing connection to MCP server...")

    # Need to reload .env since we just wrote to it
    load_dotenv(override=True)

    token = os.getenv("MCP_AUTH_TOKEN")
    if not token:
        print("❌ No token found in environment")
        return False

    try:
        # Import RemoteMCPClient
        import sys
        from pathlib import Path

        # Add parent directory to path for imports
        parent_dir = Path(__file__).parent.parent
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))

        from shared.remote_mcp_client import RemoteMCPClient

        # Try to connect and list tools
        async with RemoteMCPClient(MCP_SERVER_BASE, auth_token=token) as client:
            tools = await client.list_tools()

            print("✅ Connection successful!")
            print("   Connected to MCP server")
            print(f"   Available tools: {len(tools)}")
            if tools:
                print(f"   Sample tools: {', '.join([t['name'] for t in tools[:3]])}")
                if len(tools) > 3:
                    print(f"   ... and {len(tools) - 3} more")
            return True

    except Exception as e:
        print(f"❌ Connection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def show_config():
    """Display current OAuth configuration."""
    print("\n📋 Current MCP OAuth Configuration:\n")
    print(f"  MCP Server: {MCP_SERVER_BASE}")

    # Show if endpoints were discovered
    from urllib.parse import urlparse
    auth_domain = urlparse(MCP_OAUTH_CONFIG['authorize_url']).netloc
    mcp_domain = urlparse(MCP_SERVER_BASE).netloc
    if auth_domain != mcp_domain:
        print(f"  Auth Server: https://{auth_domain} (auto-discovered ✅)")

    print(f"  Authorize URL: {MCP_OAUTH_CONFIG['authorize_url']}")
    print(f"  Token URL: {MCP_OAUTH_CONFIG['token_url']}")
    print(f"  Register URL: {MCP_OAUTH_CONFIG['register_url']}")
    print(f"  Client ID: {os.getenv('MCP_CLIENT_ID') or '⚙️  Will auto-register'}")
    print("  Auth Method: PKCE (no client secret needed)")
    print(f"  Redirect URI: {MCP_OAUTH_CONFIG['redirect_uri']}")
    print(f"  Scope: {MCP_OAUTH_CONFIG['scope']}")
    print(f"  Current Token: {'✅ Set' if os.getenv('MCP_AUTH_TOKEN') else '❌ Not set'}")
    print()


async def main():
    """Main entry point."""
    # Check if user wants to see config
    if len(sys.argv) > 1 and sys.argv[1] == "config":
        show_config()
        return

    # Check if user wants to test connection
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        await test_connection()
        return

    # Show current configuration
    show_config()

    # Ask user if they want to use auto-registration or existing client
    use_auto_register = True
    if os.getenv("MCP_CLIENT_ID"):
        print("Found existing MCP_CLIENT_ID in .env")
        response = input("Use existing client ID? (y/N): ")
        use_auto_register = response.lower() != "y"

    try:
        mcp_auth = MCPAuth(auto_register=use_auto_register)
        success = await mcp_auth.run_oauth_flow()

        if success:
            # Test the connection
            await test_connection()
        else:
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
