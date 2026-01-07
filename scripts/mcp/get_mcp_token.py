"""
OAuth token fetcher for MCP server.

This script implements the OAuth authorization code flow with PKCE
to obtain a valid access token from the MCP authorization server.
"""

import asyncio
import sys
from pathlib import Path
import httpx
import webbrowser
from aiohttp import web
from urllib.parse import urlencode

# Add shared module to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.oauth_flow import generate_pkce_pair

# OAuth configuration
AUTH_SERVER = "https://mcp-auth.brooksmcmillin.com"
REDIRECT_URI = "http://localhost:8889/callback"
SCOPES = "read"


async def get_oauth_token() -> str | None:
    """Get OAuth access token using authorization code flow with PKCE."""

    # Generate PKCE pair
    code_verifier, code_challenge = generate_pkce_pair()

    # Register a dynamic OAuth client
    print("Registering OAuth client...")
    async with httpx.AsyncClient() as client:
        registration_response = await client.post(
            f"{AUTH_SERVER}/register",
            json={
                "redirect_uris": [REDIRECT_URI],
                "token_endpoint_auth_method": "none",  # Public client
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )

        if registration_response.status_code != 201:
            print(f"Failed to register client: {registration_response.status_code}")
            print(registration_response.text)
            return None

        client_data = registration_response.json()
        client_id = client_data["client_id"]
        print(f"✅ Registered client: {client_id}")

    # Build authorization URL
    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{AUTH_SERVER}/authorize?{urlencode(auth_params)}"

    print("\n🌐 Opening browser for authentication...")
    print(f"If browser doesn't open, visit: {auth_url}\n")

    # Open browser
    webbrowser.open(auth_url)

    # Set up callback server
    auth_code = None
    app = web.Application()

    async def callback(request):
        nonlocal auth_code
        auth_code = request.query.get("code")
        if auth_code:
            return web.Response(
                text="✅ Authorization successful! You can close this window.",
                content_type="text/html",
            )
        else:
            error = request.query.get("error", "Unknown error")
            return web.Response(
                text=f"❌ Authorization failed: {error}", content_type="text/html"
            )

    app.router.add_get("/callback", callback)

    # Start server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 8889)
    await site.start()

    print("⏳ Waiting for authorization callback...")

    # Wait for callback
    while auth_code is None:
        await asyncio.sleep(0.5)

    await runner.cleanup()

    print("✅ Received authorization code")

    # Exchange code for token
    print("🔄 Exchanging code for access token...")
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            f"{AUTH_SERVER}/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            print(f"❌ Failed to exchange code for token: {token_response.status_code}")
            print(token_response.text)
            return None

        token_data = token_response.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        print("\n✅ Successfully obtained access token!")
        print(f"\nAccess Token: {access_token}")
        if refresh_token:
            print(f"Refresh Token: {refresh_token}")

        print("\n📝 Add this to your .env file:")
        print(f"MCP_AUTH_TOKEN={access_token}")

        return access_token


async def main():
    """Main entry point."""
    try:
        await get_oauth_token()
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
